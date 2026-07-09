"""Structured operational logging.

`log_event(logger, "tick", profile_id=..., tick_id=...)` emits a stable event
name plus key=value correlation fields, appended by a formatter. Ordinary
`logger.info("...")` calls keep working unchanged (no fields -> nothing
appended), so existing consumers are undisturbed. Correlation fields used
across the ops layer: profile_id, tick_id, recovery_attempt, plugin,
action_type, error_category, status.

Two operator-facing formats: `plain` (human-readable `... message key=value`,
the default) and `json` (one JSON object per line for log shippers). Both read
the same `event_fields` extra, so `log_event` calls render identically in
either format.
"""

from __future__ import annotations

import json
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


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, event (the message), and
    every correlation field flattened as top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, _FIELDS_KEY, None)
        if fields:
            for key, value in fields.items():
                payload.setdefault(key, value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO", *, structured: bool = True, json_format: bool = False, stream=None
) -> None:
    """Install a single root handler. Idempotent-friendly: replaces handlers.

    `json_format=True` emits JSON lines; otherwise `structured` chooses between
    the key=value formatter (default) and a plain message-only formatter.
    """
    handler = logging.StreamHandler(stream)
    if json_format:
        formatter: logging.Formatter = JsonFormatter()
    elif structured:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Log a structured event: `event` is the message, `fields` become
    appended key=value pairs (None-valued fields are dropped)."""
    clean = {k: v for k, v in fields.items() if v is not None}
    logger.log(level, event, extra={_FIELDS_KEY: clean})


__all__ = ["JsonFormatter", "StructuredFormatter", "configure_logging", "log_event"]
