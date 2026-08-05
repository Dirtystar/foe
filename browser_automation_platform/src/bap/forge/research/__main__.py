"""Reproducible percentage-classifier V2 benchmark (Milestone 5C).

    python -m bap.forge.research            # regenerate all classifier_v2/ artifacts

OBSERVE-ONLY. Trains and compares candidate percentage classifiers under a
leakage-free, frame-grouped evaluation and writes the metrics, fold manifest,
robustness curves, and live-snapshot recheck under ``classifier_v2/``. It never
clicks, never moves the cursor, and never changes production behaviour — the
production v1 classifier is imported read-only as the baseline.

The detector-based data audit (centre-offset distribution) is produced separately
by ``classifier_v2/make_audit.py`` because it runs the slow detector; this command
regenerates everything that depends only on the reviewed crops.
"""

from __future__ import annotations

import json
import statistics as st
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from bap.forge.detection.classify import PercentClassifier
from bap.forge.detection.dataset import load_all
from bap.forge.detection.scan import MIN_PCT_SIM
from bap.forge.research import classifier_bench as B

OUT = Path("classifier_v2")
LIVE_SOURCES = {"live", "snapshot"}


def _write(name, obj):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2))


def run(out_dir: Path = OUT) -> dict:
    global OUT
    OUT = out_dir
    t0 = time.time()
    samples = load_all()
    recs = B.extract_crops(samples)
    groups = B.fold_groups(samples)
    identity = {k: i for i, k in enumerate(dict.fromkeys(r.frame_key for r in recs))}

    # ---- fold manifest ----
    _write("fold_manifest.json", {
        "n_records": len(recs), "n_frames": len(set(r.frame_key for r in recs)),
        "n_fold_groups_neardup": len(set(groups.values())), "near_dup_bits": 5,
        "groups": {k: groups[k] for k in sorted(groups)},
        "group_sizes": dict(sorted(Counter(groups.values()).items())),
        "multiframe_groups": {str(g): sorted(k for k in groups if groups[k] == g)
                              for g, c in Counter(groups.values()).items() if c > 1},
        "per_class_common": dict(sorted(Counter(r.pct for r in recs).items())),
        "per_source_common": dict(sorted(Counter(r.source for r in recs).items())),
    })

    # ---- model metrics (A fixed gate; B/C Step-5 tuned safety layer) ----
    metrics = {}
    cA, psA = B.grouped_eval(B.CandidateA, recs, groups)
    metrics["A_v1_fixedcrop_cosine"] = {
        "gate": "fixed 0.70 + top-3 confirmation (production v1)",
        "combined": cA.to_dict(),
        "per_source": {s: c.to_dict() for s, c in sorted(psA.items())}}
    for name in ("B_robust_recentre_cosine", "C_logreg_numpy"):
        comb, per_src, thr = B.grouped_eval_tuned(B.CANDIDATES[name], recs, groups)
        metrics[name] = {
            "gate": "train-fold-tuned rejection threshold + confirmation (Step 5)",
            "combined": comb.to_dict(),
            "per_source": {s: c.to_dict() for s, c in sorted(per_src.items())},
            "tuned_threshold": {"min": round(min(thr), 3),
                                "median": round(st.median(thr), 3),
                                "max": round(max(thr), 3)}}
        cf, _ = B.grouped_eval(B.CANDIDATES[name], recs, groups)
        metrics[name + "_fixedgate_pre_safety"] = {"combined": cf.to_dict()}
    metrics["A_identityfolds_parity"] = {
        "combined": B.grouped_eval(B.CandidateA, recs, identity)[0].to_dict()}
    _write("model_metrics.json", metrics)

    # ---- live-snapshot recheck (models trained on all non-live data) ----
    live = [r for r in recs if r.source in LIVE_SOURCES]
    train = [r for r in recs if r.source not in LIVE_SOURCES]
    clfA = PercentClassifier().fit([(r.v1vec, r.pct) for r in train if r.v1vec is not None])
    thrB, _ = B.tune_threshold(B.CandidateB, train, groups)
    modelB = B.CandidateB().fit(train)
    thrC, _ = B.tune_threshold(B.CandidateC, train, groups)
    modelC = B.CandidateC().fit(train)
    rows = []
    for r in live:
        gA, sA = clfA.predict(r.v1vec)
        okA = gA is not None and sA >= MIN_PCT_SIM and clfA.confirmed(r.v1vec)
        gB, sB = modelB.score(r)
        gC, sC = modelC.score(r)
        rows.append({"frame": r.frame_key.split(":")[-1], "source": r.source, "gt": r.pct,
                     "v1": {"pred": gA, "conf": round(float(sA), 3), "accepted": okA},
                     "B": {"pred": gB, "conf": round(float(sB), 3), "accepted": modelB.accept(r, thrB)},
                     "C": {"pred": gC, "conf": round(float(sC), 3), "accepted": modelC.accept(r, thrC)}})
    summ = {m: {"accepted": sum(1 for x in rows if x[m]["accepted"]),
                "correct": sum(1 for x in rows if x[m]["accepted"] and x[m]["pred"] == x["gt"]),
                "wrong": sum(1 for x in rows if x[m]["accepted"] and x[m]["pred"] != x["gt"])}
            for m in ("v1", "B", "C")}
    _write("live_recheck.json", {"n_live_badges": len(rows),
                                 "thresholds": {"B": round(thrB, 3), "C": round(thrC, 3)},
                                 "summary": summ, "rows": rows})

    # ---- robustness curves (perturbed held-out crops, LOFO) ----
    _robustness(recs, groups, samples)

    # ---- performance: latency / model size / training time ----
    _performance(recs)

    dt = round(time.time() - t0, 1)
    print(f"benchmark done in {dt}s — artifacts under {OUT}/")
    for name in ("A_v1_fixedcrop_cosine", "B_robust_recentre_cosine", "C_logreg_numpy"):
        d = metrics[name]["combined"]
        print(f"  {name:28} correct={d['correct']:3} unknown={d['unknown']:3} "
              f"WRONG={d['wrong_accepted']}")
    print(f"  live recheck: v1/B/C accepted="
          f"{summ['v1']['accepted']}/{summ['B']['accepted']}/{summ['C']['accepted']} "
          f"wrong={summ['v1']['wrong']}/{summ['B']['wrong']}/{summ['C']['wrong']}")
    return {"metrics": metrics, "live": summ}


def _robustness(recs, groups, samples):
    """A@0.70 vs B@median-tuned-threshold on perturbed held-out crops (LOFO)."""
    import csv
    smap = {s.key: s for s in samples}
    imgs = {k: cv2.imread(str(smap[k].path)) for k in {r.frame_key for r in recs}}
    by_group = defaultdict(list)
    for r in recs:
        by_group[groups[r.frame_key]].append(r)
    BTHR = 0.809

    def cond(**kw):
        A = [0, 0, 0]
        Bc = [0, 0, 0]
        for held, hr in by_group.items():
            tr = [r for r in recs if groups[r.frame_key] != held]
            clfA = PercentClassifier().fit([(r.v1vec, r.pct) for r in tr if r.v1vec is not None])
            nnB = B._CosineNN(BTHR).fit([r.bvec for r in tr if r.bvec is not None],
                                        [r.pct for r in tr if r.bvec is not None])
            for r in hr:
                ctx = B.perturb_ctx(imgs[r.frame_key], r.cx, r.cy, **kw)
                if ctx is None:
                    A[2] += 1
                    Bc[2] += 1
                    continue
                vA = B.v1_from_ctx(ctx)
                gA, sA = clfA.predict(vA)
                if not (gA is not None and sA >= MIN_PCT_SIM and clfA.confirmed(vA)):
                    A[2] += 1
                elif gA == r.pct:
                    A[0] += 1
                else:
                    A[1] += 1
                vB = B.robust_norm(ctx)
                top = nnB._topk(vB) if vB is not None else []
                if not top or top[0][1] < BTHR or sum(1 for p, _ in top if p == top[0][0]) < 2:
                    Bc[2] += 1
                elif top[0][0] == r.pct:
                    Bc[0] += 1
                else:
                    Bc[1] += 1
        return {"A": {"correct": A[0], "wrong": A[1], "unknown": A[2]},
                "B": {"correct": Bc[0], "wrong": Bc[1], "unknown": Bc[2]}}

    curves = {"shift_x": {}, "shift_y": {}, "shift_diag": {}, "scale": {}, "blur": {},
              "contrast": {}, "brightness": {}}
    for d in (-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10):
        curves["shift_x"][d] = cond(dx=d)
        curves["shift_y"][d] = cond(dy=d)
        curves["shift_diag"][d] = cond(dx=d, dy=d)
    for sc in (0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.20):
        curves["scale"][sc] = cond(scale=sc)
    for bl in (0.0, 0.5, 1.0, 1.5, 2.0):
        curves["blur"][bl] = cond(blur=bl)
    for ct in (0.7, 0.85, 1.0, 1.15, 1.3):
        curves["contrast"][ct] = cond(contrast=ct)
    for br in (-30, -15, 0, 15, 30):
        curves["brightness"][br] = cond(brightness=br)
    _write("robustness_curves.json", curves)
    with (OUT / "robustness_curves.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["axis", "value", "A_correct", "A_wrong", "A_unknown",
                    "B_correct", "B_wrong", "B_unknown"])
        for axis, pts in curves.items():
            for val, v in pts.items():
                a, b = v["A"], v["B"]
                w.writerow([axis, val, a["correct"], a["wrong"], a["unknown"],
                            b["correct"], b["wrong"], b["unknown"]])


def _performance(recs):
    perf = {}
    for name, cls in B.CANDIDATES.items():
        t = time.time()
        m = cls().fit(recs)
        train_ms = (time.time() - t) * 1000
        t = time.time()
        for _ in range(5):
            for r in recs[:50]:
                m.score(r)
        lat_us = (time.time() - t) / (5 * 50) * 1e6
        if cls is B.CandidateC:
            size = int(m._W.nbytes + m._b.nbytes + m._mu.nbytes + m._sd.nbytes)
        elif cls is B.CandidateA:
            size = int(sum(e.vec.nbytes for e in m._clf._exemplars))
        else:
            size = int(sum(v.nbytes for v in m._nn._vecs))
        perf[name] = {"train_ms": round(train_ms, 1),
                      "latency_us_per_pred": round(lat_us, 1),
                      "model_bytes": size}
    _write("model_performance.json", perf)


if __name__ == "__main__":
    run()

