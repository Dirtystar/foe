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
import contextlib
import logging
import os
import sys
from pathlib import Path

from bap.app.composition import create_application
from bap.config.config_loader import load_config
from bap.config.config_models import ApplicationConfig
from bap.core.engine.tab_session import TickReport
from bap.ops.logging_setup import configure_logging, log_event
from bap.ops.lifecycle import IdempotentShutdown, install_signal_handlers
from bap.ops.status import OperationalState, OperationalStatus
from bap.ops.validation import OperationalError, validate_startup

logger = logging.getLogger("bap")


def _error_category(report: TickReport) -> str | None:
    if report.error is not None:
        return type(report.error).__name__
    if report.status.value != "completed":
        return report.status.value
    return None


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
    log_event(
        logger,
        "tick",
        profile_id=report.profile_id,
        tick_id=report.tick_number,
        status=report.status.value,
        actions=len(report.execution.results) if report.execution else 0,
        duration_ms=f"{report.metrics.total_ms:.0f}" if report.metrics else None,
        error_category=_error_category(report),
    )


def _log_health(profile_id: str, health, reason: str) -> None:
    log_event(logger, "health", profile_id=profile_id, health=health.value, reason=reason)


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

    # Operational status: starting -> ready -> (degraded) -> stopping -> stopped.
    # A single on_change fans the transition out to the logs; observe_health is
    # wired into the health callback chain below so it can derive ready<->degraded.
    def _on_status(status: OperationalStatus, reason: str) -> None:
        log_event(logger, "status", status=status.value, reason=reason or None)

    state = OperationalState(on_change=_on_status)

    extra = _playwright_kwargs(config) if real else {}
    if real_vision:
        from bap.adapters.vision.registry import production_analyzer_registry

        extra["analyzer_registry"] = production_analyzer_registry()
        # Offload real (CPU-bound) analyzers off the event loop by default.
        extra["vision_workers"] = vision_workers or 4
    elif vision_workers:
        extra["vision_workers"] = vision_workers

    # Fail fast, before the browser launches: capacity, intervals, resource
    # limits, persistence writability, and (when registries are present) the
    # analyzer/action type names.
    validate_startup(
        config,
        store_path=store_path,
        analyzer_registry=extra.get("analyzer_registry"),
        action_registry=extra.get("action_registry"),
    )

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

    # Insert the operational-state observer at the head of the health chain so
    # it derives ready<->degraded from the same events the sinks already see.
    _downstream_health = health_sink

    def health_sink(profile_id: str, health, reason: str = "") -> None:  # noqa: F811
        state.observe_health(profile_id, health, reason)
        _downstream_health(profile_id, health, reason)

    supervisor = Supervisor(
        monitor=HealthMonitor(), sink=report_sink, on_health=health_sink
    )

    # Optional browser resource monitoring sits at the top of the report chain:
    # resource_monitor -> supervisor -> persistence -> log. Observational; it
    # feeds the supervisor's resource-pressure policy.
    top_sink = supervisor.on_report
    rm_cfg = config.settings.resource_monitoring
    browser_manager = extra.get("browser")
    if rm_cfg.enabled and browser_manager is not None:
        from bap.adapters.browser.playwright_metrics import PlaywrightBrowserMetrics
        from bap.app.resource_monitor import ResourceMonitor

        resource_monitor = ResourceMonitor(
            PlaywrightBrowserMetrics(browser_manager),
            collect_every=rm_cfg.collect_every_ticks,
            max_memory_mb=rm_cfg.limits.max_memory_mb,
            max_pages=rm_cfg.limits.max_pages,
            store=store,
            report_sink=supervisor.on_report,
            on_pressure=supervisor.note_resource_pressure,
        )
        top_sink = resource_monitor.on_report
        logger.info(
            "Resource monitoring enabled (every %d ticks; limits mem=%s pages=%s)",
            rm_cfg.collect_every_ticks, rm_cfg.limits.max_memory_mb, rm_cfg.limits.max_pages,
        )

    app = create_application(config, on_report=top_sink, **extra)
    supervisor.session_manager = app.manager
    profile_ids = tuple(spec.profile_id for spec in app.session_specs)
    logger.info("Starting %d profile(s): %s", len(profile_ids), profile_ids)

    stop_event = asyncio.Event()

    def _request_stop(reason: str) -> None:
        log_event(logger, "shutdown-requested", reason=reason)
        stop_event.set()

    # SIGTERM/SIGINT ask for a graceful stop instead of a hard interrupt. On
    # platforms/threads where signal handlers are unavailable this is a no-op
    # and main()'s KeyboardInterrupt path still applies.
    install_signal_handlers(asyncio.get_running_loop(), _request_stop)

    # A single idempotent routine drives teardown regardless of what triggers
    # it (signal, timed expiry, or exception): idempotent, so overlapping
    # triggers collapse into one clean shutdown.
    async def _teardown() -> None:
        state.transition(OperationalStatus.STOPPING, "shutdown")
        errors = await app.stop()
        if store is not None:
            store.close()
        state.transition(OperationalStatus.STOPPED, "stopped")
        if errors:
            logger.warning("Shutdown completed with %d error(s): %s", len(errors), errors)
        else:
            logger.info("Shutdown complete.")

    shutdown = IdempotentShutdown(_teardown)

    state.transition(OperationalStatus.STARTING, "startup")
    await app.start()
    state.transition(OperationalStatus.READY, "started")
    try:
        if seconds is None:
            await stop_event.wait()  # run until signalled
        else:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    finally:
        await shutdown()


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
    parser.add_argument(
        "--plain-logs", action="store_true",
        help="disable structured key=value fields on log lines",
    )
    args = parser.parse_args()

    configure_logging(args.log_level, structured=not args.plain_logs)
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
    except OperationalError as exc:
        # Startup precondition failed: report the actionable message and exit
        # non-zero without a traceback.
        logger.error("Startup aborted: %s", exc)
        sys.exit(2)
    except KeyboardInterrupt:
        logger.info("Interrupted.")


if __name__ == "__main__":
    main()
