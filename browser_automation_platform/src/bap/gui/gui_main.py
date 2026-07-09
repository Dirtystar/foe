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
import sys
from pathlib import Path

from bap.app.composition import create_application
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config
from bap.core.engine.health import HealthMonitor
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge
from bap.gui.runtime_service import RuntimeService


def build_main_window(
    config, *, real: bool = False, real_vision: bool = False, store_path: str | None = None
):
    """Wire config -> application -> service/bridge -> window. Returns the
    window; the caller owns the Qt lifecycle."""
    bridge = QtReportBridge()

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

    app = create_application(config, on_report=supervisor.on_report, **extra)
    supervisor.session_manager = app.manager  # late-bind now that the manager exists
    service = RuntimeService(app)
    service.on_state_change = bridge.on_state_change
    service.on_error = bridge.on_error
    service.start_loop()

    return MainWindow(
        service, bridge, on_close=on_close, metrics_repository=metrics_repository
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser Automation Platform — GUI monitor")
    parser.add_argument("config", nargs="?", default="config/app.example.yaml")
    parser.add_argument("--real", action="store_true", help="use real Playwright adapters")
    parser.add_argument("--real-vision", action="store_true", help="use real OCR/template analyzers")
    parser.add_argument("--store", default=None, metavar="PATH", help="persist history to SQLite")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    qapp = QApplication(sys.argv)
    config = load_config(Path(args.config))
    window = build_main_window(
        config, real=args.real, real_vision=args.real_vision, store_path=args.store
    )
    window.resize(900, 600)
    window.show()
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
