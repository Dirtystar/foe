"""M6A.1 GUI wiring (offscreen): the Vision Debugger shows an Open & Verify section
that is unavailable/disabled by default and never exposes an auto-battle control."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _img():
    return np.full((1080, 1920, 3), 40, np.uint8)


def test_section_unavailable_without_controller(qapp):
    from bap.gui.forge_debugger import DebuggerWindow

    w = DebuggerWindow(_img(), source="t", open_verify_controller=None)
    assert hasattr(w, "open_verify_button")
    assert not w.open_verify_button.isEnabled()          # cannot click by default
    assert "UNAVAILABLE" in w.click_state_label.text()


def test_enable_then_button_becomes_available(qapp):
    from bap.forge.click.open_verify import OpenAndVerifyController
    from bap.forge.click.panel_reader import PanelReading
    from bap.gui.forge_debugger import DebuggerWindow

    class _Reader:
        def read(self, img):
            return PanelReading(True, 20, 0.9, "blue", "x", (1469, 773))

    class _FakeClick:
        def __init__(self):
            self.clicks = []

        def click_at(self, x, y):
            self.clicks.append((x, y))

    class _FakeCursor:
        def move_to(self, x, y):
            pass

    ctl = OpenAndVerifyController(
        _FakeCursor(), _FakeClick(), _Reader(),
        __import__("bap.forge.click.audit", fromlist=["ClickAudit"]).ClickAudit("/tmp/ov_ui.jsonl"),
        capture_fn=lambda: None, panel_present_fn=lambda i: False)
    w = DebuggerWindow(_img(), source="t", open_verify_controller=ctl)
    # disabled until enabled for the session
    assert not w.open_verify_button.isEnabled()
    assert not w.open_observe_button.isEnabled()
    w._on_enable_clicking()
    assert w.open_verify_button.isEnabled()
    assert w.open_observe_button.isEnabled()      # Open Province & Observe too
    assert "ENABLED" in w.click_state_label.text()


def test_no_auto_battle_control_exists(qapp):
    from bap.gui.forge_debugger import DebuggerWindow

    w = DebuggerWindow(_img(), source="t", open_verify_controller=None)
    text = " ".join(getattr(b, "text", lambda: "")() for b in w.findChildren(type(w.open_verify_button)))
    for banned in ("start battle", "auto", "fight", "loop", "run battle",
                   "next battle", "attack", "repeat"):
        assert banned not in text.lower()
