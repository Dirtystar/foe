"""Active-learning review-batch builder for the Forge vision pipeline.

Given a folder of Forge screenshots, this ranks which ones are worth annotating
next — the highest *expected information gain* — while keeping the batch diverse
(near-duplicates are clustered and capped). It is **read-only** with respect to
the models: it runs the existing detector + classifier + scan pipeline to observe
their behaviour but never modifies the detector, the classifier, or any
threshold, and it retrains nothing.

Per frame it derives information-gain factors from the pipeline's own trace:

  * ``unknown_pct``       — badges detected but left UNKNOWN (need a label).
  * ``uncertain``         — accepted %s whose exemplar similarity sits near the
                            accept bar, or whose top-2 exemplar classes are close.
  * ``competing``         — several accepted detections (more to verify).
  * ``candidates``        — high stage-1 candidate count.
  * ``rejected``          — high rejected count.
  * ``near_thresh_reject``— stage-1 template scores just under the accept bar.
  * ``stage_disagree``    — strong colour prior but a rejecting template score
                            (the two detector stages disagree).
  * ``rare_background``   — battle-map ROI colour far from the corpus norm.
  * ``rare_scale``        — an under-represented capture resolution.

Selection is diversity-aware: frames are clustered by a perceptual descriptor,
then chosen round-robin from the highest-gain clusters with a per-cluster cap —
deliberately **not** the top-N by uncertainty.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.detection.classify import train_from_sources
from bap.forge.detection.detector import TEMPLATE_SIZE, BadgeDetector
from bap.forge.detection.geometry import CaptureGeometry, derive_rois
from bap.forge.detection.scan import MIN_PCT_SIM, _classify

# Version tag for the per-frame cache. Bump when the feature computation changes.
_CACHE_VERSION = 1

_NEAR = 0.10          # "near the accept bar" band for classifier similarity
_MARGIN = 0.05        # small top-2 exemplar-class margin = ambiguous
_DUP_SIM = 0.985      # perceptual cosine >= this => near-duplicate (same cluster)


@dataclass
class FrameInfo:
    file: str
    source_path: Path
    source: str                 # dataset tag (e.g. "grading" / "live_review")
    world: str | None
    width: int
    height: int
    descriptor: object = None   # perceptual vector for clustering
    bg: object = None           # battle-map ROI mean colour
    counts: dict = field(default_factory=dict)
    factors: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    cluster: int = -1
    score: float = 0.0


def _descriptor(img):
    import cv2
    import numpy as np

    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype("float32").ravel()
    g -= g.mean()
    n = float(np.linalg.norm(g)) or 1.0
    return g / n


def _world_from_name(name: str) -> str | None:
    head = name.split("_", 1)[0]
    return head if head and head not in {"scan", "frame"} else None


def _classify_uncertainty(diag: list[dict]) -> tuple[int, int]:
    """(uncertain_accepted, unknown) from the per-candidate classification trace.

    An accepted read is 'uncertain' when its similarity is within `_NEAR` of the
    accept bar, or its two nearest exemplar CLASSES are within `_MARGIN`."""
    uncertain = unknown = 0
    for d in diag:
        if not d.get("accepted"):
            unknown += 1
            continue
        sim = d.get("similarity") or 0.0
        near_bar = abs(sim - MIN_PCT_SIM) <= _NEAR
        top5 = d.get("top5") or []
        margin_small = False
        if top5:
            best_pct = top5[0][0]
            for pct, s in top5[1:]:
                if pct != best_pct:
                    margin_small = (top5[0][1] - s) <= _MARGIN
                    break
        if near_bar or margin_small:
            uncertain += 1
    return uncertain, unknown


def _box(rect):
    return (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h)


def _counts(candidates, detections) -> dict:
    """Identical to DebugScan.counts, computed from the lean scan+classify path."""
    stage1 = len(candidates)
    confirmed = sum(1 for c in candidates if c.get("confirmed"))
    accepted = len(detections)
    classified = sum(1 for d in detections if d.pct is not None)
    return {
        "stage1_candidates": stage1, "template_confirmed": confirmed,
        "rejected": stage1 - accepted, "final_detections": accepted,
        "percentage_classified": classified, "percentage_unknown": accepted - classified,
    }


def _frame_core(img, rois, detector, classifier) -> dict:
    """The expensive per-frame work, reduced to exactly what ranking needs:
    detector.scan + percentage classification. It deliberately skips the weakening
    OCR, the province-panel probe, and target selection — none of which affect any
    information-gain factor — so it is faster than a full ``build_scan`` while
    producing byte-identical ranking features."""
    import numpy as np

    result = detector.scan(img, region=_box(rois.battle_map))
    detections = result.detections
    classify_diag: list[dict] = []
    if classifier is not None and len(classifier):
        detections, classify_diag = _classify(img, detections, classifier)
    cands = result.candidates
    counts = _counts(cands, detections)
    uncertain, unknown = _classify_uncertainty(classify_diag)

    near_thresh = sum(1 for c in cands
                      if (c.get("template_score") is not None
                          and MIN_PCT_SIM - _NEAR <= c["template_score"] < MIN_PCT_SIM))
    areas = [c.get("color_area", 0) for c in cands]
    area_p75 = float(np.percentile(areas, 75)) if areas else 0.0
    stage_disagree = sum(1 for c in cands
                         if c.get("color_area", 0) >= area_p75
                         and (c.get("template_score") or 0.0) < MIN_PCT_SIM)

    bm = rois.battle_map
    roi = img[max(0, bm.y):bm.y + bm.h, max(0, bm.x):bm.x + bm.w]
    bg = roi.reshape(-1, 3).mean(axis=0) if roi.size else np.zeros(3)

    h, w = img.shape[:2]
    return {
        "width": w, "height": h,
        "descriptor": _descriptor(img).tolist(),
        "bg": [float(x) for x in bg],
        "counts": counts,
        "factors_abs": {
            "unknown_pct": unknown, "uncertain": uncertain,
            "competing": counts["final_detections"], "candidates": counts["stage1_candidates"],
            "rejected": counts["rejected"], "near_thresh_reject": near_thresh,
            "stage_disagree": stage_disagree,
        },
    }


def _detector_signature(detector: BadgeDetector, classifier) -> str:
    d = detector
    parts = [len(d._templates), tuple(d._scales), d._threshold, d._offset, d._nms_radius,
             d._sat_min, d._val_min, d._min_area, d._max_area, d._max_side,
             MIN_PCT_SIM, (len(classifier) if classifier is not None else 0), _CACHE_VERSION]
    return hashlib.md5(repr(parts).encode()).hexdigest()[:16]


def _frame_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()[:16]


def _core_from_frameinfo(f: FrameInfo) -> dict:
    return {"width": f.width, "height": f.height,
            "descriptor": f.descriptor.tolist(), "bg": [float(x) for x in f.bg],
            "counts": f.counts, "factors_abs": dict(f.factors)}


def analyze(frames_dir: Path | str, *, detector: BadgeDetector | None = None,
            classifier=None, calibration: WeakeningCalibration | None = None,
            source: str = "corpus", cache_dir: Path | str | None = None,
            progress=None) -> list[FrameInfo]:
    """Collect per-frame ranking features over every PNG, read-only.

    Fast analysis mode: the expensive scan is cached per frame under ``cache_dir``
    (keyed by frame content + detector/classifier signature), so re-runs and
    resume-after-interrupt reuse completed frames instead of recomputing. Each
    frame is written to the cache immediately (a checkpoint), and ``progress`` — a
    callable ``(done, total, file, cached, elapsed)`` — is invoked per frame."""
    import cv2
    import numpy as np

    frames_dir = Path(frames_dir)
    detector = detector or BadgeDetector()
    sig = _detector_signature(detector, classifier)
    cache = Path(cache_dir) if cache_dir is not None else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    paths = sorted(frames_dir.glob("*.png"))
    infos: list[FrameInfo] = []
    t0 = time.perf_counter()
    for i, p in enumerate(paths, 1):
        core = None
        cache_file = None
        if cache is not None:
            cache_file = cache / f"{_frame_hash(p)}_{sig}.json"
            if cache_file.exists():
                try:
                    core = json.loads(cache_file.read_text())
                except (json.JSONDecodeError, OSError):
                    core = None
        cached = core is not None
        if not cached:
            img = cv2.imread(str(p))
            if img is None:
                continue
            geo = CaptureGeometry(raw_w=img.shape[1], raw_h=img.shape[0])
            core = _frame_core(img, derive_rois(geo, calibration), detector, classifier)
            if cache_file is not None:  # checkpoint immediately
                tmp = cache_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(core))
                tmp.replace(cache_file)
        infos.append(FrameInfo(
            file=p.name, source_path=p, source=source, world=_world_from_name(p.name),
            width=core["width"], height=core["height"],
            descriptor=np.asarray(core["descriptor"], dtype="float32"),
            bg=np.asarray(core["bg"], dtype="float64"),  # match the original mean() precision
            counts=core["counts"], factors=dict(core["factors_abs"]),
        ))
        if progress is not None:
            progress(i, len(paths), p.name, cached, time.perf_counter() - t0)
    _finalize_corpus_factors(infos)
    return infos


def _finalize_corpus_factors(infos: list[FrameInfo]) -> None:
    """Add corpus-relative factors (rare background, rare scale) once every frame
    is measured."""
    import numpy as np

    if not infos:
        return
    bgs = np.array([f.bg for f in infos])
    median_bg = np.median(bgs, axis=0)
    res_counts: dict[tuple, int] = {}
    for f in infos:
        res_counts[(f.width, f.height)] = res_counts.get((f.width, f.height), 0) + 1
    n = len(infos)
    for f in infos:
        f.factors["rare_background"] = float(np.linalg.norm(f.bg - median_bg))
        f.factors["rare_scale"] = n / res_counts[(f.width, f.height)]  # >1 = rarer


# Weights emphasise "we cannot read it yet" and "the model is unsure / stages
# disagree", then rarity. Diversity is handled by clustering, not these weights.
_WEIGHTS = {
    "unknown_pct": 3.0,
    "uncertain": 2.5,
    "stage_disagree": 2.0,
    "near_thresh_reject": 1.5,
    "competing": 1.0,
    "rejected": 0.6,
    "candidates": 0.4,
    "rare_background": 1.5,
    "rare_scale": 2.0,
}

_REASON_TEXT = {
    "unknown_pct": "unknown percentage(s) — detected badge the classifier could not read",
    "uncertain": "uncertain classifier — similarity near the accept bar / close top-2 classes",
    "stage_disagree": "detector-stage disagreement — colour prior fires but template rejects",
    "near_thresh_reject": "near-threshold rejects — candidates just under the accept bar (possible FP/FN)",
    "competing": "multiple competing accepted candidates",
    "rejected": "high rejected-candidate count",
    "candidates": "high stage-1 candidate count",
    "rare_background": "rare background — battle-map colour far from the corpus norm",
    "rare_scale": "unusual capture scale/resolution (under-represented)",
}


def _score(infos: list[FrameInfo]) -> None:
    """Min-max normalise each factor across the corpus, weight, and sum; record
    the top contributing reasons per frame."""
    keys = list(_WEIGHTS)
    ranges = {}
    for k in keys:
        vals = [f.factors.get(k, 0.0) for f in infos]
        lo, hi = min(vals), max(vals)
        ranges[k] = (lo, hi if hi > lo else lo + 1.0)
    for f in infos:
        contrib = {}
        for k in keys:
            lo, hi = ranges[k]
            norm = (f.factors.get(k, 0.0) - lo) / (hi - lo)
            contrib[k] = _WEIGHTS[k] * norm
        f.score = round(sum(contrib.values()), 4)
        top = sorted(contrib.items(), key=lambda kv: -kv[1])
        f.reasons = [_REASON_TEXT[k] for k, v in top if v > 1e-9][:3]
        if not f.reasons:
            f.reasons = ["baseline — no strong signal (kept only for coverage)"]


def cluster(infos: list[FrameInfo], *, dup_sim: float = _DUP_SIM) -> int:
    """Group near-duplicates: union frames whose perceptual cosine >= `dup_sim`.
    Returns the number of clusters. Assigns `cluster` on each FrameInfo."""
    parent = list(range(len(infos)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)

    for i in range(len(infos)):
        for j in range(i + 1, len(infos)):
            sim = float((infos[i].descriptor * infos[j].descriptor).sum())
            if sim >= dup_sim:
                union(i, j)
    roots = {}
    for i, f in enumerate(infos):
        r = find(i)
        f.cluster = roots.setdefault(r, len(roots))
    return len(roots)


def select_batch(infos: list[FrameInfo], *, n: int = 50, per_cluster_cap: int | None = None
                 ) -> list[FrameInfo]:
    """Diversity-aware selection — NOT the top-N by score.

    Frames are grouped by cluster; within each cluster they are ranked by score.
    We then take frames round-robin from clusters ordered by their best score,
    respecting a per-cluster cap, so near-duplicates cannot dominate the batch."""
    _score(infos)
    by_cluster: dict[int, list[FrameInfo]] = {}
    for f in infos:
        by_cluster.setdefault(f.cluster, []).append(f)
    for frames in by_cluster.values():
        frames.sort(key=lambda f: -f.score)
    num_clusters = len(by_cluster)
    if per_cluster_cap is None:
        # Allow a cluster at most its fair share (rounded up) of the batch.
        per_cluster_cap = max(1, -(-n // max(1, num_clusters)))
    order = sorted(by_cluster.values(), key=lambda fs: -fs[0].score)

    picked: list[FrameInfo] = []
    taken = {cid: 0 for cid in by_cluster}
    progressed = True
    while len(picked) < n and progressed:
        progressed = False
        for frames in order:
            cid = frames[0].cluster
            if taken[cid] >= min(per_cluster_cap, len(frames)):
                continue
            picked.append(frames[taken[cid]])
            taken[cid] += 1
            progressed = True
            if len(picked) >= n:
                break
    picked.sort(key=lambda f: -f.score)
    return picked


def _default_progress(done, total, file, cached, elapsed):
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    tag = "cache" if cached else "scan "
    print(f"[{done:>4}/{total}] {tag} {file:<40} {elapsed:6.1f}s elapsed, ETA {eta:5.0f}s",
          flush=True)


def build_review_batch(sources, out_dir: Path | str, *, n: int = 50,
                       classifier=None, cache_dir: Path | str | None = None,
                       progress="default") -> dict:
    """Analyse every source, select a diverse high-gain batch, and write a
    Review-Mode-ready folder: ``frames/`` + ``labels.json`` (unreviewed) +
    ``calibration.json`` (merged) + ``manifest.json`` + ``REVIEW_BATCH.md``.

    `sources` is an iterable of ``(frames_dir, calibration_path, tag)``. The
    detector/classifier/thresholds are used read-only and never modified.

    The expensive scan is cached per frame under ``cache_dir`` (default
    ``out_dir/.cache``): the first pass checkpoints every frame, so a re-run or a
    resume-after-interrupt reuses completed work. Pass ``progress=None`` to
    silence per-frame reporting.
    """
    out = Path(out_dir)
    frames_out = out / "frames"
    frames_out.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(cache_dir) if cache_dir is not None else out / ".cache"
    prog = _default_progress if progress == "default" else progress

    merged_cal = WeakeningCalibration()
    all_infos: list[FrameInfo] = []
    for frames_dir, calib_path, tag in sources:
        cal = WeakeningCalibration.load(calib_path) if calib_path and Path(calib_path).exists() else None
        if cal is not None:
            _merge_calibration(merged_cal, cal)
        all_infos.extend(analyze(frames_dir, classifier=classifier, calibration=cal,
                                 source=tag, cache_dir=cache_dir, progress=prog))

    n_clusters = cluster(all_infos)
    picked = select_batch(all_infos, n=n)

    # Copy selected frames + build a Review-Mode label store (unreviewed).
    label_frames = []
    for f in picked:
        shutil.copy2(f.source_path, frames_out / f.file)
        label_frames.append({"file": f.file, "badges": [], "reviewed": False})
    (out / "labels.json").write_text(
        json.dumps({"version": 1, "frames": label_frames}, indent=2), encoding="utf-8")
    merged_cal._path = out / "calibration.json"
    merged_cal.save()

    manifest = {
        "corpus_frames": len(all_infos),
        "clusters": n_clusters,
        "requested": n,
        "selected": len(picked),
        "weights": _WEIGHTS,
        "method": "read-only pipeline features -> min-max weighted info-gain, "
                  "perceptual near-duplicate clustering, diversity-capped round-robin selection",
        "note": ("The committed screenshot corpus is smaller than the requested batch "
                 "size; the batch contains every diversity-selected frame available. "
                 "Re-run against a larger keep dataset to fill a full batch."
                 if len(picked) < n else ""),
        "frames": [_manifest_row(f) for f in picked],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "REVIEW_BATCH.md").write_text(_review_md(manifest, picked), encoding="utf-8")
    return manifest


def _merge_calibration(dst: WeakeningCalibration, src: WeakeningCalibration) -> None:
    dst._regions.update(src._regions)
    dst._battle_map.update(src._battle_map)
    dst._geometry.update(src._geometry)


def _manifest_row(f: FrameInfo) -> dict:
    return {
        "file": f.file, "source": f.source, "world": f.world,
        "resolution": f"{f.width}x{f.height}", "cluster": f.cluster,
        "score": f.score, "reasons": f.reasons,
        "detector": f.counts,
        "factors": {k: round(float(v), 3) for k, v in f.factors.items()},
    }


def _review_md(manifest: dict, picked: list[FrameInfo]) -> str:
    lines = [
        "# Review batch 001 — active-learning selection (observe-only, no retrain)",
        "",
        f"Corpus analysed: **{manifest['corpus_frames']}** screenshots · "
        f"clusters: **{manifest['clusters']}** · requested: **{manifest['requested']}** · "
        f"selected: **{manifest['selected']}**.",
        "",
        "The detector, classifier, and thresholds were used **read-only** — nothing "
        "was modified or retrained. Selection maximises expected information gain "
        "while capping near-duplicate clusters (it is deliberately NOT the top-N by "
        "uncertainty).",
        "",
    ]
    if manifest.get("note"):
        lines += [f"> **Note:** {manifest['note']}", ""]
    lines += [
        "## How to review",
        "",
        "Open this folder in the existing Review Mode and label each frame "
        "(left-click add, right-click remove, keys 1-5 set 20/40/60/80/100, autosave):",
        "",
        "```",
        "python -m bap.gui.forge_review tests/forge_assets/review_batch_001/frames \\",
        "    --labels tests/forge_assets/review_batch_001/labels.json \\",
        "    --calibration tests/forge_assets/review_batch_001/calibration.json",
        "```",
        "",
        "## Scoring factors (weights)",
        "",
    ]
    for k, w in manifest["weights"].items():
        lines.append(f"- **{k}** ({w}) — {_REASON_TEXT[k]}")
    lines += ["", "## Selected frames — why each was chosen", "",
              "| # | frame | source | world | res | cluster | score | detector (cand/conf/rej/acc/unk) | why |",
              "|---|---|---|---|---|---|---|---|---|"]
    for i, f in enumerate(picked, 1):
        c = f.counts
        det = (f"{c['stage1_candidates']}/{c['template_confirmed']}/{c['rejected']}/"
               f"{c['final_detections']}/{c['percentage_unknown']}")
        lines.append(f"| {i} | {f.file} | {f.source} | {f.world or '—'} | {f.width}x{f.height} "
                     f"| {f.cluster} | {f.score} | {det} | {'; '.join(f.reasons)} |")
    lines.append("")
    lines.append("Regenerate against a larger dataset: "
                 "`python -m bap.forge.detection.active_learning <frames_dir> "
                 "--n 50 --out <batch_dir>`.")
    return "\n".join(lines)


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="forge-active-learning")
    parser.add_argument("frames_dir")
    parser.add_argument("--calibration", default=None)
    parser.add_argument("--tag", default="corpus")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--out", default="tests/forge_assets/review_batch_001")
    parser.add_argument("--cache-dir", default=None,
                        help="per-frame cache/checkpoint dir (default: <out>/.cache). "
                             "Re-running reuses it and resumes after an interrupt.")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)
    t0 = time.perf_counter()
    manifest = build_review_batch(
        [(args.frames_dir, args.calibration, args.tag)], args.out, n=args.n,
        cache_dir=args.cache_dir, progress=(None if args.no_progress else "default"))
    print(f"selected {manifest['selected']}/{manifest['requested']} "
          f"from {manifest['corpus_frames']} frames in {time.perf_counter() - t0:.1f}s "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["FrameInfo", "analyze", "cluster", "select_batch", "build_review_batch"]
