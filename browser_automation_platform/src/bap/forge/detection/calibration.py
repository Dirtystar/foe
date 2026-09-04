"""Per-resolution Forge calibration — the two Test-Scan analysis regions.

Both the current-weakening number (top bar) and the usable battleground map sit
at fixed spots for a given capture setup, but those spots depend on the
window/resolution. The user draws each rectangle once (Debugger → Set Weakening
Region / Set Battle-Map Region); they are stored keyed by resolution so they are
restored next launch, together with the exact capture geometry they were drawn
against. No pixels are guessed — this is the user's calibration, persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

from bap.core.domain.models import Rect


def resolution_key(width: int, height: int) -> str:
    return f"{int(width)}x{int(height)}"


class WeakeningCalibration:
    def __init__(self, path: Path | str | None = None, regions: dict | None = None,
                 battle_map_regions: dict | None = None, geometry: dict | None = None):
        self._path = Path(path) if path is not None else None
        self._regions: dict[str, Rect] = dict(regions or {})
        self._battle_map: dict[str, Rect] = dict(battle_map_regions or {})
        self._geometry: dict[str, dict] = dict(geometry or {})

    @property
    def path(self) -> Path | None:
        return self._path

    def get(self, width: int, height: int) -> Rect | None:
        return self._regions.get(resolution_key(width, height))

    def set(self, width: int, height: int, rect: Rect) -> None:
        if rect.w <= 0 or rect.h <= 0:
            raise ValueError("weakening region must have positive size")
        self._regions[resolution_key(width, height)] = rect
        self.save()

    def get_battle_map(self, width: int, height: int) -> Rect | None:
        return self._battle_map.get(resolution_key(width, height))

    def set_battle_map(self, width: int, height: int, rect: Rect) -> None:
        if rect.w <= 0 or rect.h <= 0:
            raise ValueError("battle-map region must have positive size")
        self._battle_map[resolution_key(width, height)] = rect
        self.save()

    def geometry_for(self, width: int, height: int) -> dict | None:
        return self._geometry.get(resolution_key(width, height))

    def set_geometry(self, geometry) -> None:
        """Record the exact capture geometry a region was calibrated against, so
        a mismatched capture setup can be detected rather than silently reused."""
        self._geometry[resolution_key(geometry.raw_w, geometry.raw_h)] = geometry.to_dict()
        self.save()

    def resolutions(self) -> list[str]:
        return list(self._regions)

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)

        def dump(regions: dict[str, Rect]) -> dict:
            return {k: {"x": r.x, "y": r.y, "w": r.w, "h": r.h} for k, r in regions.items()}

        payload = {
            "version": 2,
            "weakening_regions": dump(self._regions),
            "battle_map_regions": dump(self._battle_map),
            "geometry": self._geometry,
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    @classmethod
    def load(cls, path: Path | str) -> "WeakeningCalibration":
        path = Path(path)
        cal = cls(path=path)
        if not path.exists():
            return cal
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cal
        data = data or {}

        def load_into(dest: dict[str, Rect], key: str) -> None:
            for k, r in data.get(key, {}).items():
                try:
                    dest[k] = Rect(x=int(r["x"]), y=int(r["y"]), w=int(r["w"]), h=int(r["h"]))
                except (KeyError, TypeError, ValueError):
                    continue

        load_into(cal._regions, "weakening_regions")
        load_into(cal._battle_map, "battle_map_regions")
        cal._geometry = dict(data.get("geometry", {}))
        return cal


__all__ = ["WeakeningCalibration", "resolution_key"]
