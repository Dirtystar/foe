from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")

from bap.app.metrics.models import (
    ActionMetrics,
    BrowserResourceMetrics,
    MetricSummary,
    ProfileMetrics,
    RecentFailure,
    VisionMetrics,
)
from bap.gui.dashboard import DashboardWidget


class FakeRepository:
    """In-memory analytics — no database at all."""

    def __init__(self):
        self.summary = MetricSummary(
            total_ticks=10,
            successful_ticks=8,
            failed_ticks=2,
            avg_duration_ms=42.0,
            p95_duration_ms=90.0,
            recovery_count=3,
        )
        self.profiles = [
            ProfileMetrics(
                profile_id="a",
                ticks=6,
                failures=1,
                action_success_rate=0.5,
                recovery_count=2,
                last_seen=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
                health="degraded",
                ticks_per_min=12.0,
            )
        ]
        self.failures = [
            RecentFailure(
                timestamp=datetime(2026, 7, 8, 12, 0, 30, tzinfo=timezone.utc),
                profile_id="a",
                status="capture_failed",
                reason="page crashed",
            )
        ]

    def overview(self):
        return self.summary

    def per_profile(self):
        return self.profiles

    def vision(self):
        return VisionMetrics()

    def actions(self):
        return ActionMetrics()

    def recent_failures(self, *, limit=20):
        return self.failures

    def browser_resources(self, *, trend=30):
        return getattr(self, "resources_metrics", BrowserResourceMetrics())


@pytest.fixture
def dashboard(qapp):
    repo = FakeRepository()
    widget = DashboardWidget(repo)
    yield widget, repo
    widget.deleteLater()


def test_dashboard_renders_overview_from_repository(dashboard):
    widget, _ = dashboard

    assert widget._overview_values["Total ticks"].text() == "10"  # noqa: SLF001
    assert widget._overview_values["Success"].text() == "80%"  # noqa: SLF001
    assert widget._overview_values["Avg latency"].text() == "42 ms"  # noqa: SLF001
    assert widget._overview_values["Recoveries"].text() == "3"  # noqa: SLF001


def test_dashboard_renders_profile_table(dashboard):
    widget, _ = dashboard

    assert widget.profile_table.rowCount() == 1
    assert widget.profile_table.item(0, 0).text() == "a"
    assert widget.profile_table.item(0, 1).text() == "degraded"
    assert widget.profile_table.item(0, 2).text() == "12.0"
    assert widget.profile_table.item(0, 3).text() == "1"
    assert widget.profile_table.item(0, 4).text() == "50%"


def test_dashboard_renders_recent_failures(dashboard):
    widget, _ = dashboard

    assert widget.failure_table.rowCount() == 1
    assert widget.failure_table.item(0, 1).text() == "a"
    assert widget.failure_table.item(0, 2).text() == "page crashed"


def test_refresh_reflects_updated_repository_values(dashboard):
    widget, repo = dashboard

    repo.summary = MetricSummary(total_ticks=99, successful_ticks=99)
    repo.profiles = []
    repo.failures = []
    widget.refresh()

    assert widget._overview_values["Total ticks"].text() == "99"  # noqa: SLF001
    assert widget._overview_values["Success"].text() == "100%"  # noqa: SLF001
    assert widget.profile_table.rowCount() == 0
    assert widget.failure_table.rowCount() == 0


def test_dashboard_renders_browser_resources_with_warning(qapp):
    from datetime import datetime, timezone

    repo = FakeRepository()
    repo.resources_metrics = BrowserResourceMetrics(
        browser_id="b", memory_mb=5000.0, cpu_percent=40.0, pages=20, contexts=8,
        last_seen=datetime(2026, 7, 8, tzinfo=timezone.utc), samples=5,
        memory_trend=(3000.0, 4000.0, 5000.0),
    )
    widget = DashboardWidget(repo, max_memory_mb=4096, max_pages=16)

    v = widget._resource_values  # noqa: SLF001
    assert v["Memory"].text() == "5000 MB"
    assert v["Pages"].text() == "20"
    assert v["Contexts"].text() == "8"
    assert "↑" in v["Trend"].text()
    assert "⚠" in v["Warning"].text()  # both memory and pages exceed limits
    assert "memory" in v["Warning"].text() and "pages" in v["Warning"].text()
    widget.deleteLater()


def test_dashboard_resources_ok_when_within_limits(qapp):
    repo = FakeRepository()
    repo.resources_metrics = BrowserResourceMetrics(
        browser_id="b", memory_mb=1000.0, pages=4, contexts=2, samples=3
    )
    widget = DashboardWidget(repo, max_memory_mb=4096, max_pages=16)

    assert widget._resource_values["Warning"].text() == "ok"  # noqa: SLF001
    widget.deleteLater()


def test_dashboard_resources_no_data(dashboard):
    widget, _ = dashboard  # default FakeRepository -> empty resources
    assert widget._resource_values["Warning"].text() == "no data"  # noqa: SLF001


def test_dashboard_has_no_database_dependency(dashboard):
    widget, _ = dashboard
    # The widget only holds the injected repository; nothing SQLite-related.
    assert not hasattr(widget, "_conn")
    assert widget._repository.__class__.__name__ == "FakeRepository"  # noqa: SLF001


def test_empty_repository_renders_without_error(qapp):
    class EmptyRepo:
        def overview(self):
            return MetricSummary()

        def per_profile(self):
            return []

        def vision(self):
            return VisionMetrics()

        def actions(self):
            return ActionMetrics()

        def recent_failures(self, *, limit=20):
            return []

        def browser_resources(self, *, trend=30):
            return BrowserResourceMetrics()

    widget = DashboardWidget(EmptyRepo())
    assert widget._overview_values["Total ticks"].text() == "0"  # noqa: SLF001
    assert widget._overview_values["Success"].text() == "0%"  # noqa: SLF001
    widget.deleteLater()
