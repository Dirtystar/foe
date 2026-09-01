"""Map calibration — turn two "clicked a province → the game told us which one" samples
into a persisted map→screen transform, so the app can place *any* province afterwards.

The clever bit (so a user never has to identify province ids): you click any two provinces;
opening each fires a `/game/json` request carrying its `provinceId`
(`parse_province_id_from_game_json`). Pair that id's known map-flag position
(`MapLayout.flag`) with the click's screen point → one calibration sample. Two samples
(provinces apart in x and y) solve the axis-aligned transform.

Persistence keeps the transform per world + map id, so it survives restarts and is only
redone when the map (or the map view) changes. Pure logic + a tiny JSON store; no browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bap.forge.gbg_data.map_layout import MapLayout, MapTransform


@dataclass(frozen=True)
class CalibrationSample:
    province_id: int
    screen: tuple      # (x, y) viewport CSS px where the user clicked


def solve_transform(layout: MapLayout, a: CalibrationSample,
                    b: CalibrationSample) -> MapTransform:
    """Solve the map→screen transform from two province clicks. Each province's map point is
    its flag from ``layout``; the screen point is where the user clicked. Raises if a
    province has no flag or the two are not apart on both axes."""
    fa, fb = layout.flag(a.province_id), layout.flag(b.province_id)
    if fa is None or fb is None:
        raise ValueError("a calibration province has no flag in the map layout")
    return MapTransform.from_two_points(fa, tuple(a.screen), fb, tuple(b.screen))


class CalibrationCollector:
    """Pairs the user's flag clicks with the province the game reports, into samples.

    Per province-open, the **first** click (the flag on the map) is the screen point we
    want; the ``provinceId`` arrives a moment later in a `getArmyPreview` request. So: the
    first click of a sequence is kept, later clicks (e.g. the Attack button) ignored, and the
    sample is emitted when the province id lands. Pure + testable."""

    def __init__(self, need: int = 2) -> None:
        self.need = need
        self.samples: list = []
        self._click = None
        self._pid = None

    def on_click(self, x, y) -> None:
        if self._click is None:
            self._click = (float(x), float(y))

    def on_province(self, province_id) -> None:
        self._pid = int(province_id)
        if self._click is not None:
            self.samples.append(CalibrationSample(self._pid, self._click))
            self._click = None
            self._pid = None

    def reset_current(self) -> None:
        self._click = None
        self._pid = None

    @property
    def done(self) -> bool:
        return len(self.samples) >= self.need


def _key(world: str, map_id: str | None) -> str:
    return f"{world}::{map_id or '?'}"


def save_calibration(path, world: str, map_id: str | None, t: MapTransform) -> None:
    """Persist ``t`` under (world, map_id) in a small JSON store (merged with any existing)."""
    p = Path(path)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[_key(world, map_id)] = {
        "world": world, "map_id": map_id,
        "scale_x": t.scale_x, "scale_y": t.scale_y, "off_x": t.off_x, "off_y": t.off_y,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_calibration(path, world: str, map_id: str | None) -> MapTransform | None:
    """Load a saved transform for (world, map_id), or None if absent/unreadable."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        e = data.get(_key(world, map_id))
        if not e:
            return None
        return MapTransform(e["scale_x"], e["scale_y"], e["off_x"], e["off_y"])
    except Exception:
        return None


__all__ = ["CalibrationSample", "CalibrationCollector", "solve_transform",
           "save_calibration", "load_calibration"]
