"""Unified `bap` command-line front door.

Dispatches to three subcommands — `run`, `gui`, and `validate-config` — reusing
the exact argument set and execution paths of the standalone `bap-run` /
`bap-gui` entry points, so behaviour is identical however it is invoked. This
module adds no runtime behaviour; it only wires argument parsing to the
existing composition roots.

Entry points (see pyproject `[project.scripts]`):
    bap              -> cli:main       (this dispatcher)
    bap-run          -> bap.main:main  (== `bap run`)
    bap-gui          -> bap.gui.gui_main:main (== `bap gui`)
"""

from __future__ import annotations

import argparse
import logging

from bap import __version__
from bap.config.config_loader import ConfigError
from bap.main import add_run_arguments, execute_run, resolve_config_path, validate_config
from bap.ops.logging_setup import configure_logging
from bap.ops.validation import OperationalError

logger = logging.getLogger("bap")


def _execute_validate(args: argparse.Namespace) -> int:
    """`bap validate-config <file>`: load + startup validation, no browser.

    Exit 0 when the config is valid, 2 when it is not. Never launches a browser
    and never writes persistence.
    """
    configure_logging(args.log_level, json_format=(args.log_format == "json"))
    config_path = resolve_config_path(args)
    try:
        config = validate_config(
            config_path,
            real=args.real,
            real_vision=args.real_vision,
            store_path=args.store,
        )
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 2
    except OperationalError as exc:
        logger.error("Invalid configuration: %s", exc)
        return 2
    logger.info(
        "OK: '%s' is valid — %d profile(s), %d rule pack(s).",
        config_path, len(config.profiles), len(config.rule_packs),
    )
    return 0


def _execute_gui(args: argparse.Namespace) -> int:
    from bap.gui.gui_main import run_gui

    return run_gui(
        resolve_config_path(args),
        real=args.real,
        real_vision=args.real_vision,
        store_path=args.store,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bap", description="Browser Automation Platform"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run the automation runtime (headless)")
    add_run_arguments(run_parser)
    run_parser.set_defaults(_handler=execute_run)

    validate_parser = sub.add_parser(
        "validate-config", help="validate a config file and exit (no browser)"
    )
    validate_parser.add_argument("config", nargs="?", default=None, help="path to the YAML config")
    validate_parser.add_argument(
        "--config", dest="config_opt", default=None, metavar="PATH",
        help="path to the YAML config (overrides the positional argument)",
    )
    validate_parser.add_argument(
        "--real", action="store_true",
        help="validate action types against the real Playwright handlers and installed plugins",
    )
    validate_parser.add_argument(
        "--real-vision", action="store_true",
        help="validate analyzer types against the real analyzers and installed plugins",
    )
    validate_parser.add_argument(
        "--store", default=None, metavar="PATH",
        help="also check that this persistence path is writable",
    )
    validate_parser.add_argument("--log-level", default="INFO")
    validate_parser.add_argument("--log-format", choices=["plain", "json"], default="plain")
    validate_parser.set_defaults(_handler=_execute_validate)

    gui_parser = sub.add_parser("gui", help="launch the PySide6 monitoring GUI")
    gui_parser.add_argument("config", nargs="?", default=None, help="path to the YAML config")
    gui_parser.add_argument(
        "--config", dest="config_opt", default=None, metavar="PATH",
        help="path to the YAML config (overrides the positional argument)",
    )
    gui_parser.add_argument("--real", action="store_true", help="use real Playwright adapters")
    gui_parser.add_argument(
        "--real-vision", action="store_true", help="use real OCR/template analyzers"
    )
    gui_parser.add_argument("--store", default=None, metavar="PATH", help="persist history to SQLite")
    gui_parser.set_defaults(_handler=_execute_gui)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args._handler(args))


if __name__ == "__main__":
    main()
