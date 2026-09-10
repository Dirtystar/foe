"""Performance dashboard page + nav wiring (Milestone 4.9).

Behaviour-free: the page only reads a metrics registry and paints. We inject a
registry populated with synthetic tick records (no real pipeline) so the test is
fast and deterministic.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from bap.app.attended import TabAssignment
from bap.forge.worlds import World, WorldStore
from bap.gui.main_window import MainWindow
from bap.gui.perf_page import PerformancePage, Sparkline, StageBars
from bap.gui.qt_bridge import QtReportBridge
from bap.perf.registry import MetricsRegistry
from bap.perf.timing import StageTimer


def _populated_registry() -> MetricsRegistry:
    reg = MetricsRegistry()
    for step in range(10):
        for w in ("W1", "W2"):
            t = StageTimer()
            t.record("capture", 0.0)
            t.record("detection", 4.9 + step * 0.01)
            t.record("weakening_ocr", 0.1)
            t.record("classification", 0.06)
            t.total = t.stage_total()
            reg.record_tick(w, t)
    reg.mark_skipped("W1")
    reg.set_world_counts(attached=2, running=2)
    return reg


def test_page_renders_from_registry(qapp):
    page = PerformancePage(registry=_populated_registry())
    page.resize(1100, 800)
    page.refresh()
    assert page._table.rowCount() == 2
    # KPI + bottleneck reflect the injected data (detection dominates).
    assert "detection" in page._bottleneck.text()
    assert page._kpi_fps._value.text() != "—"
    # The slow-ticks table is populated.
    assert page._slow.rowCount() > 0
    page.grab()  # force a paint of the charts, must not raise


def test_charts_paint_without_data(qapp):
    sl = Sparkline(); sl.resize(200, 80); sl.grab()          # empty -> "no data yet"
    sl.set_values([1.0, 2.0, 3.0, 2.5]); sl.grab()
    sb = StageBars(); sb.resize(300, 140); sb.grab()
    sb.set_stages([("detection", 4900.0), ("weakening_ocr", 100.0)]); sb.grab()


def test_world_filter_updates(qapp):
    page = PerformancePage(registry=_populated_registry())
    page.refresh()
    # "All Worlds" plus each World name.
    assert page._world_combo.count() == 3
    page._world_combo.setCurrentIndex(1)   # a specific World -> refresh, no raise
    assert page._selected_world() in ("W1", "W2")


class _Service:
    profile_ids = ()

    def add_world_session(self, spec):
        return None

    def stop_loop(self):
        pass


def test_main_window_has_performance_page(qapp):
    store = WorldStore()
    store.add(World(alias="H", hostname="cz8.forgeofempires.com"))
    win = MainWindow(_Service(), QtReportBridge(), forge=True, world_store=store,
                     assignment=TabAssignment())
    try:
        assert "performance" in win._pages
        win._show_page("performance")           # starts live refresh
        assert hasattr(win, "_perf_page")
        win._show_page("dashboard")             # stops live refresh (no raise)
    finally:
        win.close()
