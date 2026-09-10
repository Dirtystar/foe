"""Dataset integrity validation (Milestone 5D).

Reports problems; **never silently repairs or deletes**. Each issue carries a
human-readable message and an *explicit* suggested fix the operator can choose to
apply. Read-only.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from bap.forge.collection.capture import META_DIRNAME, provenance_for
from bap.forge.dataset_store import (
    CALIB_NAME,
    FRAMES_DIRNAME,
    LABELS_NAME,
    reviewed_dataset_dir,
)
from bap.forge.labeling.model import VALID_PCTS

DUP_CENTER_PX = 6   # two badge centres this close are almost certainly one badge


@dataclass
class Issue:
    kind: str
    frame: str | None
    detail: str
    severity: str          # "error" | "warning"
    suggested_fix: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _frames_map(raw) -> dict:
    """Normalize labels.json (a list of frame records keyed by ``file``) to a
    ``{name: record}`` map, tolerating either the list or a legacy dict shape."""
    frames = raw.get("frames", []) if isinstance(raw, dict) else raw
    if isinstance(frames, dict):
        return frames
    out = {}
    for rec in frames or []:
        if isinstance(rec, dict):
            name = rec.get("file") or rec.get("name")
            if name:
                out[name] = rec
    return out


def validate_dataset(dataset_dir=None) -> dict:
    """Validate the canonical dataset and return ``{ok, counts, issues}``."""
    d = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir()
    frames_dir = d / FRAMES_DIRNAME
    labels_path = d / LABELS_NAME
    issues: list[Issue] = []

    frame_files = {p.name for p in frames_dir.glob("*.png")} if frames_dir.is_dir() else set()
    raw = json.loads(labels_path.read_text()) if labels_path.exists() else {"frames": []}
    labels = _frames_map(raw)

    # orphan labels (label without image) and missing images
    for name in labels:
        if name not in frame_files:
            issues.append(Issue("orphan_label", name,
                                 "labels.json references a frame that is not on disk",
                                 "error", "Remove this label entry or restore the image."))
    for name in sorted(frame_files):
        fl = labels.get(name)
        if fl is None:
            issues.append(Issue("missing_label", name,
                                 "image on disk has no label entry",
                                 "warning", "Open in Review to label, or leave as pending."))
            continue
        badges = fl.get("badges", [])
        reviewed = bool(fl.get("reviewed", False))
        # reviewed badge with null percentage
        if reviewed:
            for b in badges:
                if b.get("pct") is None:
                    issues.append(Issue("reviewed_null_pct", name,
                                         f"reviewed frame has an unclassified badge at "
                                         f"({b.get('cx')},{b.get('cy')})", "error",
                                         "Assign a percentage (1-5) or delete the badge, then re-save."))
        # invalid percentage
        for b in badges:
            pct = b.get("pct")
            if pct is not None and pct not in VALID_PCTS:
                issues.append(Issue("invalid_pct", name, f"badge pct {pct!r} is not one of {sorted(VALID_PCTS)}",
                                     "error", "Correct the percentage in Review."))
        # duplicate badge centres within a frame
        centers = [(b.get("cx"), b.get("cy")) for b in badges]
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                (x1, y1), (x2, y2) = centers[i], centers[j]
                if x1 is not None and abs(x1 - x2) <= DUP_CENTER_PX and abs(y1 - y2) <= DUP_CENTER_PX:
                    issues.append(Issue("duplicate_centers", name,
                                         f"two badges within {DUP_CENTER_PX}px ({x1},{y1})/({x2},{y2})",
                                         "warning", "Delete the duplicate detection in Review."))
        # missing provenance for a live-collected frame
        prov = provenance_for(name, dataset_dir=d)
        if prov is None and (d / META_DIRNAME).is_dir():
            issues.append(Issue("missing_metadata", name,
                                 "no provenance record (imported_meta/*.json)", "warning",
                                 "Recapture via Live Data Collection to attach provenance, or ignore for historical frames."))

    # duplicate images by content hash
    by_md5 = defaultdict(list)
    for name in sorted(frame_files):
        by_md5[hashlib.md5((frames_dir / name).read_bytes()).hexdigest()].append(name)
    for group in by_md5.values():
        if len(group) > 1:
            issues.append(Issue("duplicate_image", ", ".join(group),
                                 "identical image content stored under multiple names", "warning",
                                 "Keep one frame and remove the others (they train identically)."))

    # calibration coverage: every resolution present should have a calibration entry
    cal_res = _calibrated_resolutions(d / CALIB_NAME)
    seen_res = set()
    for name in frame_files:
        prov = provenance_for(name, dataset_dir=d)
        if prov and prov.get("capture_w") and prov.get("capture_h"):
            seen_res.add(f"{prov['capture_w']}x{prov['capture_h']}")
    for res in sorted(seen_res - cal_res):
        issues.append(Issue("calibration_mismatch", None,
                             f"resolution {res} has captured frames but no calibration entry",
                             "warning", "Set the weakening/battle-map region for this resolution in Review."))

    counts = defaultdict(int)
    for it in issues:
        counts[it.severity] += 1
    return {
        "ok": counts["error"] == 0,
        "counts": {"errors": counts["error"], "warnings": counts["warning"],
                   "frames": len(frame_files), "labels": len(labels)},
        "issues": [it.to_dict() for it in issues],
    }


def _calibrated_resolutions(calib_path: Path) -> set[str]:
    if not calib_path.exists():
        return set()
    try:
        data = json.loads(calib_path.read_text())
    except Exception:
        return set()
    out = set()
    for key in ("regions", "weakening", "battle_map", "entries"):
        section = data.get(key) if isinstance(data, dict) else None
        if isinstance(section, dict):
            out |= {k for k in section if "x" in str(k)}
    # also accept top-level resolution keys like "1920x1080"
    if isinstance(data, dict):
        out |= {k for k in data if isinstance(k, str) and "x" in k and k[0].isdigit()}
    return out


__all__ = ["validate_dataset", "Issue"]
