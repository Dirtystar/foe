"""M6A.1: the click boundary is structurally single-click-only, and the cursor
port never gains a click method."""

from __future__ import annotations

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.adapters.input.fake_click import FakeClick
from bap.forge.click.port import FORBIDDEN_INPUT_METHODS, ClickPort
from bap.forge.cursor.port import CursorPreviewPort


def test_fake_click_is_a_clickport_with_only_click_at():
    fc = FakeClick()
    assert isinstance(fc, ClickPort)
    assert hasattr(fc, "click_at")
    for m in FORBIDDEN_INPUT_METHODS:
        assert not hasattr(fc, m), f"click adapter must not expose {m}"


def test_cursor_port_stays_movement_only():
    cur = FakeCursorPreview()
    assert isinstance(cur, CursorPreviewPort)
    assert hasattr(cur, "move_to")
    # The cursor port must NOT gain a click method (that lives on ClickPort only).
    assert not hasattr(cur, "click_at")


def test_windows_click_adapter_exposes_no_forbidden_methods():
    # Constructed off-Windows it raises; assert the class surface anyway.
    from bap.adapters.input.os_click import WindowsSingleClick

    for m in FORBIDDEN_INPUT_METHODS:
        assert not hasattr(WindowsSingleClick, m)
    assert hasattr(WindowsSingleClick, "click_at")
