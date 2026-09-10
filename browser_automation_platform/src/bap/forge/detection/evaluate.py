"""Grade the detector against the human-confirmed grading set.

Matches predicted badges to reviewed ground-truth badges by nearest centre
(greedy, within a tolerance), then reports the agreed metrics:

  - recall / precision of badge detection,
  - centre error (px) on matched pairs — raw and after removing a fitted
    systematic offset (so calibration is separated from jitter),
  - percentage-classification accuracy on true positives, graded leave-one-out
    so a badge is never classified using itself.

Only frames marked `reviewed` count. With no reviewed frames it reports exactly
that — never fabricated numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bap.forge.detection.classify import PercentClassifier, percent_patch
from bap.forge.detection.detector import BadgeDetector, Detection, build_templates_from_labels
from bap.forge.labeling.model import LabelStore


@dataclass
class FrameResult:
    file: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    center_errors: list[float] = field(default_factory=list)


@dataclass
class EvalReport:
    n_frames: int = 0
    n_reviewed: int = 0
    truth_badges: int = 0
    predicted: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    center_errors: list[float] = field(default_factory=list)
    fitted_offset: tuple[float, float] = (0.0, 0.0)
    calibrated_errors: list[float] = field(default_factory=list)
    class_total: int = 0
    class_correct: int = 0
    per_frame: list[FrameResult] = field(default_factory=list)
    note: str = ""

    @property
    def recall(self) -> float:
        return self.tp / self.truth_badges if self.truth_badges else 0.0

    @property
    def precision(self) -> float:
        return self.tp / self.predicted if self.predicted else 0.0

    @property
    def classification_accuracy(self) -> float:
        return self.class_correct / self.class_total if self.class_total else 0.0

    @staticmethod
    def _stats(errors: list[float]) -> dict:
        if not errors:
            return {"mean": None, "median": None, "max": None}
        s = sorted(errors)
        mean = sum(s) / len(s)
        median = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
        return {"mean": round(mean, 2), "median": round(median, 2), "max": round(max(s), 2)}

    def format(self) -> str:
        if self.n_reviewed == 0:
            return (f"No reviewed frames in the grading set ({self.n_frames} present). "
                    "Confirm labels with the labelling tool before grading.")
        raw = self._stats(self.center_errors)
        cal = self._stats(self.calibrated_errors)
        lines = [
            f"Grading: {self.n_reviewed}/{self.n_frames} frames reviewed, "
            f"{self.truth_badges} ground-truth badges",
            f"  Detection : recall {self.recall:.1%} ({self.tp}/{self.truth_badges})  "
            f"precision {self.precision:.1%} ({self.tp}/{self.predicted})  FP {self.fp}",
            f"  Centre err: raw mean {raw['mean']}px median {raw['median']}px max {raw['max']}px",
            f"              calibrated (offset {self.fitted_offset}) "
            f"mean {cal['mean']}px median {cal['median']}px max {cal['max']}px",
            f"  Class acc : {self.classification_accuracy:.1%} "
            f"({self.class_correct}/{self.class_total}) leave-one-out, no OCR",
        ]
        if self.note:
            lines.append(f"  Note: {self.note}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "frames": self.n_frames, "reviewed": self.n_reviewed,
            "truth_badges": self.truth_badges, "predicted": self.predicted,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "recall": round(self.recall, 4), "precision": round(self.precision, 4),
            "center_error_raw": self._stats(self.center_errors),
            "fitted_offset": [round(v, 2) for v in self.fitted_offset],
            "center_error_calibrated": self._stats(self.calibrated_errors),
            "classification_accuracy": round(self.classification_accuracy, 4),
            "classification": {"correct": self.class_correct, "total": self.class_total},
        }


def _match(preds: list[Detection], truths: list, max_dist: float):
    """Greedy nearest-centre matching. Returns (pairs, unmatched_pred_idx,
    unmatched_truth_idx) where pairs is list[(pred_i, truth_i, dist)]."""
    cand = []
    for pi, p in enumerate(preds):
        for ti, t in enumerate(truths):
            d = ((p.cx - t.cx) ** 2 + (p.cy - t.cy) ** 2) ** 0.5
            if d <= max_dist:
                cand.append((d, pi, ti))
    cand.sort()
    used_p, used_t, pairs = set(), set(), []
    for d, pi, ti in cand:
        if pi in used_p or ti in used_t:
            continue
        used_p.add(pi)
        used_t.add(ti)
        pairs.append((pi, ti, d))
    unmatched_p = [i for i in range(len(preds)) if i not in used_p]
    unmatched_t = [i for i in range(len(truths)) if i not in used_t]
    return pairs, unmatched_p, unmatched_t


def evaluate(detector: BadgeDetector, frames_dir: Path | str, labels_path: Path | str,
             *, max_dist: float = 25.0, lofo: bool = False, detector_kwargs: dict | None = None
             ) -> EvalReport:
    """Grade `detector` against the reviewed grading set.

    With `lofo=True` the emblem-template bank is rebuilt per frame excluding that
    frame's own emblems (leave-one-frame-out), so the reported numbers reflect
    generalisation to unseen frames, not templates cut from the test image."""
    import cv2

    frames_dir = Path(frames_dir)
    store = LabelStore.load(labels_path)
    report = EvalReport(n_frames=len(store))
    if lofo:
        report.note = "leave-one-frame-out (per-frame emblem bank excludes the test frame)"
    dkw = detector_kwargs or {}

    def detector_for(file: str) -> BadgeDetector:
        if not lofo:
            return detector
        bank = build_templates_from_labels(frames_dir, labels_path, exclude_file=file)
        return BadgeDetector(templates=bank, **dkw)

    # Collect all truth badges (with images) once — reused for LOO classification.
    reviewed = [f for f in (store.get(name) for name in store.files()) if f and f.reviewed]
    report.n_reviewed = len(reviewed)
    if not reviewed:
        return report

    # Build the global classifier bank: (patch, pct, badge_key) for every
    # classified truth badge, so LOO can exclude the badge under test.
    bank: list[tuple[object, int, tuple]] = []
    images: dict[str, object] = {}
    for fl in reviewed:
        img = cv2.imread(str(frames_dir / fl.file))
        images[fl.file] = img
        if img is None:
            continue
        for bi, b in enumerate(fl.badges):
            if b.pct is not None:
                bank.append((percent_patch(img, b.cx, b.cy), b.pct, (fl.file, bi)))

    raw_offsets = []
    matched_records = []  # (pred_center, truth_center, file, truth_key, truth_pct)
    for fl in reviewed:
        img = images.get(fl.file)
        fr = FrameResult(file=fl.file)
        preds = detector_for(fl.file).detect(img) if img is not None else []
        report.predicted += len(preds)
        report.truth_badges += len(fl.badges)
        pairs, um_p, um_t = _match(preds, fl.badges, max_dist)
        fr.tp, fr.fp, fr.fn = len(pairs), len(um_p), len(um_t)
        for pi, ti, d in pairs:
            fr.center_errors.append(d)
            report.center_errors.append(d)
            raw_offsets.append((fl.badges[ti].cx - preds[pi].cx, fl.badges[ti].cy - preds[pi].cy))
            matched_records.append((preds[pi], fl.badges[ti], fl.file, (fl.file, ti)))
        report.tp += fr.tp
        report.fp += fr.fp
        report.fn += fr.fn
        report.per_frame.append(fr)

    # Fit a single systematic centre offset and report calibrated error.
    if raw_offsets:
        ox = sum(o[0] for o in raw_offsets) / len(raw_offsets)
        oy = sum(o[1] for o in raw_offsets) / len(raw_offsets)
        report.fitted_offset = (round(ox, 2), round(oy, 2))
        for (p, t, _f, _k) in matched_records:
            report.calibrated_errors.append(
                (((p.cx + ox) - t.cx) ** 2 + ((p.cy + oy) - t.cy) ** 2) ** 0.5
            )

    # Percentage classification on true positives, leave-one-out.
    for (pred, truth, file, key) in matched_records:
        if truth.pct is None:
            continue
        clf = PercentClassifier().fit([(v, p) for (v, p, k) in bank if k != key and v is not None])
        img = images.get(file)
        patch = percent_patch(img, pred.cx, pred.cy) if img is not None else None
        guess, _sim = clf.predict(patch)
        report.class_total += 1
        if guess == truth.pct:
            report.class_correct += 1

    return report


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="forge-grade", description="Grade the badge detector")
    from bap.forge.labeling.__main__ import default_labels_path

    parser.add_argument("frames_dir", nargs="?", default="tests/forge_assets/grading/frames")
    parser.add_argument("--labels", default=None)
    parser.add_argument("--no-lofo", action="store_true", help="use the bundled bank (leaks; for a sanity check only)")
    args = parser.parse_args(argv)
    labels = args.labels or str(default_labels_path(Path(args.frames_dir)))
    report = evaluate(BadgeDetector(), args.frames_dir, labels, lofo=not args.no_lofo)
    print(report.format())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EvalReport", "FrameResult", "evaluate"]
