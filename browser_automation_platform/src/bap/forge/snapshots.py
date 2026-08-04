"""Reproducible Vision snapshots (Milestone 4.13) — observe-only.

The live Forge battleground changes within minutes, so a good scan is lost before
an investigation finishes. A **snapshot** freezes one scan into a permanent,
self-contained, immediately-reviewable directory:

    <root>/snapshots/<timestamp>_<alias>/
        frames/raw.png        # the one raw capture (Review Mode reads this dir)
        annotated.png         # the drawn overlay (never analysed)
        scan.json             # the full pipeline trace
        world.json            # the World this came from
        calibration.json      # the ROIs used, keyed by capture geometry
        labels.json           # ground truth (the ONLY file Review Mode rewrites)
        metadata.json         # alias, url, resolution, dpr, viewport, versions, git
        validation_report.md  # optional Vision Validation report

The raw image lives under ``frames/`` so "Open in Review" is a zero-copy
``run_review(frames/, labels.json, calibration.json)`` — Review Mode globs that
dir and sees exactly the one frame. A snapshot is **immutable except for
labels.json**: reviewing never rewrites the raw image, the annotation, or the
trace. This module is Qt-free and never clicks, moves the cursor, or types.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

SNAPSHOT_SCHEMA = 1
RAW_NAME = "raw.png"


def _slug(text: str | None) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", (text or "scan").strip()) or "scan"
    return s[:40]


def snapshots_root(base: Path | str | None = None) -> Path:
    """Default snapshots directory (under the app data dir), or ``base``/snapshots."""
    if base is not None:
        return Path(base) / "snapshots"
    try:
        from bap.ops.paths import ensure_dirs, get_paths

        return ensure_dirs(get_paths()).data_dir / "snapshots"
    except Exception:
        return Path("snapshots")


def image_md5(source) -> str | None:
    """MD5 of an image's PNG-encoded bytes (path) or raw file bytes."""
    try:
        if isinstance(source, (str, Path)):
            return hashlib.md5(Path(source).read_bytes()).hexdigest()
        # assume a BGR ndarray
        import cv2

        ok, buf = cv2.imencode(".png", source)
        return hashlib.md5(buf.tobytes()).hexdigest() if ok else None
    except Exception:
        return None


def git_commit() -> str | None:
    try:
        import subprocess

        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def detector_version(detector=None) -> str:
    from bap.forge.detection.detector import BadgeDetector

    thr = getattr(detector, "score_threshold", None)
    if thr is None:
        thr = getattr(BadgeDetector, "DEFAULT_SCORE_THRESHOLD", 0.62)
    return f"badge-colorprior+emblem+nms@{float(thr):.2f}"


def classifier_version(classifier=None) -> str:
    from bap.forge.detection.scan import MIN_PCT_SIM

    n = len(classifier) if classifier is not None else 0
    return f"exemplar-cosine@min_sim={MIN_PCT_SIM:.2f};exemplars={n}"


def _calibration_from_scan(scan, geometry, out_path: Path):
    """Persist the ROIs actually used, keyed by this capture geometry, so Review
    Mode loads the identical regions."""
    from bap.forge.detection.calibration import WeakeningCalibration

    cal = WeakeningCalibration(path=out_path)
    if geometry is not None:
        try:
            cal.set_geometry(geometry)
        except Exception:
            pass
    rois = scan.rois
    w = getattr(geometry, "raw_w", scan.width)
    h = getattr(geometry, "raw_h", scan.height)
    if rois is not None and rois.weakening is not None:
        cal.set(w, h, rois.weakening)
    if rois is not None and getattr(rois, "battle_map_calibrated", False):
        cal.set_battle_map(w, h, rois.battle_map)
    cal.save()
    return cal


def _labels_from_scan(scan, out_path: Path, *, seed_from_detections: bool = True):
    """Seed labels.json with the detected badges as an UNREVIEWED starting point
    (reviewed=False, so it is not ground truth until a human confirms it in Review
    Mode). Weakening is carried through as the frame's current value."""
    from bap.forge.labeling.model import Badge, FrameLabel, LabelStore, VALID_PCTS

    store = LabelStore(path=out_path)
    label = store.ensure(RAW_NAME)
    if seed_from_detections:
        for d in scan.detections:
            pct = d.pct if d.pct in VALID_PCTS else None
            label.badges.append(Badge(cx=int(d.cx), cy=int(d.cy), pct=pct))
    label.reviewed = False
    weak = scan.weakening
    label.weakening = int(weak.value) if (weak is not None and weak.value is not None) else None
    store.save()
    return store


def write_snapshot(
    image,
    scan,
    *,
    world=None,
    classifier=None,
    detector=None,
    validation_markdown: str | None = None,
    url: str | None = None,
    root: Path | str | None = None,
    seed_labels: bool = True,
    timestamp: datetime | None = None,
) -> Path:
    """Freeze one scan into a reproducible snapshot directory and return its path."""
    import cv2

    from bap.forge.detection.scan import annotate

    ts = timestamp or datetime.now()
    alias = getattr(world, "alias", None) or getattr(scan, "world_alias", None)
    name = f"{ts.strftime('%Y-%m-%d_%H-%M-%S')}_{_slug(alias)}"
    out = snapshots_root(root) / name
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    raw_path = frames_dir / RAW_NAME
    cv2.imwrite(str(raw_path), image)
    cv2.imwrite(str(out / "annotated.png"), annotate(image, scan))
    (out / "scan.json").write_text(json.dumps(scan.to_dict(), indent=2), encoding="utf-8")
    (out / "world.json").write_text(
        json.dumps(world.to_dict() if world is not None else None, indent=2), encoding="utf-8")

    geometry = scan.geometry
    _calibration_from_scan(scan, geometry, out / "calibration.json")
    _labels_from_scan(scan, out / "labels.json", seed_from_detections=seed_labels)
    if validation_markdown:
        (out / "validation_report.md").write_text(validation_markdown, encoding="utf-8")

    meta = {
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "world_alias": alias,
        "url": url or getattr(world, "last_url", None),
        "resolution": [scan.width, scan.height],
        "device_pixel_ratio": getattr(geometry, "device_pixel_ratio", None),
        "viewport": [getattr(geometry, "viewport_w", None), getattr(geometry, "viewport_h", None)],
        "timestamp": ts.isoformat(timespec="seconds"),
        "detector_version": detector_version(detector),
        "classifier_version": classifier_version(classifier),
        "git_commit": git_commit(),
        "image_md5": image_md5(raw_path),
        "decision": scan.decision.value,
        "weakening": scan.weakening.value if (scan.weakening and scan.weakening.value is not None) else None,
        "counts": scan.counts,
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out


def review_paths(snapshot_dir: Path | str) -> tuple[str, str, str]:
    """(frames_dir, labels_path, calibration_path) for a zero-copy Open-in-Review."""
    d = Path(snapshot_dir)
    return str(d / "frames"), str(d / "labels.json"), str(d / "calibration.json")


def load_snapshot(snapshot_dir: Path | str) -> dict:
    """Load a snapshot's metadata, labels, and file paths for reload/inspection."""
    from bap.forge.labeling.model import LabelStore

    d = Path(snapshot_dir)
    meta = {}
    meta_path = d / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    labels = LabelStore.load(d / "labels.json")
    return {
        "dir": str(d),
        "raw": str(d / "frames" / RAW_NAME),
        "annotated": str(d / "annotated.png"),
        "scan_json": str(d / "scan.json"),
        "metadata": meta,
        "labels": labels,
    }


def import_into_dataset(snapshot_dir: Path | str, dataset_dir: Path | str | None = None) -> dict:
    """Import a snapshot's raw frame + label into the dataset (frames/ + labels.json),
    deduplicating by image content hash. Preserves the label and the snapshot's
    metadata, merges the snapshot's ROIs into the dataset calibration, and never
    imports the same image twice.

    When ``dataset_dir`` is omitted the import goes to THE one canonical reviewed
    dataset (:func:`bap.forge.dataset_store.reviewed_dataset_dir`), so a snapshot
    imported from anywhere in the UI lands in the single place Review Mode edits
    (Milestone 4.15)."""
    from bap.forge.labeling.model import LabelStore

    snap = Path(snapshot_dir)
    if dataset_dir is None:
        from bap.forge.dataset_store import reviewed_dataset_dir

        dataset = reviewed_dataset_dir(create=True)
    else:
        dataset = Path(dataset_dir)
    raw = snap / "frames" / RAW_NAME
    if not raw.exists():
        return {"imported": False, "reason": "snapshot has no frames/raw.png", "dest": None}

    frames_out = dataset / "frames"
    frames_out.mkdir(parents=True, exist_ok=True)
    new_md5 = image_md5(raw)

    # Dedup by content hash against every frame already in the dataset.
    for existing in sorted(frames_out.glob("*.png")):
        if image_md5(existing) == new_md5:
            return {"imported": False, "reason": "duplicate image already in dataset",
                    "dest": str(existing), "md5": new_md5}

    # Unique, stable destination name derived from the snapshot dir.
    dest_name = f"{snap.name}.png"
    dest = frames_out / dest_name
    i = 1
    while dest.exists():
        dest = frames_out / f"{snap.name}_{i}.png"
        i += 1
    shutil.copy2(raw, dest)

    # Merge the snapshot's label (re-keyed to the destination filename).
    snap_labels = LabelStore.load(snap / "labels.json")
    src_label = snap_labels.get(RAW_NAME)
    ds_store = LabelStore.load(dataset / "labels.json")
    if src_label is not None:
        dst_label = ds_store.ensure(dest.name)
        dst_label.badges = list(src_label.badges)
        dst_label.reviewed = src_label.reviewed
        dst_label.weakening = src_label.weakening
    else:
        ds_store.ensure(dest.name)
    if ds_store.path is None:
        ds_store._path = dataset / "labels.json"  # bind so save writes to the dataset
    ds_store.save()

    # Preserve the snapshot metadata alongside (ignored by the *.png frame glob).
    meta_src = snap / "metadata.json"
    if meta_src.exists():
        meta_dir = dataset / "imported_meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(meta_src, meta_dir / f"{dest.stem}.json")

    # Merge the snapshot's ROIs into the dataset calibration so Review Mode on the
    # imported frame shows the same weakening / battle-map regions it was scanned with.
    _merge_calibration(snap / "calibration.json", dataset / "calibration.json")

    return {"imported": True, "reason": "imported", "dest": str(dest), "md5": new_md5}


def _merge_calibration(src_path: Path, dst_path: Path) -> None:
    """Fold every resolution-keyed ROI from a snapshot's calibration into the
    dataset calibration (existing dataset entries win, so an operator's dataset
    calibration is never overwritten by an import)."""
    from bap.forge.detection.calibration import WeakeningCalibration

    if not Path(src_path).exists():
        return
    try:
        src = WeakeningCalibration.load(src_path)
        dst = WeakeningCalibration.load(dst_path)  # bound to dst_path for save()
    except Exception:
        return
    changed = False
    for attr in ("_regions", "_battle_map", "_geometry"):
        dst_map = getattr(dst, attr)
        for key, value in getattr(src, attr).items():
            if key not in dst_map:
                dst_map[key] = value
                changed = True
    if changed:
        dst.save()


__all__ = [
    "SNAPSHOT_SCHEMA", "RAW_NAME", "snapshots_root", "image_md5", "git_commit",
    "detector_version", "classifier_version", "write_snapshot", "review_paths",
    "load_snapshot", "import_into_dataset",
]
