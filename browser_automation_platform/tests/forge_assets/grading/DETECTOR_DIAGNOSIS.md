# Detector diagnosis — Windows H/F recall & false positives (M4.5)

Observe-only. No thresholds were changed in this sprint: the numbers below are
the *justification data* the next threshold decision must be based on, not a
change already made.

Measured on the reviewed grading set with the current whole-map battle ROI
(`x0 y502 w1920 h578` at 1920×1080) and the shipped detector
(`score_threshold=0.55`).

## Stage counts the debugger now exposes

Every scan reports: `Stage-1 candidates · Template-confirmed · Rejected ·
Accepted (classified / unknown)` in the explanation, and per-candidate in
`scan.json` (full + ROI coords, colour-prior area, template score, top-5
percentage exemplars, predicted %, accepted/rejected, reason).

## 1. Missed real badges (low recall)

3 reviewed badges are missed, all on blue province banners at the top/right edge
of the map: `frame_000346 (1864,650)`, `frame_000486 (1696,517)`,
`frame_000536 (1696,525)`.

**Root cause = stage-1 colour prior, not ROI clipping / NMS / classification.**
For `frame_000536 (1696,525)` the 50×40 window around the badge contains only
**5 red pixels**, and after the morphological open there are **0 connected
components** — so no arrow candidate is proposed at all. The badge arrow there is
rendered small/dark against the banner and does not clear the red mask
(`sat≥140, val≥80`, `min_area=5`). These centres are inside the battle-map ROI,
so ROI coverage is not the cause.

Fix direction (not applied here): relax the colour prior specifically (lower
`sat_min`/`min_area` or add a darker-red band) and re-measure recall + precision.
This is a colour-segmentation change, deliberately left for review because it
widens the candidate set.

## 2. False-positive targets

24 detections do not match any reviewed badge. Two distinct classes:

| class | n | template score | cause |
|---|---|---|---|
| open province-panel % pill | 4 | med 0.56 | the open panel's emblem+% pill is a *real* emblem sitting outside the fixed panel-exclusion radius, so it is picked up as a map badge |
| red map features (province name-banners, lava terrain) | 20 | med 0.61, max 0.98 | red UI/terrain that scores like an emblem under the masked template |

The mid-map "? 0.60/0.61" false target the Windows reviewer saw on Worlds H and F
is this second class — a **red lava/banner region** whose template score
(~0.60) clears the 0.55 bar. It reads `?` because its percentage crop does not
match any exemplar (similarity below `MIN_PCT_SIM`), so — critically — it is
**never eligible for selection**; it is only drawn as a rejected/unknown marker.

## 3. Score distributions — why this is a threshold decision, not a bug to patch

| set | n | min | median | max |
|---|---|---|---|---|
| true badges (TP) | 29 | **0.64** | 1.00 | 1.00 |
| false positives (FP) | 24 | 0.55 | 0.60 | 0.98 |

Real badges score **high** (min 0.64, median 1.00); most FPs sit in a **0.55–0.65
band** just above the current bar. Raising the template threshold trades recall
for precision:

| threshold | TP kept | FP kept |
|---|---|---|
| 0.55 (current) | 29/29 | 24/24 |
| 0.60 | 29/29 | 12/24 |
| 0.65 | 27/29 | 8/24 |
| 0.70 | 27/29 | 6/24 |

`0.60` drops **half** the false positives with **no** loss of true badges;
`0.65` removes two-thirds of FPs at the cost of 2 real badges. Neither is applied
in this sprint — per the brief, a threshold move must be a reviewed decision, and
it interacts with the recall fix in §1 (which adds candidates). The few
high-scoring FPs (incl. the 0.98 banner and the panel pill) are *real emblems* no
template threshold can separate; those need shape/aspect or panel-region
handling, not a threshold.

`test_detector_regression.py` locks a missed badge and a false positive as
fixtures and asserts the TP/FP separation, so any future threshold or
colour-prior change is measured against these cases rather than eyeballed.

## 4. Percentage `?` — live vs grading rendering

Each detected badge carries a classification diagnostic in `scan.json`
(`predicted`, `similarity`, `top5` nearest labelled exemplars,
`classifier_min_similarity`, `reason`) and, when saved, a raw crop +
normalized classifier input under `06_badge_classifier_crops/`. A badge stays
`?` (UNKNOWN, ineligible for selection) whenever its similarity is below
`MIN_PCT_SIM` (0.55).

The exemplars were cut from the 1920×1080 desktop-screenshot grading set. A live
page-content capture can differ in ways that lower similarity even when
localization is correct:

- **scale** — on-map badges render smaller/larger than the exemplar crops; the
  fixed-geometry percentage patch then samples the wrong pixels.
- **crop offset** — a sub-pixel shift in the emblem centre moves the "XX%" patch.
- **DPI / devicePixelRatio & zoom** — a page capture at a different dPR/zoom
  resizes glyphs and changes anti-aliasing vs the exemplars.
- **font anti-aliasing & background** — the pill sits on varied terrain, so the
  binarized digit edges differ from the grading crops.

These are recorded per capture in `scan.json`'s `geometry` block so a live
mismatch is visible. The remedy is more exemplars / a scale-robust patch (a
follow-up), not accepting low-confidence guesses — `?` is never selected.
