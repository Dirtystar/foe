"""Cursor adapters (Milestone 5A): the fake records moves; neither adapter exposes
any click/keyboard API; the real Windows adapter is unavailable off Windows.
"""

from __future__ import annotations

import sys

import pytest

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.adapters.cursor.os_cursor import OsCursorPreviewUnavailable, WindowsCursorPreview
from bap.forge.cursor.port import FORBIDDEN_INPUT_METHODS, CursorPreviewPort


def test_fake_records_moves_and_is_a_cursor_preview_port():
    c = FakeCursorPreview()
    assert isinstance(c, CursorPreviewPort)      # satisfies the move_to protocol
    c.move_to(10, 20)
    c.move_to(-30, 40)
    assert c.moves == [(10, 20), (-30, 40)]
    assert c.move_count == 2 and c.last == (-30, 40)


def test_fake_has_no_click_or_keyboard_method():
    c = FakeCursorPreview()
    present = [m for m in FORBIDDEN_INPUT_METHODS if hasattr(c, m)]
    assert present == [], f"fake cursor must expose no input methods, found {present}"
    # The only public callable is move_to.
    public = [a for a in dir(c) if not a.startswith("_") and callable(getattr(c, a))]
    assert public == ["move_to"]


def test_windows_adapter_class_exposes_only_move_and_position():
    # Even without instantiating, the class must not define click/keyboard methods.
    present = [m for m in FORBIDDEN_INPUT_METHODS if hasattr(WindowsCursorPreview, m)]
    assert present == []


@pytest.mark.skipif(sys.platform == "win32", reason="off-Windows behaviour")
def test_windows_adapter_unavailable_off_windows():
    with pytest.raises(OsCursorPreviewUnavailable):
        WindowsCursorPreview()
