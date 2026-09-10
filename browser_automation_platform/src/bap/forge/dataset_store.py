"""The single canonical **Reviewed Dataset** (Milestone 4.15).

One obvious place where reviewed ground truth lives, and one function every part of
the app uses to find it. This removes the old ambiguity between AppData
(``forge/live_review``), per-snapshot ``labels.json`` islands, and the repo-root
``dataset/``: from now on there is exactly **one** editable reviewed dataset, and
every "review from the UI" action edits *that exact* dataset.

Layout (created on first use):

    <reviewed-dataset>/
        frames/            # one PNG per reviewed frame
        labels.json        # the ONE ground-truth file every Review edits
        calibration.json   # weakening / battle-map ROIs, keyed by capture geometry
        imported_meta/     # provenance for frames imported from snapshots

Resolution order for the location:

    1. ``BAP_DATASET_DIR`` env var (explicit override)
    2. the repo-root ``dataset/`` when running from source (also what the training
       + evaluation pipeline discovers — see ``classify.default_snapshot_dataset_dir``)
    3. ``<app-data>/dataset`` when installed/frozen with no repo checkout

Snapshots remain immutable archives; to review one, import it here and review the
imported copy. Nothing in this module clicks, moves the cursor, or types.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

DATASET_DIRNAME = "dataset"
LABELS_NAME = "labels.json"
CALIB_NAME = "calibration.json"
FRAMES_DIRNAME = "frames"


def _repo_root() -> Path | None:
    """The repository root when running from source (has pyproject.toml or the
    committed ``tests/forge_assets`` datasets), else None."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() or (parent / "tests" / "forge_assets").is_dir():
            return parent
    return None


def reviewed_dataset_dir(*, create: bool = False) -> Path:
    """Return THE one canonical reviewed-dataset directory. When ``create`` is
    True the directory, its ``frames/`` folder, and an empty ``labels.json`` are
    materialised so callers can write immediately."""
    override = os.environ.get("BAP_DATASET_DIR")
    if override:
        root = Path(override).expanduser()
    else:
        repo = _repo_root()
        if repo is not None:
            root = repo / DATASET_DIRNAME
        else:  # installed / frozen: fall back to the writable app-data dir
            from bap.ops.paths import ensure_dirs, get_paths

            root = ensure_dirs(get_paths()).data_dir / DATASET_DIRNAME
    if create:
        (root / FRAMES_DIRNAME).mkdir(parents=True, exist_ok=True)
        labels = root / LABELS_NAME
        if not labels.exists():
            from bap.forge.labeling.model import LabelStore

            LabelStore(labels).save()  # write an empty, valid labels.json
    return root


def dataset_labels_path(*, create: bool = False) -> Path:
    return reviewed_dataset_dir(create=create) / LABELS_NAME


def dataset_calibration_path(*, create: bool = False) -> Path:
    return reviewed_dataset_dir(create=create) / CALIB_NAME


def dataset_review_paths(*, create: bool = True) -> tuple[str, str, str]:
    """(frames_dir, labels_path, calibration_path) for opening Review Mode on the
    canonical dataset. Everything the UI opens for review comes from here."""
    d = reviewed_dataset_dir(create=create)
    return str(d / FRAMES_DIRNAME), str(d / LABELS_NAME), str(d / CALIB_NAME)


def dataset_exists() -> bool:
    d = reviewed_dataset_dir()
    return (d / LABELS_NAME).exists() and (d / FRAMES_DIRNAME).is_dir()


def _md5_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _slug(text: str | None) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", (text or "scan").strip()) or "scan"
    return s[:24]


def add_frame(
    image,
    *,
    alias: str | None = None,
    scan=None,
    dataset_dir: Path | str | None = None,
    source: str = "scan",
    timestamp: datetime | None = None,
) -> tuple[str, bool]:
    """Add one captured frame to the canonical dataset and return
    ``(frame_name, is_new)``.

    Deduplicates by image content hash (an identical frame is never added twice).
    A new frame's label is seeded from the scan's detections as an **unreviewed**
    starting point (percentages only when known; the operator confirms in Review),
    the weakening value is carried through, and the scan's ROIs are persisted into
    the dataset calibration so Review Mode shows the same regions."""
    import cv2

    root = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir(create=True)
    (root / FRAMES_DIRNAME).mkdir(parents=True, exist_ok=True)
    frames = root / FRAMES_DIRNAME

    ok, buf = cv2.imencode(".png", image)
    digest = hashlib.md5(buf.tobytes()).hexdigest() if ok else None
    if digest is not None:
        for existing in sorted(frames.glob("*.png")):
            if _md5_file(existing) == digest:
                return existing.name, False

    ts = timestamp or datetime.now()
    name = f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}_{_slug(alias or source)}.png"
    i = 1
    while (frames / name).exists():
        name = f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}_{_slug(alias or source)}_{i}.png"
        i += 1
    cv2.imwrite(str(frames / name), image)

    from bap.forge.labeling.model import Badge, LabelStore, VALID_PCTS

    store = LabelStore.load(root / LABELS_NAME)
    if store.path is None:
        store.bind(root / LABELS_NAME)
    label = store.ensure(name)
    if scan is not None:
        for det in getattr(scan, "detections", []):
            pct = det.pct if det.pct in VALID_PCTS else None
            label.badges.append(Badge(cx=int(det.cx), cy=int(det.cy), pct=pct))
        weak = getattr(scan, "weakening", None)
        if weak is not None and weak.value is not None:
            label.weakening = int(weak.value)
    store.save()

    if scan is not None and getattr(scan, "rois", None) is not None:
        _persist_calibration(root, image, scan.rois)
    return name, True


def _persist_calibration(root: Path, image, rois) -> None:
    from bap.forge.detection.calibration import WeakeningCalibration

    cal = WeakeningCalibration.load(root / CALIB_NAME)
    h, w = image.shape[:2]
    if rois.weakening is not None:
        cal.set(w, h, rois.weakening)
    if getattr(rois, "battle_map_calibrated", False):
        cal.set_battle_map(w, h, rois.battle_map)
    cal.save()


def dataset_summary() -> dict:
    """Frame + reviewed counts for the canonical dataset (for the UI)."""
    from bap.forge.labeling.model import LabelStore

    d = reviewed_dataset_dir()
    frames = list((d / FRAMES_DIRNAME).glob("*.png")) if (d / FRAMES_DIRNAME).is_dir() else []
    store = LabelStore.load(d / LABELS_NAME) if (d / LABELS_NAME).exists() else LabelStore()
    reviewed = store.reviewed_count()
    labelled = len(store)
    return {"dir": str(d), "frames": len(frames), "labelled": labelled, "reviewed": reviewed}


__all__ = [
    "DATASET_DIRNAME", "LABELS_NAME", "CALIB_NAME", "FRAMES_DIRNAME",
    "reviewed_dataset_dir", "dataset_labels_path", "dataset_calibration_path",
    "dataset_review_paths", "dataset_exists", "add_frame", "dataset_summary",
]
