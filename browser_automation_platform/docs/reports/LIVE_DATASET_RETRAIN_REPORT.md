# Live Dataset Retrain — Evaluation Report

_Observe-only, measurement-only. No detector threshold, template-matching, OCR,
cursor-preview, UI, browser, geometry, or weakening change; no new functionality.
Reproduce: `python -m bap.forge.detection.live_eval` and the per-frame classification
script in §5._

## Headline (measured, not speculated)

The **newly reviewed live snapshot is not, in fact, reviewed in the repository**.
The canonical Reviewed Dataset frame `dataset/frames/2026-08-04_17-58-59_H.png` is
committed with `reviewed: false` and **all three badge percentages `null`**. By the
standing ground-truth gate ("only reviewed frames count"), it therefore contributes
**zero training exemplars and zero ground truth**, so retraining produces a
**byte-identical classifier** and the global metrics are **unchanged**. Whatever
review the operator performed on Windows was **not committed/pushed to this branch**
(the remote head is `e1a2f41`, and `dataset/labels.json` was last touched by
`79fe2cd`, before any review).

This is the same condition first documented in `DATASET_SNAPSHOT_SOURCE_REPORT_M4_13.md`;
nothing about the committed frame has changed since.

## 1. Is the frame discovered by the loader? — Yes

`classify.default_snapshot_dataset_dir()` resolves the repo `dataset/`
(`/…/browser_automation_platform/dataset`), and it is a first-class classifier +
eval source (M4.15). Discovery works.

## 2. reviewed / percentages / participates in training? — No / null / No

Measured from `dataset/labels.json`:

| frame | reviewed | badges (cx, cy, pct) |
|---|---|---|
| `2026-08-04_17-58-59_H.png` | **false** | (1059, 806, **null**), (1031, 797, **null**), (913, 749, **null**) |

- `reviewed == true`? **No** — `false`.
- percentages loaded correctly? They are **`null`** (unclassified seeds, not human labels).
- participates in classifier training? **No.** `load_snapshot_dataset()` returns
  **0 samples** (reviewed-gate excludes it), and it has no non-null pct to add as an
  exemplar even if reviewed.

## 3. Retrain

The exemplar bank is rebuilt from every reviewed source
(`classify.default_label_sources`). Measured composition:

| source | frames | badges |
|---|---|---|
| historical (`grading/`) | 14 | 28 |
| `review_batch_002/` | 50 | 124 |
| live (`live_review/`) | 2 | 4 |
| canonical `dataset/` | **0 (unreviewed)** | **0** |
| **total loaded** | **66** | **156** |

Bundled classifier exemplar count: **154** (before **and** after — the `dataset/`
frame adds nothing). The retrained model is identical to the prior one.

## 4. Complete evaluation (frame-grouped LOFO, `MIN_PCT_SIM = 0.70`) — unchanged

Because the corpus is identical, before == after. Reproduced this session:

**Localization (combined):**

| metric | value |
|---|---|
| truth badges | 156 |
| TP | 134 |
| FP | 70 |
| FN | 22 |
| precision | 0.657 |
| recall | 0.859 |
| F1 | 0.745 |

**Percentage classification (combined, `evaluate_classification` over the 156
classified-GT badges, LOFO):**

| metric | value |
|---|---|
| total | 156 |
| correct | 37 |
| UNKNOWN | 119 |
| **wrong-accepted** | **0** |
| correct % | 23.7 % |

**Full observe-only slice (combined, on the 134 detected TP badges):** correct 62,
UNKNOWN 72, **wrong-accepted 0**.

Per-class classification (combined correct/total): 20 → 26/104, 40 → **0/8**,
60 → 9/39, 80 → **0/0 (no exemplars exist anywhere)**, 100 → 2/5.

## 5. Classification on THIS reviewed snapshot — before vs after

Ran the real pipeline (`build_scan`, bundled 154-exemplar classifier) on
`dataset/frames/2026-08-04_17-58-59_H.png`. **Before and after are identical** (the
classifier is unchanged):

| item | value (before == after) |
|---|---|
| detector stage-1 candidates | 351 |
| template-confirmed | 5 |
| accepted detections | **3** |
| classified percentages | **0** |
| UNKNOWN | **3** |
| decision | UNKNOWN (no weakening region calibrated) |
| selected target | **none** (all ignored: "percentage unknown") |
| would-click | **nothing** |

Per detected badge — detector confidence, classifier prediction, **nearest
similarity**, top-5 exemplar similarities:

| centre (cx, cy) | det. conf. | predicted | nearest sim | top-5 (pct: sim) | accepted? |
|---|---|---|---|---|---|
| (1059, 806) | 0.729 | 40 | **0.448** | 40:0.448, 20:0.435, 20:0.414, 20:0.394, 20:0.377 | No (< 0.70) |
| (1031, 797) | 0.636 | 60 | **0.351** | 60:0.351, 60:0.339, 60:0.318, 40:0.304, 60:0.274 | No (< 0.70) |
| (913, 749) | 0.632 | 20 | **0.328** | 20:0.328, 60:0.311, 60:0.281, 60:0.238, 60:0.227 | No (< 0.70) |

All three nearest similarities (0.33–0.45) are far below the 0.70 accept bar, so
every badge is left **UNKNOWN** and **wrong-accepted = 0** holds.

## 6. Global metrics — before vs after

| metric | before | after | Δ |
|---|---|---|---|
| TP (localization) | 134 | 134 | 0 |
| FP | 70 | 70 | 0 |
| FN | 22 | 22 | 0 |
| precision | 0.657 | 0.657 | 0 |
| recall | 0.859 | 0.859 | 0 |
| F1 | 0.745 | 0.745 | 0 |
| correct % (classification) | 23.7 % (37/156) | 23.7 % (37/156) | 0 |
| **wrong-accepted** | **0** | **0** | 0 |

**No change** — the unreviewed frame adds no exemplar and no ground truth, so the
LOFO evaluation over the same 66 frames / 154 exemplars is deterministically
identical.

## 7. Why the live snapshot is STILL UNKNOWN — measured

Two distinct, measured causes:

1. **It is not reviewed** (`reviewed: false`, percentages `null`). This is why it
   neither trains the classifier nor can be scored as ground truth — the primary
   blocker, and it is a data/workflow state, not a model limitation.
2. **Classifier similarity below threshold.** Independently, when the pipeline
   classifies the frame's three detected badges, the nearest-exemplar cosine
   similarities are **0.448 / 0.351 / 0.328**, all under `MIN_PCT_SIM = 0.70`, so they
   are safely left UNKNOWN (the fail-safe that keeps wrong-accepted = 0).

The underlying reason for the low similarity is **insufficient / mismatched
exemplars** for this frame's badge appearance, confirmed by measurement:

- This frame (md5 `6aa01aba…`, captured 2026-08-04) is a **distinct** capture from
  the two reviewed live-H frames in `live_review/` (md5 `81cf62a9…`, captured
  2026-07-12), which sit at different centres (558/1072) with labels 20 % and 60 %.
  So the reviewed bank contains **no same-frame, same-appearance exemplar** for these
  three crops.
- Not ruled-out causes, measured away: it is **not** OCR (this classifier is OCR-free,
  template-cosine), **not** a detector-crop failure (all three badges were localized
  with confidence 0.63–0.73), and **not** scaling of the capture (full 1080p frame).
  The gap is purely the **percentage-patch cosine distance** to the existing bank.

**The single action that would resolve it: review this frame** — open it in Review
Mode, assign the true 20/40/60/80/100 to each real badge (and remove any false
positive), and mark it reviewed. Then it (a) becomes ground truth and (b) supplies
same-appearance exemplars, at which point the classifier can clear 0.70 on
same-appearance future captures (this is exactly the mechanism that took
`review_batch_002` from 0 to 26/124 classified). Until then, UNKNOWN is the correct,
safe output.

## Dataset contribution

**Zero.** The committed `dataset/` frame is unreviewed with null percentages: 0
training exemplars, 0 ground-truth badges, classifier unchanged at 154 exemplars,
evaluation set unchanged at 66 frames / 156 badges.

## Recommendation

1. **Review and commit the frame.** On Windows, open
   `dataset/frames/2026-08-04_17-58-59_H.png` in Review Mode (Datasets → Open Dataset
   in Review), label the real badges' percentages, resolve the (1059,806)/(1031,797)
   pair (28 px apart — likely a double-detection of one badge), mark **reviewed**,
   **Save**, and push. The loader/regression test already guarantee it then joins
   training + evaluation automatically (no code change).
2. **Re-run this evaluation after the review is pushed.** Only then can "does the
   classifier improve" be answered with ground truth; today the honest answer is
   that the frame contributes nothing and metrics are unchanged.
3. **Do not lower `MIN_PCT_SIM`.** The prior sweep showed 0.70 is the lowest bar that
   keeps wrong-accepted = 0; the 0.33–0.45 similarities here are far below any safe
   bar, so forcing acceptance would be a wrong read, not an improvement.
4. **40 % and 80 % remain unclassifiable** for lack of exemplars (40 % is 0/8; 80 %
   has none anywhere) — future reviews should prioritise those classes.

_No code, thresholds, or models were changed by this milestone; it is measurement
and reporting only._
