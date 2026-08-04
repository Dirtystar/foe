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

# Canonical dataset roots (relative to the repo's tests dir).
HISTORICAL_DIR = Path("tests/forge_assets/grading")
LIVE_DIR = Path("tests/forge_assets/live_review")
# Reviewed active-learning batch. Present only after the operator pushes their
# corrected labels; loaders skip it cleanly while it is absent.
REVIEW_BATCH_2_DIR = Path("tests/forge_assets/review_batch_002")


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


def load_snapshot_dataset(base: Path | str | None = None) -> list[Sample]:
    """Reviewed frames imported via "Import Snapshot into Dataset" (repo-root
    ``dataset/``). Resolved robustly (cwd-independent) when ``base`` is None.
    Returns [] when the directory is absent, so it is a no-op until snapshots are
    imported. Only reviewed frames load (the standard ground-truth gate)."""
    if base is None:
        from bap.forge.detection.classify import default_snapshot_dataset_dir

        base = default_snapshot_dataset_dir()
    if base is None:
        return []
    base = Path(base)
    if not (base / "labels.json").exists():
        return []
    return _load(base, "snapshot", world_from_name=False)


def load_review_batch(base: Path | str = REVIEW_BATCH_2_DIR) -> list[Sample]:
    """The reviewed active-learning batch, or an empty list when it has not been
    pushed yet (guarded absence — never an error)."""
    base = Path(base)
    if not (base / "labels.json").exists():
        return []
    return _load(base, "review_batch_002", world_from_name=True)


def _dedup_by_content(samples: list[Sample]) -> list[Sample]:
    """Drop frames that appear under more than one root by exact image content,
    keeping the LAST occurrence so a later (reviewed) source's corrected labels
    win over an earlier copy. A no-op while the roots are disjoint."""
    seen: dict[str, int] = {}
    out: list[Sample] = []
    for s in samples:
        try:
            digest = _md5(s.path.read_bytes())
        except OSError:
            out.append(s)
            continue
        if digest in seen:
            out[seen[digest]] = s      # later source supersedes the earlier copy
        else:
            seen[digest] = len(out)
            out.append(s)
    return out


def _md5(data: bytes) -> str:
    import hashlib

    return hashlib.md5(data).hexdigest()


def load_all(historical: Path | str = HISTORICAL_DIR,
             live: Path | str = LIVE_DIR,
             review_batch: Path | str = REVIEW_BATCH_2_DIR,
             snapshots: Path | str | None = None) -> list[Sample]:
    """Every reviewed source, concatenated then de-duplicated by image content so
    a frame reviewed in more than one place is counted once (the later, reviewed
    source wins). ``review_batch`` and the imported-snapshot ``dataset/`` are each
    included only when present. Snapshots are appended last so their (reviewed)
    labels supersede any earlier copy of the same image."""
    return _dedup_by_content(
        load_historical(historical) + load_live(live)
        + load_review_batch(review_batch) + load_snapshot_dataset(snapshots))


def battle_map_box(sample: Sample) -> tuple[int, int, int, int]:
    r = sample.rois.battle_map
    return (r.x, r.y, r.x + r.w, r.y + r.h)


__all__ = [
    "Sample", "GtBadge", "HISTORICAL_DIR", "LIVE_DIR", "REVIEW_BATCH_2_DIR",
    "load_historical", "load_live", "load_review_batch", "load_snapshot_dataset",
    "load_all", "battle_map_box",
]
