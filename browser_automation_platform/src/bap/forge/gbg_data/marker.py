"""Read a province's on-screen point from FoE Helper's sector-marker arrow.

The GBG map is a canvas, so a province has no DOM node of its own. But FoE Helper's "Mark
sector on the map" draws a ``.building-marker-arrow`` whose CSS ``transform: translate(Xpx,
Ypx)`` is the sector's exact screen anchor — the point the arrow tips at. Marking a province
(by its id = the row's ``data-id``) and reading that translate gives us the click target with
no calibration and no map→screen transform. This module is the pure parser; the live driver
in ``action/locate.py`` does the marking/clicking.

Keeping the (flag, screen) pairs this yields also lets us fit the native transform later and
drop the FoE Helper dependency (see ``gbg_data/calibration.py``).
"""

from __future__ import annotations

import re

_TRANSLATE = re.compile(r"translate\(\s*(-?[0-9.]+)px\s*,\s*(-?[0-9.]+)px\s*\)")


def parse_marker_xy(transform: str | None) -> tuple | None:
    """Screen (x, y) from a ``transform: translate(Xpx, Ypx) …`` string, or None.

    Tolerates extra transforms (``scale(1)`` etc.) and missing/blank input."""
    if not transform:
        return None
    m = _TRANSLATE.search(transform)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)))


__all__ = ["parse_marker_xy"]
