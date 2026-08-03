"""Vision Validation GUI page + nav wiring (Milestone 4.11).

Behaviour-free: the page renders a report and runs the (existing) pipeline in a
worker. Here we inject providers and drive the render path with a hand-built
report so the test is fast and deterministic (no real detector), plus assert the
page is wired into the Forge nav-shell.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from bap.app.attended import TabAssignment
from bap.core.domain.models import Rect
from bap.forge.worlds import World, WorldStore
from bap.forge.detection.geometry import ScanRois
from bap.forge.detection.validation import validate_vision
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge
from bap.gui.vision_validation import VisionValidationPage
import numpy as np


class _FakeDetector:
    _offset = (16, 0)

    def scan(self, image, region=None):
        from types import SimpleNamespace

        return SimpleNamespace(detections=[], candidates=[])

    def score_at(self, image, x, y):
        return 0.0


def _report():
    img = np.zeros((140, 200, 3), dtype=np.uint8)
    rois = ScanRois(battle_map=Rect(0, 8, 200, 132), weakening=Rect(10, 2, 40, 18),
                    weakening_calibrated=True)
    return validate_vision(img, world_alias="H", detector=_FakeDetector(), rois=rois)


def test_page_renders_report(qapp):
    page = VisionValidationPage(world_aliases=lambda: ["H", "F"])
    page.refresh_worlds()
    assert page._world_combo.count() == 2
    page.render_report(_report())
    # One card per section.
    assert page._results.count() == 7
    assert page._last_report is not None
    assert page._export_btn.isEnabled() is False  # enable happens via _on_done
    page.grab()  # force a paint, must not raise


def test_page_export_writes_markdown(qapp, tmp_path, monkeypatch):
    page = VisionValidationPage(world_aliases=lambda: ["H"])
    rep = _report()
    page._last_report = rep
    out = tmp_path / "VISION_VALIDATION_REPORT.md"
    monkeypatch.setattr("bap.gui.vision_validation.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(out), "Markdown (*.md)"))
    page._export()
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Vision Validation" in text and "Weakening" in text


class _Service:
    profile_ids = ()

    def add_world_session(self, spec):
        return None

    def stop_loop(self):
        pass


def test_snapshot_button_enables_after_run(qapp):
    page = VisionValidationPage(world_aliases=lambda: ["H"])
    assert page._snapshot_btn.isEnabled() is False
    import numpy as np

    page._last_image = np.zeros((90, 120, 3), dtype=np.uint8)
    page._last_alias = "H"
    page._on_done(_report(), None)
    # Report carries the scan and an image is retained -> Save Snapshot enabled.
    assert page._snapshot_btn.isEnabled() is True


def test_debugger_has_snapshot_button():
    # The Vision Debugger (Test Scan) exposes a Save Snapshot control + handler.
    import bap.gui.forge_debugger as fd

    assert hasattr(fd.DebuggerWindow, "_on_save_snapshot")


def test_main_window_has_validation_page(qapp):
    store = WorldStore()
    store.add(World(alias="H", hostname="cz8.forgeofempires.com"))
    win = MainWindow(_Service(), QtReportBridge(), forge=True, world_store=store,
                     assignment=TabAssignment())
    try:
        assert "validation" in win._pages
        win._show_page("validation")
        assert hasattr(win, "_validation_page")
        # World list is refreshed from the store on show.
        combo = win._validation_page._world_combo
        assert [combo.itemData(i) for i in range(combo.count())] == ["H"]
        win._show_page("dashboard")
    finally:
        win.close()
