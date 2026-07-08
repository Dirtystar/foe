"""Pure presentation-mapping tests — no Qt required."""

from bap.core.engine.tab_session import TickStatus
from bap.core.vision.pipeline import AnalyzerFailure, VisionResult
from bap.gui.report_view import log_line, row_for

from _reports import make_report


def test_completed_report_summarizes_rules_and_actions():
    report = make_report(
        profile_id="p1", tick=5, matched=1, rules_total=3, actions_ok=2, actions_total=2
    )

    row = row_for(report)

    assert row.profile_id == "p1"
    assert row.status == "completed"
    assert row.last_tick == "5"
    assert row.rules == "1/3 matched"
    assert row.actions == "2/2 ok"
    assert row.error == ""


def test_capture_failed_report_shows_error_and_dashes():
    report = make_report(status=TickStatus.CAPTURE_FAILED, error=RuntimeError("page crashed"))

    row = row_for(report)

    assert row.status == "capture_failed"
    assert row.rules == "-"
    assert row.actions == "-"
    assert "page crashed" in row.error


def test_vision_failure_is_summarized():
    vision = VisionResult(
        observations=(), failures=(AnalyzerFailure(analyzer="ocr", error=ValueError("x")),)
    )
    report = make_report(status=TickStatus.VISION_FAILED, vision=vision)

    assert "vision failed: ocr" in row_for(report).error


def test_action_failures_are_counted():
    report = make_report(actions_ok=1, actions_total=2)

    assert "1 action failure" in row_for(report).error


def test_log_line_includes_profile_tick_and_summaries():
    report = make_report(profile_id="tab3", tick=7, matched=0, rules_total=1)

    line = log_line(report)

    assert "[tab3]" in line
    assert "tick #7" in line
    assert "rules 0/1 matched" in line
