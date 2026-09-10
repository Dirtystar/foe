"""Robust map navigation state — reach any province on a scrolling map.

The GBG map is larger than the viewport and does **not** re-centre when you open a province,
but it can be dragged (panned). So a single global transform is impossible; instead we track
a running **offset** ourselves:

    screen = scale * flag + offset

- ``scale`` is fixed (the bitmap zoom) and estimated once from two known anchors.
- ``offset`` changes only when **we** drag the map — and we know by how much — so we keep it
  current with :meth:`apply_drag`.
- Every province we open gives ground truth (``provinceId`` → its map flag at the click
  point), so :meth:`learn_offset` self-corrects any drift. Clicking near a just-learned
  anchor is therefore reliable even if ``scale`` is slightly off.

Pure geometry — no browser. The live driver in ``action/navigate.py`` uses this.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def estimate_scale(a_screen, a_flag, b_screen, b_flag) -> float | None:
    """Uniform scale from two (screen, flag) anchors = screen distance / flag distance."""
    fd = math.hypot(b_flag[0] - a_flag[0], b_flag[1] - a_flag[1])
    if fd == 0:
        return None
    sd = math.hypot(b_screen[0] - a_screen[0], b_screen[1] - a_screen[1])
    return sd / fd


@dataclass
class MapNavigator:
    scale: float
    off_x: float = 0.0
    off_y: float = 0.0

    def screen_for(self, flag) -> tuple:
        """Where a province flag currently is on screen."""
        return (self.scale * flag[0] + self.off_x, self.scale * flag[1] + self.off_y)

    def learn_offset(self, screen, flag) -> None:
        """Ground truth: we saw ``flag`` open at ``screen`` — set offset so it's exact."""
        self.off_x = screen[0] - self.scale * flag[0]
        self.off_y = screen[1] - self.scale * flag[1]

    def apply_drag(self, dx, dy) -> None:
        """We dragged the map by (dx, dy); content (and every flag) shifts by the same."""
        self.off_x += dx
        self.off_y += dy

    def on_screen(self, screen, vw, vh, margin: float = 60) -> bool:
        return (margin <= screen[0] <= vw - margin
                and margin <= screen[1] <= vh - margin)

    def drag_to_center(self, flag, vw, vh) -> tuple:
        """Drag vector that would bring ``flag`` to the viewport centre (clamped so we don't
        over-drag past the map — the caller may need several drags for far targets)."""
        cx, cy = self.screen_for(flag)
        return (vw / 2 - cx, vh / 2 - cy)


__all__ = ["MapNavigator", "estimate_scale"]
