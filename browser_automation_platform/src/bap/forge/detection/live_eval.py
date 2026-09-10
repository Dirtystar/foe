"""Honest, leakage-free evaluation of the Forge observe-only vision slice.

Runs three graded passes over the unified dataset (:mod:`bap.forge.detection.dataset`),
reported per source (historical / live-H / live-F / combined):

  1. **Localization** — detector over each frame's calibrated battle-map ROI,
     greedily matched to reviewed badges: precision, recall, FP/frame, miss/frame,
     centre error, and the TP vs FP template-score distributions that justify any
     threshold decision.
  2. **Classification** — percentage accuracy under **frame-grouped
     leave-one-frame-out** (a frame's badges are never classified with an exemplar
     cut from that same frame), with a confusion matrix, UNKNOWN rate, and the
     nearest-exemplar similarity distribution.
  3. **Full slice** — the whole pipeline end to end, whose key safety metric is
     the count of **wrong accepted percentages** (an accepted pct that disagrees
     with ground truth); this must be zero.

Nothing here clicks or drives a browser — it reads committed frames and labels.
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field

from bap.forge.detection.classify import PercentClassifier, percent_patch
from bap.forge.detection.dataset import Sample, battle_map_box, load_all
from bap.forge.detection.detector import BadgeDetector
from bap.forge.detection.evaluate import _match
from bap.forge.detection.scan import MIN_PCT_SIM


def _group(sample: Sample) -> str:
    if sample.source == "live":
        return f"live-{sample.world or '?'}"
    if sample.source == "review_batch_002":
        return "review_batch_002"
    return "historical"


# --------------------------------------------------------------------------- #
# 1. Localization                                                             #
# --------------------------------------------------------------------------- #

@dataclass
class LocResult:
    frames: int = 0
    truth: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    center_errors: list[float] = field(default_factory=list)
    tp_scores: list[float] = field(default_factory=list)
    fp_scores: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.truth if self.truth else 0.0

    def to_dict(self) -> dict:
        def band(xs):
            return None if not xs else {"n": len(xs), "min": round(min(xs), 2),
                                        "median": round(st.median(xs), 2), "max": round(max(xs), 2)}
        return {
            "frames": self.frames, "truth_badges": self.truth,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 3), "recall": round(self.recall, 3),
            "fp_per_frame": round(self.fp / self.frames, 2) if self.frames else 0.0,
            "miss_per_frame": round(self.fn / self.frames, 2) if self.frames else 0.0,
            "center_error_px": None if not self.center_errors else {
                "mean": round(sum(self.center_errors) / len(self.center_errors), 1),
                "median": round(st.median(self.center_errors), 1),
                "max": round(max(self.center_errors), 1)},
            "tp_scores": band(self.tp_scores), "fp_scores": band(self.fp_scores),
        }


def evaluate_localization(samples, detector: BadgeDetector, *, max_dist: float = 30.0
                          ) -> dict[str, LocResult]:
    import cv2

    groups: dict[str, LocResult] = {}
    for s in samples:
        for g in (_group(s), "combined"):
            groups.setdefault(g, LocResult())
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        res = detector.scan(img, region=battle_map_box(s))
        preds = res.detections
        truths = s.badges
        pairs, um_p, um_t = _match(preds, truths, max_dist)
        matched_pred = {pi for pi, _ti, _d in pairs}
        for g in (_group(s), "combined"):
            r = groups[g]
            r.frames += 1
            r.truth += len(truths)
            r.tp += len(pairs)
            r.fp += len(um_p)
            r.fn += len(um_t)
            for _pi, _ti, d in pairs:
                r.center_errors.append(d)
            for pi, p in enumerate(preds):
                (r.tp_scores if pi in matched_pred else r.fp_scores).append(p.confidence)
    return groups


# --------------------------------------------------------------------------- #
# 2. Classification (frame-grouped leave-one-frame-out)                       #
# --------------------------------------------------------------------------- #

@dataclass
class ClassResult:
    total: int = 0
    correct: int = 0
    unknown: int = 0
    wrong: int = 0
    sims: list[float] = field(default_factory=list)
    confusion: dict = field(default_factory=dict)   # (gt, pred) -> n
    per_class: dict = field(default_factory=dict)   # pct -> [total, correct]

    def to_dict(self) -> dict:
        return {
            "total": self.total, "correct": self.correct, "unknown": self.unknown,
            "wrong_accepted": self.wrong,
            "accuracy": round(self.correct / self.total, 3) if self.total else 0.0,
            "unknown_rate": round(self.unknown / self.total, 3) if self.total else 0.0,
            "similarity": None if not self.sims else {
                "min": round(min(self.sims), 2), "median": round(st.median(self.sims), 2),
                "max": round(max(self.sims), 2)},
            "per_class": {str(k): {"total": v[0], "correct": v[1]} for k, v in sorted(self.per_class.items())},
            "confusion": {f"{gt}->{pr}": n for (gt, pr), n in sorted(self.confusion.items())},
        }


def _bank(samples):
    """(patch, pct, frame_key) for every classified GT badge in `samples`."""
    import cv2

    out = []
    for s in samples:
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        for b in s.badges:
            if b.pct is not None:
                out.append((percent_patch(img, b.cx, b.cy), b.pct, s.key))
    return out


def evaluate_classification(samples, *, min_sim: float = MIN_PCT_SIM) -> dict[str, ClassResult]:
    import cv2

    bank = _bank(samples)
    groups: dict[str, ClassResult] = {}
    for s in samples:
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        for b in s.badges:
            if b.pct is None:
                continue
            # Frame-grouped LOFO: drop every exemplar from THIS frame.
            clf = PercentClassifier().fit([(v, p) for (v, p, k) in bank if k != s.key and v is not None])
            patch = percent_patch(img, b.cx, b.cy)
            guess, sim = clf.predict(patch)
            accepted = guess is not None and sim >= min_sim and clf.confirmed(patch)
            for g in (_group(s), "combined"):
                r = groups.setdefault(g, ClassResult())
                r.total += 1
                r.sims.append(float(sim))
                pc = r.per_class.setdefault(b.pct, [0, 0])
                pc[0] += 1
                if not accepted:
                    r.unknown += 1
                elif guess == b.pct:
                    r.correct += 1
                    pc[1] += 1
                else:
                    r.wrong += 1
                    r.confusion[(b.pct, guess)] = r.confusion.get((b.pct, guess), 0) + 1
    return groups


# --------------------------------------------------------------------------- #
# 3. Full observe-only slice                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class SliceResult:
    frames: int = 0
    truth: int = 0
    correct_detections: int = 0
    missed_detections: int = 0
    false_positives: int = 0
    correct_pct: int = 0
    unknown_pct: int = 0
    wrong_accepted_pct: int = 0   # THE safety metric — must be 0

    def to_dict(self) -> dict:
        return {
            "frames": self.frames, "truth_badges": self.truth,
            "correct_detections": self.correct_detections,
            "missed_detections": self.missed_detections,
            "false_positives": self.false_positives,
            "correct_pct": self.correct_pct, "unknown_pct": self.unknown_pct,
            "wrong_accepted_pct": self.wrong_accepted_pct,
        }


def evaluate_full_slice(samples, *, detector: BadgeDetector, min_sim: float = MIN_PCT_SIM,
                        max_dist: float = 30.0) -> dict[str, SliceResult]:
    """End-to-end per frame with a frame-grouped-LOFO classifier, counting the
    wrong-accepted-percentage safety metric on matched true-positive badges."""
    import cv2

    bank = _bank(samples)
    groups: dict[str, SliceResult] = {}
    for s in samples:
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        clf = PercentClassifier().fit([(v, p) for (v, p, k) in bank if k != s.key and v is not None])
        preds = detector.scan(img, region=battle_map_box(s)).detections
        pairs, um_p, um_t = _match(preds, s.badges, max_dist)
        for g in (_group(s), "combined"):
            r = groups.setdefault(g, SliceResult())
            r.frames += 1
            r.truth += len(s.badges)
            r.correct_detections += len(pairs)
            r.missed_detections += len(um_t)
            r.false_positives += len(um_p)
            for pi, ti, _d in pairs:
                gt = s.badges[ti].pct
                patch = percent_patch(img, preds[pi].cx, preds[pi].cy)
                guess, sim = clf.predict(patch)
                if guess is None or sim < min_sim or not clf.confirmed(patch):
                    r.unknown_pct += 1
                elif gt is not None and guess == gt:
                    r.correct_pct += 1
                elif gt is not None:
                    r.wrong_accepted_pct += 1
    return groups


# --------------------------------------------------------------------------- #
# Top-level report                                                            #
# --------------------------------------------------------------------------- #

def run(detector: BadgeDetector | None = None, *, min_sim: float = MIN_PCT_SIM) -> dict:
    samples = load_all()
    detector = detector or BadgeDetector()
    sources = sorted({s.source for s in samples})
    counts = {"frames": len(samples), "badges": sum(len(s.badges) for s in samples)}
    for src in sources:
        counts[f"{src}_frames"] = sum(1 for s in samples if s.source == src)
        counts[f"{src}_badges"] = sum(len(s.badges) for s in samples if s.source == src)
    return {
        "counts": counts,
        "localization": {g: r.to_dict() for g, r in evaluate_localization(samples, detector).items()},
        "classification": {g: r.to_dict() for g, r in evaluate_classification(samples, min_sim=min_sim).items()},
        "full_slice": {g: r.to_dict() for g, r in
                       evaluate_full_slice(samples, detector=detector, min_sim=min_sim).items()},
    }


def _main(argv=None) -> int:
    import json

    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "evaluate_localization", "evaluate_classification", "evaluate_full_slice", "run",
    "LocResult", "ClassResult", "SliceResult",
]
