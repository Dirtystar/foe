"""GBG map layout — where each province sits, and the map→screen transform.

The game ships a static map asset (`assets/guild_battlegrounds/map/data/<mapId>-…`) that
lists, for every province id, the **flag position in map space** (a fixed 2500×1960-ish
coordinate system). Combined with a small **calibration** (two known province → screen
clicks) we can compute the on-screen point of *any* province — the "where to click" that
province auto-selection (B3) needs. This module is pure geometry + parsing; no browser.

Confirmed from a real capture: every `getBattleground` province id has a flag here
(fixture `dataset/api_samples/map_data.*.sample.json`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapLayout:
    map_id: str | None
    width: int | None
    height: int | None
    flags: dict          # province_id -> (map_x, map_y)

    def flag(self, province_id: int):
        return self.flags.get(province_id)


def parse_map_data(obj, *, map_id: str | None = None) -> MapLayout | None:
    """Parse a `map/data/<mapId>` asset body into a :class:`MapLayout`. Returns None if it
    doesn't look like map data. Defensive: a province without a flag is skipped."""
    if not isinstance(obj, dict) or "provinces" not in obj:
        return None
    size = obj.get("size") or {}
    flags: dict = {}
    for p in obj.get("provinces") or []:
        if not isinstance(p, dict):
            continue
        f = p.get("flag") or {}
        try:
            pid = int(p.get("id", 0))
            flags[pid] = (float(f["x"]), float(f["y"]))
        except (TypeError, ValueError, KeyError):
            continue
    if not flags:
        return None
    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return MapLayout(map_id=map_id or obj.get("id"),
                     width=_int(size.get("width")), height=_int(size.get("height")),
                     flags=flags)


@dataclass(frozen=True)
class MapTransform:
    """Axis-aligned affine map→screen: ``screen = scale * map + offset`` per axis (no
    rotation/shear — the GBG map renders un-rotated). Enough to place any province flag."""

    scale_x: float
    scale_y: float
    off_x: float
    off_y: float

    def to_screen(self, map_x: float, map_y: float) -> tuple:
        return (self.scale_x * map_x + self.off_x, self.scale_y * map_y + self.off_y)

    @classmethod
    def from_two_points(cls, a_map, a_screen, b_map, b_screen) -> "MapTransform":
        """Solve the transform from two calibration points (each a (map, screen) pair). The
        two map points must differ on **both** axes (pick provinces apart in x and y)."""
        (amx, amy), (asx, asy) = a_map, a_screen
        (bmx, bmy), (bsx, bsy) = b_map, b_screen
        if amx == bmx or amy == bmy:
            raise ValueError("calibration provinces must differ in both x and y")
        sx = (bsx - asx) / (bmx - amx)
        sy = (bsy - asy) / (bmy - amy)
        return cls(scale_x=sx, scale_y=sy, off_x=asx - sx * amx, off_y=asy - sy * amy)


def province_screen_point(layout: MapLayout, transform: MapTransform, province_id: int):
    """Screen (viewport) point of a province's flag, or None if the id has no flag."""
    f = layout.flag(province_id)
    if f is None:
        return None
    return transform.to_screen(f[0], f[1])


__all__ = ["MapLayout", "MapTransform", "parse_map_data", "province_screen_point"]
