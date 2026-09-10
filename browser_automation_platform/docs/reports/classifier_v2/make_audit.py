"""Reproducible classifier data audit (Milestone 5C) — writes dataset_audit.json.

    python classifier_v2/make_audit.py

Runs the production detector over every reviewed frame to record the detector
centre-offset distribution alongside per-class / per-source / resolution counts.
Slow (detector pass); OBSERVE-ONLY, no clicking or cursor movement.
"""
import hashlib
import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from bap.forge.detection.classify import _PATCH_DX, _PATCH_DY, percent_patch
from bap.forge.detection.dataset import battle_map_box, load_all
from bap.forge.detection.detector import BadgeDetector
from bap.forge.detection.evaluate import _match


def main():
    samples = load_all()
    det = BadgeDetector()
    records, per_class, per_source = [], Counter(), Counter()
    per_source_class = defaultdict(Counter)
    res_dist, frame_md5, offsets = Counter(), {}, []
    for s in samples:
        img = cv2.imread(str(s.path))
        md5 = hashlib.md5(s.path.read_bytes()).hexdigest()
        frame_md5[s.key] = md5
        preds = det.scan(img, region=battle_map_box(s)).detections
        pairs, _um_p, _um_t = _match(preds, s.badges, 30.0)
        matched = {ti: d for _pi, ti, d in pairs}
        for ti, b in enumerate(s.badges):
            if b.pct is not None:
                per_class[b.pct] += 1
                per_source[s.source] += 1
                per_source_class[s.source][b.pct] += 1
                if ti in matched:
                    offsets.append(matched[ti])
            records.append({"frame": s.frame, "source": s.source, "world": s.world,
                            "pct": b.pct, "cx": b.cx, "cy": b.cy,
                            "capture_w": s.width, "capture_h": s.height,
                            "patch_valid": percent_patch(img, b.cx, b.cy) is not None,
                            "md5": md5, "detector_offset_px":
                                round(matched[ti], 2) if ti in matched else None})
        res_dist[f"{s.width}x{s.height}"] += 1
    by_md5 = defaultdict(list)
    for k, m in frame_md5.items():
        by_md5[m].append(k)
    audit = {
        "frames": len(samples), "badges_total": sum(len(s.badges) for s in samples),
        "badges_classified": sum(1 for r in records if r["pct"] is not None),
        "per_class": dict(sorted(per_class.items())),
        "per_source": dict(per_source),
        "per_source_class": {s: dict(sorted(c.items())) for s, c in per_source_class.items()},
        "resolution_distribution": dict(res_dist),
        "crop_raw_wh": [_PATCH_DX[1] - _PATCH_DX[0], _PATCH_DY[1] - _PATCH_DY[0]],
        "duplicate_md5_groups": {m: ks for m, ks in by_md5.items() if len(ks) > 1},
        "detector_offset_px": None if not offsets else {
            "n": len(offsets), "min": round(min(offsets), 2),
            "median": round(st.median(offsets), 2),
            "mean": round(sum(offsets) / len(offsets), 2), "max": round(max(offsets), 2),
            "p90": round(sorted(offsets)[int(0.9 * len(offsets))], 2)},
        "frames_per_source": dict(Counter(s.source for s in samples)),
    }
    Path("classifier_v2/dataset_audit.json").write_text(
        json.dumps({"audit": audit, "records": records}, indent=2))
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
