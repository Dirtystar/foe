"""Structured operational logging.

`log_event(logger, "tick", profile_id=..., tick_id=...)` emits a stable event
name plus key=value correlation fields, appended by a formatter. Ordinary
`logger.info("...")` calls keep working unchanged (no fields -> nothing
appended), so existing consumers are undisturbed. Correlation fields used
across the ops layer: profile_id, tick_id, recovery_attempt, plugin,
action_type, error_category, status.
"""

from __future__ import annotations

import logging
from typing import Any

_FIELDS_KEY = "event_fields"


class StructuredFormatter(logging.Formatter):
    """Appends `key=value` correlation fields (if any) to the message line."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, _FIELDS_KEY, None)
        if fields:
            base += " " + " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        return base


def _fmt(value: Any) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text


def configure_logging(level: str = "INFO", *, structured: bool = True, stream=None) -> None:
    """Install a single root handler. Idempotent-friendly: replaces handlers."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        StructuredFormatter()
        if structured
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Log a structured event: `event` is the message, `fields` become
    appended key=value pairs (None-valued fields are dropped)."""
    clean = {k: v for k, v in fields.items() if v is not None}
    logger.log(level, event, extra={_FIELDS_KEY: clean})


__all__ = ["StructuredFormatter", "configure_logging", "log_event"]
