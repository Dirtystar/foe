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
    config, *, real: bool = False, real_vision: bool = False, store_path: str | None = None,
    status_observer=None, forge: bool = False, world_store=None,
):
    """Wire config -> application -> service/bridge -> window. Returns the
    window; the caller owns the Qt lifecycle. `status_observer` (e.g. a crash
    reporter's set_status) receives each operational status as well."""
    bridge = QtReportBridge()

    # Operational status derives ready<->degraded from the health flow (in the
    # ops layer) and is pushed to the GUI as a signal — the window only displays it.
    def _on_status(status, reason):
        bridge.on_status_change(status.value, reason)
        if status_observer is not None:
            status_observer(status.value)

    state = OperationalState(on_change=_on_status)

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
    attended = config.settings.attended
    assignment = None
    save_assignment_path = None
    if attended:
        # Attended mode: a visible browser the user drives; sessions adopt the
        # tab the user assigns (no start_url navigation). Uses real page capture
        # with the built-in demo analyzers/actions so no vision libs are needed.
        import os

        from bap.app.attended import (
            TabAssignment,
            load_assignment,
            make_tab_provider,
            save_assignment,
        )
        from bap.ops.paths import ensure_dirs, get_paths

        paths = ensure_dirs(get_paths())
        # Browser mode (Milestone 4.16): Forge may attach to an operator-launched
        # Chrome over CDP instead of managing its own Chromium. The choice is a
        # persisted operator setting; a missing file defaults to Managed Chromium,
        # so existing installs are unchanged. There is no silent fallback between
        # modes — External Chrome never launches a browser.
        from bap.forge.browser_settings import (
            BrowserMode,
            default_settings_path,
            load_browser_settings,
        )

        browser_settings = load_browser_settings(default_settings_path()) if forge else None
        if forge and browser_settings.mode is BrowserMode.EXTERNAL:
            from bap.adapters.browser.cdp_attach_adapter import CdpAttachBrowserManager

            browser = CdpAttachBrowserManager(endpoint=browser_settings.cdp_endpoint)
        else:
            from bap.adapters.browser.attended_adapter import AttendedBrowserManager

            # Forge shares one persistent Chromium profile across all worlds (they
            # are tabs in the same window); the generic attended mode uses its own.
            profile_dir = "forge-profile" if forge else "attended-profile"
            browser = AttendedBrowserManager(
                user_data_dir=str(paths.data_dir / profile_dir),
                browser_engine=config.settings.browser_engine,
                executable_path=os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH"),
            )
        if forge:
            # Worlds persist (worlds.json); tab assignment does NOT — it is
            # rebuilt each launch by hostname reattachment, so start with an
            # empty runtime assignment and never write it to disk.
            assignment = TabAssignment()
            save_assignment_path = None
        else:
            save_assignment_path = paths.data_dir / "attended-assignment.json"
            assignment = load_assignment(save_assignment_path)
        extra["browser"] = browser
        if forge:
            # Read-only CDP capture: screenshotting a world tab must never
            # foreground it, resize the canvas, or deliver input (P0-1).
            from bap.adapters.capture.forge_capture import ForgeCanvasCaptureAdapter

            extra["capture_port"] = ForgeCanvasCaptureAdapter()
        else:
            from bap.adapters.capture.playwright_capture import PlaywrightCaptureAdapter

            extra["capture_port"] = PlaywrightCaptureAdapter()
        extra["tab_provider"] = make_tab_provider(browser, assignment)
    elif real:
        from bap.main import _playwright_kwargs

        extra.update(_playwright_kwargs(config))
    if real_vision and not attended:
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
    # Skipped in attended mode: the metrics adapter targets the standard
    # PlaywrightBrowserManager, not the attended persistent-context browser.
    top_sink = supervisor.on_report
    rm_cfg = config.settings.resource_monitoring
    browser_manager = extra.get("browser")
    if rm_cfg.enabled and browser_manager is not None and not attended:
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

    # Forge edits its world set live (hot CRUD); the factory must be able to
    # build a session for a world the launch config never had.
    app = create_application(config, on_report=top_sink, dynamic_profiles=forge, **extra)
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

    # Persist the tab assignment (metadata only) on close, then run any store
    # close from above.
    if attended and save_assignment_path is not None:
        from bap.app.attended import save_assignment as _save

        _previous_close = on_close

        def on_close() -> None:  # noqa: F811
            try:
                _save(save_assignment_path, assignment)
            except Exception:  # a failed save must not block shutdown
                pass
            if _previous_close is not None:
                _previous_close()

    # Forge Test Scan: a synchronous read-only capture of a world's tab, used by
    # the observe-only Vision Debugger. Uses the same CDP capture as the runtime.
    capture_callback = None
    if forge:
        _capture_port = extra.get("capture_port")

        def capture_callback(tab_id: str):  # noqa: F811
            return service.capture_world(tab_id, _capture_port).result(timeout=20)

    limits = config.settings.resource_monitoring.limits
    return MainWindow(
        service,
        bridge,
        on_close=on_close,
        metrics_repository=metrics_repository,
        max_memory_mb=limits.max_memory_mb,
        max_pages=limits.max_pages,
        attended=attended,
        assignment=assignment,
        forge=forge,
        world_store=world_store,
        capture_callback=capture_callback,
        browser_settings=browser_settings if forge else None,
    )


def _load_world_store():
    """Load the persistent Forge worlds from the per-user data directory."""
    from bap.forge.worlds import WorldStore
    from bap.ops.paths import ensure_dirs, get_paths

    paths = ensure_dirs(get_paths())
    return WorldStore.load(paths.data_dir / "forge" / "worlds.json")


def run_gui(
    config_path,
    *,
    real: bool = False,
    real_vision: bool = False,
    store_path: str | None = None,
    exec_app: bool = True,
    status_observer=None,
    forge: bool = False,
) -> int:
    """Load config, build the window, and run the Qt loop. Returns an exit code.

    Config problems (ConfigError / OperationalError) are reported and return 2
    without opening a window. `exec_app=False` builds and shows the window but
    returns immediately without entering the Qt event loop — used by tests to
    verify the entry point wires up without blocking.

    In `forge` mode the config is built from the persistent World store
    (worlds.json) rather than loaded from a YAML file — the World Manager owns
    what runs, and a `--forge` launch always uses real attended browser capture.
    """
    from PySide6.QtWidgets import QApplication

    from bap.config.config_loader import ConfigError
    from bap.ops.validation import OperationalError

    logger = logging.getLogger("bap")
    world_store = None
    if forge:
        from bap.forge.config import build_forge_config

        world_store = _load_world_store()
        config = build_forge_config(world_store.list())
    else:
        try:
            config = load_config(Path(config_path))
        except ConfigError as exc:
            logger.error("Configuration error: %s", exc)
            return 2

    qapp = QApplication.instance() or QApplication(sys.argv)
    # Apply the desktop theme (presentation only; safe to call once at startup).
    try:
        from bap.gui.theme import apply_theme

        apply_theme(qapp)
    except Exception:  # never let theming block startup
        logger.debug("theme not applied", exc_info=True)
    try:
        window = build_main_window(
            config, real=real, real_vision=real_vision, store_path=store_path,
            status_observer=status_observer, forge=forge, world_store=world_store,
        )
    except OperationalError as exc:
        logger.error("Startup aborted: %s", exc)
        return 2
    window.resize(1360, 860)
    window.show()
    if not exec_app:
        return 0
    # First launch: a one-time welcome that explains demo vs real mode and
    # offers to install the browser. Only in a real run (never in tests).
    from bap.gui.first_run import maybe_run_first_run

    maybe_run_first_run()
    return int(qapp.exec())


def _resolve_gui_config(explicit: str | None) -> str:
    """Config path for the GUI. The packaged app defaults to the per-user config
    dir (seeding it from a bundled example on first run); source runs default to
    the repo example."""
    if explicit:
        return explicit
    from bap.ops.paths import ensure_user_config, get_paths, is_frozen

    if is_frozen():
        bundled = Path(getattr(sys, "_MEIPASS", ".")) / "config" / "app.example.yaml"
        return str(ensure_user_config(get_paths().config_dir, bundled))
    return "config/app.example.yaml"


def main(argv: list[str] | None = None) -> None:
    from bap import __version__
    from bap.ops.crash import CrashReporter, LogTailHandler, install as install_crash
    from bap.ops.logging_setup import StructuredFormatter, configure_logging
    from bap.ops.paths import ensure_dirs, get_paths, is_frozen

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
    parser.add_argument(
        "--forge", action="store_true",
        help="launch the Forge of Empires World Manager (persistent worlds, real attended browser)",
    )
    args = parser.parse_args(argv)

    # Packaged (windowless) build writes a rotating log file; source runs log to
    # the console only.
    log_file = ensure_dirs(get_paths()).logs_dir / "bap-gui.log" if is_frozen() else None
    configure_logging("INFO", log_file=log_file)

    # Find a browser installed via Tools → Install browser without a manual env var.
    from bap.ops.browser_install import configure_browser_path

    configure_browser_path()

    # A GUI exception can surface through sys.excepthook (outside a caught
    # frame), so install the excepthook variant to still capture a crash bundle.
    tail = LogTailHandler()
    tail.setFormatter(StructuredFormatter())
    reporter = install_crash(
        CrashReporter(version=__version__, crashes_dir=get_paths().crashes_dir, log_tail=tail),
        set_excepthook=True,
    )

    # Forge mode builds its config from the World store, so the YAML path is
    # irrelevant there; pass a harmless default to keep the signature uniform.
    config_path = None if args.forge else _resolve_gui_config(args.config_opt or args.config)
    sys.exit(
        run_gui(
            config_path, real=args.real, real_vision=args.real_vision,
            store_path=args.store, status_observer=reporter.set_status,
            forge=args.forge,
        )
    )


if __name__ == "__main__":
    main()
