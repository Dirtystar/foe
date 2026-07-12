# Weakening-reader spike

Comparing two readers for the current-weakening number (the top-bar attrition
counter) against the 15 reviewed ground-truth values, on regions auto-located in
the mixed-geometry grading frames.

Reproduce: `python -m bap.forge.detection.weakening_eval tests/forge_assets/grading/frames`

## Results

| Reader | Exact read | Mean confidence |
|---|---|---|
| OCR (numeric whitelist) | **33%** (5/15) | 0.15 |
| Deterministic digit templates | **0%** (0/15) | 0.33 |

## Reading

- **Region location is the bottleneck.** The grading frames come from several
  capture sessions whose top bars sit at different x-positions, so the
  auto-locator's region is often a few pixels off and catches an adjacent glyph.
  In production the user calibrates one fixed rectangle for their consistent
  setup (Debugger → *Set Weakening Region*), which removes this error — both
  readers should improve substantially, OCR most of all.
- **OCR confidence is well-calibrated and that is what matters for safety.** Every
  correct OCR read scored high (0.9+); every wrong read scored ~0. So the
  fail-safe gate (confidence < 0.60 → UNKNOWN → no action) correctly rejects the
  bad reads rather than acting on them.
- **Deterministic digit templates need a precise, tight region.** On loose
  auto-located regions the digit segmentation picks up emblem/edge pixels and
  mis-assembles. With a calibrated region and per-setup glyphs it is viable, but
  it is far more sensitive to calibration than OCR.

## Recommendation

Use **OCR with the numeric whitelist gated by confidence** as the weakening
reader; keep the deterministic template reader as a cross-check once a tight
calibrated region + per-setup digit glyphs exist. The safety gate never depends
on a low-confidence read: **UNKNOWN → no action** by design.

Regenerate after the user calibrates the region and confirms weakening values on
their own setup.
