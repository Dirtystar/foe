"""The real Windows single-left-click adapter (Milestone 6A.1) — **one click only**.

Implements exactly one operation, ``click_at``, via the Win32 ``SendInput`` API: an
absolute cursor move to the target physical pixel, then a single left-button
down/up at that point. There is **no** double-click, right/middle click, drag,
scroll, hold, or keyboard method here or reachable from here.

Windows-only by construction (that is where the operator runs Chrome). The adapter
is process-DPI-aware — the same awareness the cursor-move adapter sets — so the
absolute coordinates it sends are **physical** screen pixels, matching the
coordinate contract (`image_to_screen`). On any non-Windows platform, or if Win32 is
unavailable, construction raises and the app reports clicking as unavailable rather
than guessing.
"""

from __future__ import annotations

import sys


class OsClickUnavailable(RuntimeError):
    """Raised when a real click cannot be performed on this platform."""


# Win32 SendInput constants.
_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_ABS = 65535  # SendInput absolute coordinates are normalised to 0..65535


class WindowsSingleClick:
    """A `ClickPort` backed by Win32 ``SendInput`` — a single left click only."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OsClickUnavailable(
                "The real click adapter is Windows-only (uses SendInput).")
        try:
            import ctypes

            self._ctypes = ctypes
            self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - only on Windows without win32
            raise OsClickUnavailable(f"Win32 user32 unavailable: {exc}") from exc
        # Match the cursor adapter's DPI awareness so coordinates are physical px.
        try:  # pragma: no cover - Windows-only
            self._user32.SetProcessDPIAware()
        except Exception:
            pass

    def click_at(self, screen_x: int, screen_y: int) -> None:  # pragma: no cover - Windows-only
        """One left click at a physical screen pixel: move (absolute) → down → up.
        No double-click, no drag, no hold."""
        ctypes = self._ctypes

        class _MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("mi", _MOUSEINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

        vscreen_w = self._user32.GetSystemMetrics(78) or 1   # SM_CXVIRTUALSCREEN
        vscreen_h = self._user32.GetSystemMetrics(79) or 1   # SM_CYVIRTUALSCREEN
        vscreen_x = self._user32.GetSystemMetrics(76)        # SM_XVIRTUALSCREEN
        vscreen_y = self._user32.GetSystemMetrics(77)        # SM_YVIRTUALSCREEN
        nx = int((int(screen_x) - vscreen_x) * _ABS / vscreen_w)
        ny = int((int(screen_y) - vscreen_y) * _ABS / vscreen_h)

        def _send(flags: int) -> None:
            inp = _INPUT(type=_INPUT_MOUSE)
            inp.mi = _MOUSEINPUT(dx=nx, dy=ny, mouseData=0, dwFlags=flags, time=0,
                                 dwExtraInfo=None)
            self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

        _send(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE)
        _send(_MOUSEEVENTF_LEFTDOWN)
        _send(_MOUSEEVENTF_LEFTUP)

    def current_position(self) -> tuple[int, int] | None:  # pragma: no cover - Windows-only
        """Actual cursor position now (for requested-vs-actual verification)."""
        ctypes = self._ctypes

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = _POINT()
        if self._user32.GetCursorPos(ctypes.byref(pt)):
            return (int(pt.x), int(pt.y))
        return None


__all__ = ["WindowsSingleClick", "OsClickUnavailable"]
