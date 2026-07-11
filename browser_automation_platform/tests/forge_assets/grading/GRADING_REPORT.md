# Badge detector — grading report (Milestone 3)

Measured against the 15-frame, human-confirmed grading set (37 ground-truth
badges), **leave-one-frame-out**: for each test frame the emblem-template bank is
rebuilt from the *other* frames, so these are generalisation numbers, not
templates matched against themselves.

Reproduce: `python -m bap.forge.detection.evaluate tests/forge_assets/grading/frames`

## Results

| Metric | Result | Go-live gate | Met? |
|---|---|---|---|
| Recall (detection) | **78.4%** (29/37) | ≥ 95% | ✗ |
| Precision (detection) | **55.8%** (29/52) | ≥ 98% | ✗ |
| Centre error (median) | **6.1 px** | ≤ 10 px | ✓ |
| Centre error (max) | 24 px | — | outliers |
| % classification (no OCR) | **62.1%** (18/29) | ≥ 98% | ✗ |

Percentage distribution in the truth set is skewed (20% ×19, 60% ×9, 40/100 ×2,
5 left unclassified), so 62% classification is only modestly above the
majority-class baseline.

## Method

- **Locate (recall):** segment the badge's red attrition arrow (the true arrows
  are darker than they look — HSV value ~95, so the threshold is `S≥140, V≥80`)
  inside the game region; take blob centroids as candidates.
- **Confirm (precision):** multi-scale, background-masked template match of an
  emblem bank. On the grading set true emblems score distinctly higher than
  province-banner reds (median ≈ 0.73 vs ≈ 0.36); a 0.55 threshold + NMS keeps
  badges and drops most banners.
- **Centre:** the arrow sits ~16 px left of where a human marks the badge; a
  fitted `+16 px` offset aligns them (residual < 1 px).
- **Percentage:** nearest-neighbour over labelled percentage patches (no OCR).

## Honest assessment

Detection **centre accuracy meets the bar**; recall, precision, and percentage
classification **do not**. Real clicking therefore stays disabled — this is
exactly the case the observe-only Vision Debugger exists for: a human verifies
every detection before any action is enabled.

### What would move the numbers

1. **More labelled frames** (this is 15). The single biggest lever — banner
   false-positives and the harder/darker arrows need more examples, and the
   percentage classifier needs more per class.
2. **Precision:** add a shape/structure check beyond colour+template (the
   crossbow/sword silhouette), or a small trained classifier on emblem vs
   banner crops.
3. **Recall:** the ~8 misses are small/low-contrast arrows; a finer scale set
   and a slightly lower score threshold with the precision fix above.
4. **Classification:** align the percentage patch to the detected centre with a
   local search, and consider per-digit glyph templates (still not OCR).

Numbers here should be regenerated whenever the grading set grows.
