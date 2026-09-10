"""Environment/identity context for a cursor preview (Milestone 5A).

The Vision Debugger already holds the *target + safety* facts (from its scan). This
context supplies the other half the gate needs — the browser/window identity and
live state — as plain values and small callables, so the GUI can build a
:class:`PreviewRequest` and the whole flow stays Qt-free and testable.

The callables are re-read at confirm time, so a World switched (or a window moved)
while the confirmation dialog is open is detected and blocks the move.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import DEFAULT_MAX_SCAN_AGE_S, PreviewRequest


def _none() -> None:
    return None


@dataclass
class CursorPreviewContext:
    """Scan-time identity + live getters used to build a PreviewRequest."""

    world_alias: str | None
    hostname: str | None
    browser_mode: str | None
    tab_id_at_scan: str | None
    live: bool
    captured_at: datetime | None
    capture_w: int
    capture_h: int
    geometry_at_scan: WindowGeometry | None = None
    max_age_s: float = DEFAULT_MAX_SCAN_AGE_S

    # Live getters (re-read at button/confirm time). Defaults are safe: no window,
    # no current geometry, unchanged selection.
    selected_alias_getter: Callable[[], str | None] = _none
    current_tab_getter: Callable[[], str | None] = _none
    current_geometry_getter: Callable[[], WindowGeometry | None] = _none
    window_owned_getter: Callable[[], bool] = staticmethod(lambda: False)

    # Optional post-move verification hooks.
    after_move_capture: Callable[[], object] | None = None
    cursor_position_getter: Callable[[], tuple[int, int] | None] | None = None

    # M5A.1 — "Set Browser Content Origin". Runs the operator calibration and
    # returns True on success; None when calibration is not offered here.
    calibrate_content_origin: Callable[[], bool] | None = None
    # A short human note about why geometry is unavailable (e.g. "content origin not
    # calibrated"), shown alongside a blocked preview.
    geometry_status_getter: Callable[[], str | None] = _none

    def build_request(
        self, *, enabled: bool, target_point, pct, confidence, weakening_value,
        world_limit, decision,
    ) -> PreviewRequest:
        """Assemble a PreviewRequest by combining these environment facts with the
        target/safety facts the caller pulled from the scan. Live getters are read
        NOW, so drift since the scan is captured in the request."""
        return PreviewRequest(
            enabled=enabled,
            live=self.live,
            browser_mode=self.browser_mode,
            window_owned=bool(self.window_owned_getter()),
            world_alias=self.world_alias,
            hostname=self.hostname,
            selected_alias=self.selected_alias_getter(),
            tab_id_at_scan=self.tab_id_at_scan,
            current_tab_id=self.current_tab_getter(),
            target_point=target_point,
            pct=pct,
            confidence=confidence,
            weakening_value=weakening_value,
            world_limit=world_limit,
            decision=decision,
            capture_w=self.capture_w,
            capture_h=self.capture_h,
            captured_at=self.captured_at,
            geometry_at_scan=self.geometry_at_scan,
            current_geometry=self.current_geometry_getter(),
            max_age_s=self.max_age_s,
        )


__all__ = ["CursorPreviewContext"]
