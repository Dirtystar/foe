"""Weakening-reader spike: OCR-whitelist vs deterministic digit templates.

Evaluates both readers against the reviewed weakening ground truth, on the
per-frame regions in ``weakening_regions.json`` (produced by the auto-locator or,
in production, the user's calibration). Reports exact-read accuracy and mean
confidence for each method. Digit templates for the template reader are built
leave-one-frame-out so a frame is never read with a glyph cut from itself.

Kept separate from badge classification — this is the attrition-counter reader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bap.core.domain.models import Rect
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
    note: str = ""

    def format(self) -> str:
        if self.n_samples == 0:
            return "No weakening ground-truth samples (set values + regions first)."
        lines = [f"Weakening reader spike: {self.n_samples} reviewed samples"]
        for m in (self.ocr, self.template):
            lines.append(
                f"  {m.method:<9}: exact {m.accuracy:.1%} ({m.correct}/{m.total})  "
                f"mean confidence {m.mean_confidence:.2f}"
            )
        if self.note:
            lines.append(f"  Note: {self.note}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "samples": self.n_samples,
            "ocr": {"accuracy": round(self.ocr.accuracy, 4), "mean_confidence": round(self.ocr.mean_confidence, 4)},
            "template": {"accuracy": round(self.template.accuracy, 4), "mean_confidence": round(self.template.mean_confidence, 4)},
        }


def _load_regions(path: Path) -> dict[str, Rect]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for fn, r in (data or {}).get("regions", {}).items():
        if r:
            out[fn] = Rect(x=r[0], y=r[1], w=r[2], h=r[3])
    return out


def run(frames_dir: Path | str, labels_path: Path | str, regions_path: Path | str) -> WeakeningSpikeReport:
    import cv2

    frames_dir = Path(frames_dir)
    store = LabelStore.load(labels_path)
    regions = _load_regions(Path(regions_path))
    report = WeakeningSpikeReport(note="regions auto-located on mixed-geometry frames; "
                                       "a single-setup calibration will be cleaner")

    samples = []  # (file, img, rect, gt)
    for name in store.files():
        fl = store.get(name)
        if fl is None or not fl.reviewed or fl.weakening is None or name not in regions:
            continue
        img = cv2.imread(str(frames_dir / name))
        if img is None:
            continue
        samples.append((name, img, regions[name], fl.weakening))
    report.n_samples = len(samples)
    if not samples:
        return report

    for name, img, rect, gt in samples:
        # LOO digit templates from the other samples.
        others = [(cv2.imread(str(frames_dir / n))[r.y:r.y + r.h, r.x:r.x + r.w], g)
                  for (n, _im, r, g) in samples if n != name]
        digit_templates = build_digit_templates(others)

        o = read_ocr(img, rect)
        t = read_template(img, rect, digit_templates)
        for res, m in ((o, report.ocr), (t, report.template)):
            m.total += 1
            ok = res.value == gt
            m.correct += int(ok)
            m.confidences.append(res.confidence)
            m.per_frame.append((name, gt, res.value, ok, round(res.confidence, 2)))
    return report


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="forge-weakening-spike")
    parser.add_argument("frames_dir", nargs="?", default="tests/forge_assets/grading/frames")
    args = parser.parse_args(argv)
    base = Path(args.frames_dir).parent
    report = run(args.frames_dir, base / "labels.json", base / "weakening_regions.json")
    print(report.format())
    for m in (report.ocr, report.template):
        print(f"\n[{m.method}]")
        for fn, gt, rd, ok, cf in m.per_frame:
            print(f"  {fn} gt={gt} read={rd} conf={cf} {'OK' if ok else 'X'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["WeakeningSpikeReport", "MethodResult", "run"]
