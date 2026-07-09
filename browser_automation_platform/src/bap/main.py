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

from bap import __version__
from bap.app.composition import create_application
from bap.config.config_loader import ConfigError, load_config
from bap.config.config_models import ApplicationConfig
from bap.core.engine.tab_session import TickReport
from bap.ops.logging_setup import configure_logging, log_event
from bap.ops.lifecycle import IdempotentShutdown, install_signal_handlers
from bap.ops.status import OperationalState, OperationalStatus
from bap.ops.validation import OperationalError, validate_startup

_DEFAULT_CONFIG = "config/app.example.yaml"

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
    dry_run: bool = False,
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
    # A dry run validates the persistence *path* (above) but opens no store, so
    # it makes zero writes.
    store = None
    report_sink = _log_report
    health_sink = _log_health
    if store_path and not dry_run:
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

    # create_application resolves every analyzer/action type (including plugins
    # when real registries are supplied), builds the rules/bindings/handlers,
    # and type-checks them — all without launching a browser. A dry run stops
    # exactly here: everything is validated, nothing is started.
    app = create_application(config, on_report=top_sink, **extra)
    supervisor.session_manager = app.manager
    profile_ids = tuple(spec.profile_id for spec in app.session_specs)

    if dry_run:
        await app.stop()  # releases any vision executor; no sessions/tabs, no writes
        log_event(
            logger, "dry-run-ok",
            profiles=len(profile_ids),
            analyzers="real" if real_vision else "stub",
            actions="real" if real else "stub",
            store=store_path,
        )
        logger.info(
            "Dry run OK: configuration valid, %d profile(s) resolved, no browser launched.",
            len(profile_ids),
        )
        return

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


def _registries_for(real: bool, real_vision: bool):
    """Resolve the analyzer/action registries a run would use for these flags.

    Real flags select the production registries (which discover installed
    plugins via entry points); otherwise the built-in dev registries. Used by
    both the runtime and the standalone config validation so a `validate-config`
    or `--dry-run` checks exactly what a real run would.
    """
    from bap.app.stubs import default_action_registry, default_analyzer_registry

    if real:
        from bap.adapters.actions.playwright_action_handlers import playwright_action_registry

        actions = playwright_action_registry()
    else:
        actions = default_action_registry()

    if real_vision:
        from bap.adapters.vision.registry import production_analyzer_registry

        analyzers = production_analyzer_registry()
    else:
        analyzers = default_analyzer_registry()
    return analyzers, actions


def validate_config(
    config_path: Path,
    *,
    real: bool = False,
    real_vision: bool = False,
    store_path: str | None = None,
) -> ApplicationConfig:
    """Load and fully validate a config without launching anything.

    Raises ConfigError (parse/schema) or OperationalError (operational
    preconditions, including unknown analyzer/action types and unwritable
    persistence path). Opens no browser and makes no persistence writes.
    """
    config = load_config(config_path)
    analyzers, actions = _registries_for(real, real_vision)
    validate_startup(
        config, store_path=store_path, analyzer_registry=analyzers, action_registry=actions
    )
    return config


def resolve_config_path(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "config_opt", None) or args.config or _DEFAULT_CONFIG)


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the flags shared by `bap-run` and `bap run`."""
    parser.add_argument(
        "config", nargs="?", default=None,
        help=f"path to the YAML config (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--config", dest="config_opt", default=None, metavar="PATH",
        help="path to the YAML config (overrides the positional argument)",
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
    parser.add_argument("--log-level", default="INFO", help="logging level (default: INFO)")
    parser.add_argument(
        "--log-format", choices=["plain", "json"], default="plain",
        help="log output format: human-readable key=value (plain) or JSON lines (json)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="validate config, resolve plugins and action/analyzer types, then exit "
        "without launching a browser or writing persistence",
    )


def execute_run(args: argparse.Namespace) -> int:
    """Configure logging and run (or dry-run). Returns a process exit code."""
    configure_logging(args.log_level, json_format=(args.log_format == "json"))
    config_path = resolve_config_path(args)
    try:
        asyncio.run(
            run(
                config_path,
                seconds=args.seconds,
                real=args.real,
                real_vision=args.real_vision,
                store_path=args.store,
                vision_workers=args.vision_workers,
                dry_run=args.dry_run,
            )
        )
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 2
    except OperationalError as exc:
        # Startup precondition failed: report the actionable message and exit
        # non-zero without a traceback.
        logger.error("Startup aborted: %s", exc)
        return 2
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bap-run", description="Browser Automation Platform — headless runner"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    add_run_arguments(parser)
    args = parser.parse_args(argv)
    sys.exit(execute_run(args))


if __name__ == "__main__":
    main()
