"""The real Windows cursor-move adapter (Milestone 5A) — **move only**.

Implements exactly one operation, ``move_to``, via the Win32 ``SetCursorPos`` API
(cursor position only — it changes no button state and cannot click). There is no
click, press, drag, scroll, or keyboard method here or reachable from here.

Windows-only by construction (that is where the operator runs Chrome). The adapter
is process-DPI-aware so ``SetCursorPos`` takes **physical** screen pixels, which is
exactly what the coordinate contract produces. On any non-Windows platform, or if
Win32 is unavailable, construction raises — the app then reports the cursor preview
as unavailable rather than guessing.

Optionally reports the actual cursor position afterwards (``GetCursorPos``) so the
GUI can show the requested-vs-actual delta for verification.
"""

from __future__ import annotations

import sys


class OsCursorPreviewUnavailable(RuntimeError):
    """Raised when a real cursor move cannot be performed on this platform."""


class WindowsCursorPreview:
    """A `CursorPreviewPort` backed by Win32 ``SetCursorPos`` — movement only."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OsCursorPreviewUnavailable(
                "The real cursor preview is Windows-only (uses SetCursorPos).")
        try:
            import ctypes

            self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - only on Windows without win32
            raise OsCursorPreviewUnavailable(f"Win32 user32 unavailable: {exc}") from exc
        # Per-monitor DPI aware so SetCursorPos coordinates are physical pixels.
        try:  # pragma: no cover - Windows-only
            self._user32.SetProcessDPIAware()
        except Exception:
            pass

    def move_to(self, screen_x: int, screen_y: int) -> None:  # pragma: no cover - Windows-only
        """Move the cursor to a physical screen pixel. Movement only — never clicks."""
        self._user32.SetCursorPos(int(screen_x), int(screen_y))

    def current_position(self) -> tuple[int, int] | None:  # pragma: no cover - Windows-only
        """The actual cursor position now (for requested-vs-actual verification)."""
        import ctypes

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = _POINT()
        if self._user32.GetCursorPos(ctypes.byref(pt)):
            return (int(pt.x), int(pt.y))
        return None


__all__ = ["WindowsCursorPreview", "OsCursorPreviewUnavailable"]
