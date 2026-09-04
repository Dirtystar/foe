# Live-scan diagnosis — Windows H/F (M4.6)

Observe-only. No mouse/keyboard/game action. This addresses the second Windows
review: the capture excluded the weakening top bar, badge precision was poor, and
the percentage classifier read `0/5` on live captures.

## 1. Capture now contains the top bar

Root cause: the observe-only banner was painted onto the **image** across the top
~40 px — exactly where the Forge top bar (current weakening) sits — so it was
hidden and could not be calibrated. The CDP capture itself is full-viewport
(`Page.captureScreenshot`, `captureBeyondViewport:false`); the top bar was always
in the pixels, just covered.

Fix: `annotate()` no longer draws any banner on the image. Observe-only status
now lives only in the window title, the side text panel, and the GUI chrome. The
freed top strip shows the real top bar, so **Set Weakening Region** can be drawn
around the live number and the gate can read it.

## 2. Per-candidate diagnostic table

`scan.json` records, for every accepted candidate and every rejected stage-1
candidate: full-image bbox/center, ROI-local coords, colour-prior area,
template score, top-5 nearest percentage exemplars, similarity, predicted % or
UNKNOWN, and the accept/reject reason. The debugger explanation shows the stage
counts (`stage-1 · template-confirmed · rejected · accepted / classified /
unknown`). Populate the "true badge / false positive" and "visual element"
columns by opening the scan in **Label in Review Mode** (§4) — that records your
verdict as ground truth.

The attached H/F **raw** captures were not recoverable from the review
screenshots (only the annotated previews came through), so the exact per-pixel
H/F rows are produced live by Save artifacts / Scan All (`08_classifier_contact_
sheet.png` + `06_badge_classifier_crops/`). The mechanisms below are confirmed on
the grading set (`DETECTOR_DIAGNOSIS.md`) and match the H/F symptoms.

## 3. Why every live percentage read UNKNOWN

`classified 0, unknown 5` on both Worlds is a **classifier-input mismatch**, not a
detection failure. The exemplars were cut from 1920×1080 desktop screenshots; the
live page-content capture differs:

- **crop scale** — `percent_patch` samples a fixed pixel window
  (`dx -4..66, dy -18..18`) around the emblem centre. If the live badge is
  rendered at a different scale than the exemplars, that window lands on the wrong
  pixels and cosine similarity falls below `MIN_PCT_SIM` (0.55) → UNKNOWN.
- **crop offset** — a few-px error in the emblem centre shifts the "XX%" patch.
- **devicePixelRatio / zoom** — a live capture at a different dPR/zoom resizes
  glyphs and changes anti-aliasing versus the exemplars.
- **background** — pills sit on varied terrain, changing the binarized digit
  edges.

`08_classifier_contact_sheet.png` shows each live `%`-crop beside its 5 nearest
grading exemplars, so the scale/offset gap is visible at a glance. The remedy is
**live exemplars** (below) and/or a scale-robust patch — never accepting a
low-confidence guess. `?` is never eligible for selection.

## 4. Fixing it with live ground truth (no external tool)

The debugger's **Label in Review Mode…** button opens the current live capture in
the existing Review Mode: left-click adds/moves a badge, right-click removes a
false positive, keys `1-5` set `20/40/60/80/100`, and it autosaves. Frames are
stored under `data/forge/live_review/frames/<world>_<ts>.png` with their
`labels.json`, so live scans accumulate as additional ground truth that
`train_from_labels` can fold into the classifier — closing the live-vs-training
gap with real live crops rather than a blind threshold change.

## 5. Precision (unchanged thresholds)

Badge localization precision is the same detector characterized in
`DETECTOR_DIAGNOSIS.md`: real badges score high (min ~0.64), false positives
(red banners/lava/panel pills) cluster at 0.55–0.65. No thresholds were changed
this sprint; the TP/FP separation and the recall/precision cost of each threshold
are documented there and locked by `test_detector_regression.py`.
