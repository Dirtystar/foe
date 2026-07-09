"""Structured logging: fields are appended, plain calls are undisturbed."""

from __future__ import annotations

import io
import logging

from bap.ops.logging_setup import configure_logging, log_event


def _capture(structured: bool = True) -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    configure_logging("INFO", structured=structured, stream=buf)
    return logging.getLogger("test.ops"), buf


def test_log_event_appends_key_value_fields() -> None:
    logger, buf = _capture()
    log_event(logger, "tick", profile_id="p1", tick_id=7, status="completed")
    line = buf.getvalue().strip()
    assert line.endswith("tick profile_id=p1 tick_id=7 status=completed")


def test_log_event_drops_none_valued_fields() -> None:
    logger, buf = _capture()
    log_event(logger, "tick", profile_id="p1", error_category=None, tick_id=3)
    line = buf.getvalue()
    assert "error_category" not in line
    assert "profile_id=p1" in line and "tick_id=3" in line


def test_values_with_spaces_are_quoted() -> None:
    logger, buf = _capture()
    log_event(logger, "health", profile_id="p1", reason="tick failed twice")
    assert 'reason="tick failed twice"' in buf.getvalue()


def test_plain_logging_calls_are_unchanged() -> None:
    logger, buf = _capture()
    logger.info("just a message")
    line = buf.getvalue().strip()
    # No trailing key=value soup when there are no fields.
    assert line.endswith("just a message")


def test_configure_logging_installs_single_handler() -> None:
    configure_logging("INFO")
    configure_logging("DEBUG")  # replaces, does not accumulate
    assert len(logging.getLogger().handlers) == 1


def test_structured_false_omits_fields() -> None:
    logger, buf = _capture(structured=False)
    log_event(logger, "tick", profile_id="p1")
    line = buf.getvalue().strip()
    assert line.endswith("tick")  # fields not rendered by the plain formatter
