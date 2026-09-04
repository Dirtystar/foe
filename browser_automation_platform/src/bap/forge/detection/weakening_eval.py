"""Weakening-reader spike: OCR-whitelist vs deterministic digit templates.

Evaluates both readers against the reviewed weakening ground truth, on the
per-frame regions in ``weakening_regions.json`` (produced by the auto-locator or,
in production, the user's calibration). Reports exact-read accuracy and mean
confidence for each method. Digit templates for the template reader are built
leave-one-frame-out so a frame is never read with a glyph cut from itself.

Kept separate from badge classification — this is the attrition-counter reader.

The grading frames are independent snapshots from different Worlds and unrelated
moments, so this evaluates PER-FRAME reading accuracy only. It applies no
temporal, monotonicity, or downward-jump logic — that lives in the runtime
`WeakeningTracker`, per World.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bap.core.domain.models import Rect
from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.detection.weakening import build_digit_templates, read_ocr, read_template
from bap.forge.labeling.model import LabelStore


@dataclass
class MethodResult:
    method: str
    total: int = 0
    correct: int = 0
    confidences: list[float] = field(default_factory=list)
    per_frame: list[tuple] = field(default_factory=list)  # (file, gt, read, ok, conf)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def mean_confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0


@dataclass
class WeakeningSpikeReport:
    n_samples: int = 0
    ocr: MethodResult = field(default_factory=lambda: MethodResult("ocr"))
    template: MethodResult = field(default_factory=lambda: MethodResult("template"))
    # Diagnosis: OCR accuracy when the region is aligned per frame, and how many
    # of the calibrated-region failures are region/layout drift vs genuine OCR.
    ocr_aligned_correct: int = 0
    drift_failures: list = field(default_factory=list)   # (file, gt, got, shift)
    ocr_failures: list = field(default_factory=list)     # (file, gt, got)
    note: str = ""

    def format(self) -> str:
        if self.n_samples == 0:
            return "No weakening ground-truth samples (set values + regions first)."
        lines = [f"Weakening reader spike: {self.n_samples} reviewed samples "
                 "(corrected calibration)"]
        for m in (self.ocr, self.template):
            lines.append(
                f"  {m.method:<9}: exact {m.accuracy:.1%} ({m.correct}/{m.total})  "
                f"mean confidence {m.mean_confidence:.2f}"
            )
        aligned_acc = self.ocr_aligned_correct / self.n_samples if self.n_samples else 0.0
        lines.append(f"  ocr (aligned per frame): exact {aligned_acc:.1%} "
                     f"({self.ocr_aligned_correct}/{self.n_samples})")
        lines.append(f"  Failure attribution: {len(self.drift_failures)} region/layout drift, "
                     f"{len(self.ocr_failures)} genuine OCR")
        if self.drift_failures:
            lines.append("   drift (a small shift reads it correctly):")
            lines += [f"     {fn} gt={gt} got={got} fixed-by-shift {sh}"
                      for fn, gt, got, sh in self.drift_failures]
        if self.ocr_failures:
            lines.append("   genuine OCR errors (no shift helps):")
            lines += [f"     {fn} gt={gt} got={got}" for fn, gt, got in self.ocr_failures]
        if self.note:
            lines.append(f"  Note: {self.note}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "samples": self.n_samples,
            "ocr_calibrated_accuracy": round(self.ocr.accuracy, 4),
            "ocr_aligned_accuracy": round(self.ocr_aligned_correct / self.n_samples, 4) if self.n_samples else 0.0,
            "template_accuracy": round(self.template.accuracy, 4),
            "failures_region_drift": len(self.drift_failures),
            "failures_ocr": len(self.ocr_failures),
        }


def _aligned_region(img, base: Rect, gt: int) -> tuple[Rect, tuple | None]:
    """Search a small window around the calibrated region for a shift whose OCR
    equals the ground truth. Returns (region, shift) — shift is None if the base
    region already reads correctly or nothing nearby helps. Used only for
    failure attribution and the 'given a correct region' number; the production
    reader never auto-searches (that would risk reading a different field)."""
    if read_ocr(img, base).value == gt:
        return base, (0, 0)
    for dx in range(-18, 5, 2):
        for dy in range(-6, 7, 2):
            r = Rect(base.x + dx, base.y + dy, base.w, base.h)
            if read_ocr(img, r).value == gt:
                return r, (dx, dy)
    return base, None


def run(frames_dir: Path | str, labels_path: Path | str,
        calibration_path: Path | str) -> WeakeningSpikeReport:
    """Evaluate both readers at the user's corrected per-resolution calibration,
    and attribute each failure to region/layout drift vs genuine OCR error."""
    import cv2

    frames_dir = Path(frames_dir)
    store = LabelStore.load(labels_path)
    cal = WeakeningCalibration.load(calibration_path)
    report = WeakeningSpikeReport(
        note="single per-resolution calibration; grading frames come from several "
             "capture sessions, so some sit at a different top-bar position"
    )

    samples = []  # (file, img, rect, gt)
    for name in store.files():
        fl = store.get(name)
        if fl is None or not fl.reviewed or fl.weakening is None:
            continue
        img = cv2.imread(str(frames_dir / name))
        if img is None:
            continue
        rect = cal.get(img.shape[1], img.shape[0])
        if rect is None:
            continue
        samples.append((name, img, rect, fl.weakening))
    report.n_samples = len(samples)
    if not samples:
        return report

    # Per-frame aligned regions (for the reader-quality number + LOO glyphs).
    aligned = {name: _aligned_region(img, rect, gt) for (name, img, rect, gt) in samples}

    for name, img, rect, gt in samples:
        others = [(cv2.imread(str(frames_dir / n))[a.y:a.y + a.h, a.x:a.x + a.w], g)
                  for (n, _im, _r, g) in samples for (a, _s) in [aligned[n]] if n != name]
        digit_templates = build_digit_templates(others)

        o = read_ocr(img, rect)
        t = read_template(img, rect, digit_templates)
        for res, m in ((o, report.ocr), (t, report.template)):
            m.total += 1
            ok = res.value == gt
            m.correct += int(ok)
            m.confidences.append(res.confidence)
            m.per_frame.append((name, gt, res.value, ok, round(res.confidence, 2)))

        a_rect, shift = aligned[name]
        a_val = read_ocr(img, a_rect).value
        if a_val == gt:
            report.ocr_aligned_correct += 1
        if o.value != gt:  # attribute the calibrated-region failure
            if shift is not None:
                report.drift_failures.append((name, gt, o.value, shift))
            else:
                report.ocr_failures.append((name, gt, o.value))
    return report


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="forge-weakening-spike")
    parser.add_argument("frames_dir", nargs="?", default="tests/forge_assets/grading/frames")
    args = parser.parse_args(argv)
    base = Path(args.frames_dir).parent
    report = run(args.frames_dir, base / "labels.json", base / "calibration.json")
    print(report.format())
    for m in (report.ocr, report.template):
        print(f"\n[{m.method}]")
        for fn, gt, rd, ok, cf in m.per_frame:
            print(f"  {fn} gt={gt} read={rd} conf={cf} {'OK' if ok else 'X'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["WeakeningSpikeReport", "MethodResult", "run"]
