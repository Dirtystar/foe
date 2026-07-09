"""Application entrypoint.

Deliberately thin: load config, build the application, run it until
interrupted, shut it down. All assembly lives in the composition root and
all behaviour in the runtime layers — this file only sequences them.

Usage:
    python -m bap.main [path/to/app.yaml] [--seconds N]

With no path it looks for config/app.example.yaml. Without real adapters
installed it runs entirely on development stubs, so it is safe to run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from bap.app.composition import create_application
from bap.config.config_loader import load_config
from bap.config.config_models import ApplicationConfig
from bap.core.engine.tab_session import TickReport

logger = logging.getLogger("bap")


def _playwright_kwargs(config: ApplicationConfig) -> dict:
    """Build create_application kwargs backed by real Playwright adapters.

    Imported lazily so stub runs never require Playwright at import time.
    """
    from bap.adapters.actions.playwright_action_handlers import playwright_action_registry
    from bap.adapters.browser.playwright_adapter import PlaywrightBrowserManager
    from bap.adapters.capture.playwright_capture import PlaywrightCaptureAdapter

    settings = config.settings
    browser = PlaywrightBrowserManager(
        headless=settings.headless,
        max_tabs=settings.max_sessions,
        isolate_contexts_per_tab=settings.isolate_contexts_per_tab,
        browser_engine=settings.browser_engine,
        executable_path=os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH"),
    )
    return {
        "browser": browser,
        "capture_port": PlaywrightCaptureAdapter(),
        "action_registry": playwright_action_registry(),
    }


def _log_report(report: TickReport) -> None:
    timing = f" {report.metrics.total_ms:.0f}ms" if report.metrics else ""
    logger.info(
        "tick %s#%d -> %s (%d actions)%s",
        report.profile_id,
        report.tick_number,
        report.status.value,
        len(report.execution.results) if report.execution else 0,
        timing,
    )


def _log_health(profile_id: str, health, reason: str) -> None:
    logger.info("health %s -> %s (%s)", profile_id, health.value, reason)


async def run(
    config_path: Path,
    *,
    seconds: float | None,
    real: bool,
    real_vision: bool,
    store_path: str | None = None,
    vision_workers: int | None = None,
) -> None:
    from bap.app.supervisor import Supervisor
    from bap.core.engine.health import HealthMonitor

    config = load_config(config_path)
    extra = _playwright_kwargs(config) if real else {}
    if real_vision:
        from bap.adapters.vision.registry import production_analyzer_registry

        extra["analyzer_registry"] = production_analyzer_registry()
        # Offload real (CPU-bound) analyzers off the event loop by default.
        extra["vision_workers"] = vision_workers or 4
    elif vision_workers:
        extra["vision_workers"] = vision_workers

    # Optional persistence sits between the supervisor and the log sinks:
    # supervisor -> persistence (stores) -> log. Storage failures are logged,
    # never fatal.
    store = None
    report_sink = _log_report
    health_sink = _log_health
    if store_path:
        from bap.adapters.persistence.sqlite_store import SqliteStateStore
        from bap.app.persistence_sink import PersistenceSink

        store = SqliteStateStore(store_path, on_error=lambda e: logger.warning("store: %s", e))
        persistence = PersistenceSink(
            store,
            report_sink=_log_report,
            health_sink=_log_health,
            on_error=logger.warning,
        )
        report_sink = persistence.on_report
        health_sink = persistence.on_health
        logger.info("Persisting runtime history to %s", store_path)

    supervisor = Supervisor(
        monitor=HealthMonitor(), sink=report_sink, on_health=health_sink
    )
    app = create_application(config, on_report=supervisor.on_report, **extra)
    supervisor.session_manager = app.manager
    profile_ids = tuple(spec.profile_id for spec in app.session_specs)
    logger.info("Starting %d profile(s): %s", len(profile_ids), profile_ids)
    await app.start()
    try:
        if seconds is None:
            await asyncio.Event().wait()  # run until cancelled
        else:
            await asyncio.sleep(seconds)
    finally:
        errors = await app.stop()
        if store is not None:
            store.close()
        if errors:
            logger.warning("Shutdown completed with %d error(s): %s", len(errors), errors)
        else:
            logger.info("Shutdown complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser Automation Platform")
    parser.add_argument(
        "config", nargs="?", default="config/app.example.yaml", help="path to the YAML config"
    )
    parser.add_argument(
        "--seconds", type=float, default=None, help="run for N seconds then stop (default: forever)"
    )
    parser.add_argument(
        "--real", action="store_true", help="use real Playwright adapters instead of stubs"
    )
    parser.add_argument(
        "--real-vision", action="store_true", help="use real OCR/template analyzers instead of stubs"
    )
    parser.add_argument(
        "--store", default=None, metavar="PATH", help="persist runtime history to a SQLite file"
    )
    parser.add_argument(
        "--vision-workers", type=int, default=None, metavar="N",
        help="offload vision analyzers to N worker threads (default 4 with --real-vision)",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(
            run(
                Path(args.config),
                seconds=args.seconds,
                real=args.real,
                real_vision=args.real_vision,
                store_path=args.store,
                vision_workers=args.vision_workers,
            )
        )
    except KeyboardInterrupt:
        logger.info("Interrupted.")


if __name__ == "__main__":
    main()
