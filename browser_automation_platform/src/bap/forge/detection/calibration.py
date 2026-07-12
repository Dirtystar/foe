"""Per-resolution Forge calibration — the weakening-number region.

The current-weakening number sits at a fixed spot in the top bar for a given
capture setup, but that spot depends on the window/resolution. The user draws
the rectangle once (Debugger → Set Weakening Region); it is stored keyed by
resolution so it is restored next launch. No pixels are guessed — this is the
user's calibration, persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

from bap.core.domain.models import Rect


def resolution_key(width: int, height: int) -> str:
    return f"{int(width)}x{int(height)}"


class WeakeningCalibration:
    def __init__(self, path: Path | str | None = None, regions: dict | None = None):
        self._path = Path(path) if path is not None else None
        self._regions: dict[str, Rect] = dict(regions or {})

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

    def resolutions(self) -> list[str]:
        return list(self._regions)

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "weakening_regions": {
                k: {"x": r.x, "y": r.y, "w": r.w, "h": r.h} for k, r in self._regions.items()
            },
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
        for key, r in (data or {}).get("weakening_regions", {}).items():
            try:
                cal._regions[key] = Rect(x=int(r["x"]), y=int(r["y"]), w=int(r["w"]), h=int(r["h"]))
            except (KeyError, TypeError, ValueError):
                continue
        return cal


__all__ = ["WeakeningCalibration", "resolution_key"]
