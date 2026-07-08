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
from pathlib import Path

from bap.app.composition import create_application
from bap.config.config_loader import load_config
from bap.core.engine.tab_session import TickReport

logger = logging.getLogger("bap")


def _log_report(report: TickReport) -> None:
    logger.info(
        "tick %s#%d -> %s (%d actions)",
        report.profile_id,
        report.tick_number,
        report.status.value,
        len(report.execution.results) if report.execution else 0,
    )


async def run(config_path: Path, *, seconds: float | None) -> None:
    config = load_config(config_path)
    app = create_application(config, on_report=_log_report)
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
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(Path(args.config), seconds=args.seconds))
    except KeyboardInterrupt:
        logger.info("Interrupted.")


if __name__ == "__main__":
    main()
