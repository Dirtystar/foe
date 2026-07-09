"""GUI entrypoint: compose runtime + window, then run the Qt loop.

Mirrors bap.main but presents a window instead of logging. The application
is built by the composition root here (the only place that assembles it) and
handed to the GUI as a service + bridge; widgets receive those, never raw
runtime pieces.

Usage:
    python -m bap.gui.gui_main [config] [--real] [--real-vision]
Runs on stubs by default, so it is safe without a browser or vision libs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from bap.app.composition import create_application
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config
from bap.core.engine.health import HealthMonitor
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge
from bap.gui.runtime_service import RuntimeService
from bap.ops.status import OperationalState, OperationalStatus
from bap.ops.validation import validate_startup


def build_main_window(
    config, *, real: bool = False, real_vision: bool = False, store_path: str | None = None
):
    """Wire config -> application -> service/bridge -> window. Returns the
    window; the caller owns the Qt lifecycle."""
    bridge = QtReportBridge()

    # Operational status derives ready<->degraded from the health flow (in the
    # ops layer) and is pushed to the GUI as a signal — the window only displays it.
    state = OperationalState(
        on_change=lambda status, reason: bridge.on_status_change(status.value, reason)
    )

    # Report/health flow into the GUI. Optional persistence sits between the
    # supervisor and the bridge, storing everything without affecting the UI.
    report_sink = bridge.on_report
    health_sink = bridge.on_health_change
    on_close = None
    metrics_repository = None
    if store_path:
        from bap.adapters.persistence.sqlite_store import SqliteStateStore
        from bap.app.metrics.repository import MetricsRepository
        from bap.app.persistence_sink import PersistenceSink

        store = SqliteStateStore(store_path)
        persistence = PersistenceSink(
            store, report_sink=bridge.on_report, health_sink=bridge.on_health_change
        )
        report_sink = persistence.on_report
        health_sink = persistence.on_health
        # Read-only analytics view over the same file (separate ro connection).
        metrics_repository = MetricsRepository(store_path)

        def on_close() -> None:
            store.close()
            metrics_repository.close()

    # Head of the health chain: the operational-state observer derives
    # ready<->degraded from the same events the bridge/persistence already see.
    _downstream_health = health_sink

    def health_sink(profile_id, health, reason=""):  # noqa: F811
        state.observe_health(profile_id, health, reason)
        _downstream_health(profile_id, health, reason)

    # Recovery supervisor sits in the report path: it forwards every report to
    # the (persistence ->) GUI bridge and drives recovery on transient failures.
    supervisor = Supervisor(monitor=HealthMonitor(), sink=report_sink, on_health=health_sink)

    extra: dict = {}
    if real:
        from bap.main import _playwright_kwargs

        extra.update(_playwright_kwargs(config))
    if real_vision:
        from bap.adapters.vision.registry import production_analyzer_registry

        extra["analyzer_registry"] = production_analyzer_registry()
        extra["vision_workers"] = 4  # offload CPU-bound analyzers off the loop

    # Fail fast before assembling the runtime, same checks as the headless entry.
    validate_startup(
        config,
        store_path=store_path,
        analyzer_registry=extra.get("analyzer_registry"),
        action_registry=extra.get("action_registry"),
    )

    # Optional browser resource monitoring at the top of the report chain.
    top_sink = supervisor.on_report
    rm_cfg = config.settings.resource_monitoring
    browser_manager = extra.get("browser")
    if rm_cfg.enabled and browser_manager is not None:
        from bap.adapters.browser.playwright_metrics import PlaywrightBrowserMetrics
        from bap.app.resource_monitor import ResourceMonitor

        store_arg = store if store_path else None
        resource_monitor = ResourceMonitor(
            PlaywrightBrowserMetrics(browser_manager),
            collect_every=rm_cfg.collect_every_ticks,
            max_memory_mb=rm_cfg.limits.max_memory_mb,
            max_pages=rm_cfg.limits.max_pages,
            store=store_arg,
            report_sink=supervisor.on_report,
            on_pressure=supervisor.note_resource_pressure,
        )
        top_sink = resource_monitor.on_report

    app = create_application(config, on_report=top_sink, **extra)
    supervisor.session_manager = app.manager  # late-bind now that the manager exists
    service = RuntimeService(app)

    def _on_state_change(runtime_state: str) -> None:
        # Map the runtime's running/stopped to the operational lifecycle so the
        # status label reflects readiness; health events then derive degraded.
        if runtime_state == "running":
            state.transition(OperationalStatus.READY, "runtime running")
        else:
            state.transition(OperationalStatus.STOPPED, "runtime stopped")
        bridge.on_state_change(runtime_state)

    service.on_state_change = _on_state_change
    service.on_error = bridge.on_error
    service.start_loop()

    limits = config.settings.resource_monitoring.limits
    return MainWindow(
        service,
        bridge,
        on_close=on_close,
        metrics_repository=metrics_repository,
        max_memory_mb=limits.max_memory_mb,
        max_pages=limits.max_pages,
    )


def run_gui(
    config_path,
    *,
    real: bool = False,
    real_vision: bool = False,
    store_path: str | None = None,
    exec_app: bool = True,
) -> int:
    """Load config, build the window, and run the Qt loop. Returns an exit code.

    Config problems (ConfigError / OperationalError) are reported and return 2
    without opening a window. `exec_app=False` builds and shows the window but
    returns immediately without entering the Qt event loop — used by tests to
    verify the entry point wires up without blocking.
    """
    from PySide6.QtWidgets import QApplication

    from bap.config.config_loader import ConfigError
    from bap.ops.validation import OperationalError

    logger = logging.getLogger("bap")
    try:
        config = load_config(Path(config_path))
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    qapp = QApplication.instance() or QApplication(sys.argv)
    try:
        window = build_main_window(
            config, real=real, real_vision=real_vision, store_path=store_path
        )
    except OperationalError as exc:
        logger.error("Startup aborted: %s", exc)
        return 2
    window.resize(900, 600)
    window.show()
    if not exec_app:
        return 0
    return int(qapp.exec())


def main(argv: list[str] | None = None) -> None:
    from bap import __version__

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        prog="bap-gui", description="Browser Automation Platform — GUI monitor"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("config", nargs="?", default=None)
    parser.add_argument(
        "--config", dest="config_opt", default=None, metavar="PATH",
        help="path to the YAML config (overrides the positional argument)",
    )
    parser.add_argument("--real", action="store_true", help="use real Playwright adapters")
    parser.add_argument("--real-vision", action="store_true", help="use real OCR/template analyzers")
    parser.add_argument("--store", default=None, metavar="PATH", help="persist history to SQLite")
    args = parser.parse_args(argv)

    config_path = args.config_opt or args.config or "config/app.example.yaml"
    sys.exit(
        run_gui(config_path, real=args.real, real_vision=args.real_vision, store_path=args.store)
    )


if __name__ == "__main__":
    main()
