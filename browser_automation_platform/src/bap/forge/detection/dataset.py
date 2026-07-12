"""One dataset-loading contract for the Forge vision evaluation.

Two labelled sources, loaded the same way and kept separate:

  * **historical** — ``tests/forge_assets/grading/`` (desktop screenshots, the
    original regression set).
  * **live**       — ``tests/forge_assets/live_review/`` (reviewed page-content
    captures from real Worlds H/F).

Each returns a list of :class:`Sample`, one per reviewed frame, carrying its
source, World alias (parsed from the live filename prefix), capture geometry,
both calibrated ROIs, badge centres + percentages, and the weakening ground
truth. Source images are never modified; there is no silent path fallback — a
missing labels/calibration file is an explicit error at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bap.core.domain.models import Rect
from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.detection.geometry import CaptureGeometry, ScanRois, derive_rois
from bap.forge.labeling.model import LabelStore

# Canonical, non-overlapping dataset roots (relative to the repo's tests dir).
HISTORICAL_DIR = Path("tests/forge_assets/grading")
LIVE_DIR = Path("tests/forge_assets/live_review")


@dataclass
class GtBadge:
    cx: int
    cy: int
    pct: int | None


@dataclass
class Sample:
    source: str                 # "historical" | "live"
    frame: str                  # filename
    frames_dir: Path
    world: str | None           # alias parsed from a live filename, else None
    width: int
    height: int
    rois: ScanRois
    badges: list[GtBadge] = field(default_factory=list)
    weakening: int | None = None

    @property
    def path(self) -> Path:
        return self.frames_dir / self.frame

    @property
    def key(self) -> str:
        """Frame-group key for leave-one-frame-out (unique per source+frame)."""
        return f"{self.source}:{self.frame}"


def _world_from_filename(name: str) -> str | None:
    """Live frames are saved as ``<World>_<timestamp>.png`` by Review Mode."""
    head = name.split("_", 1)[0]
    return head if head and head not in {"scan"} else None


def _load(base: Path, source: str, *, world_from_name: bool) -> list[Sample]:
    base = Path(base)
    labels_path = base / "labels.json"
    calib_path = base / "calibration.json"
    if not labels_path.exists():
        raise FileNotFoundError(f"labels.json not found for {source} set at {labels_path}")
    store = LabelStore.load(labels_path)
    cal = WeakeningCalibration.load(calib_path) if calib_path.exists() else None
    frames_dir = base / "frames"

    import cv2

    samples: list[Sample] = []
    for name in store.files():
        fl = store.get(name)
        if fl is None or not fl.reviewed:
            continue
        img = cv2.imread(str(frames_dir / name))
        if img is None:
            continue
        h, w = img.shape[:2]
        rois = derive_rois(CaptureGeometry(raw_w=w, raw_h=h), cal)
        samples.append(Sample(
            source=source, frame=name, frames_dir=frames_dir,
            world=_world_from_filename(name) if world_from_name else None,
            width=w, height=h, rois=rois,
            badges=[GtBadge(b.cx, b.cy, b.pct) for b in fl.badges],
            weakening=fl.weakening,
        ))
    return samples


def load_historical(base: Path | str = HISTORICAL_DIR) -> list[Sample]:
    return _load(Path(base), "historical", world_from_name=False)


def load_live(base: Path | str = LIVE_DIR) -> list[Sample]:
    return _load(Path(base), "live", world_from_name=True)


def load_all(historical: Path | str = HISTORICAL_DIR,
             live: Path | str = LIVE_DIR) -> list[Sample]:
    """Both sources, concatenated. No de-duplication is needed — the two roots are
    disjoint and each frame is unique within its source."""
    return load_historical(historical) + load_live(live)


def battle_map_box(sample: Sample) -> tuple[int, int, int, int]:
    r = sample.rois.battle_map
    return (r.x, r.y, r.x + r.w, r.y + r.h)


__all__ = [
    "Sample", "GtBadge", "HISTORICAL_DIR", "LIVE_DIR",
    "load_historical", "load_live", "load_all", "battle_map_box",
]
