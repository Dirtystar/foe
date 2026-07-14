# Retrain report — all reviewed datasets

Retrain + re-evaluation of the Forge badge pipeline on every reviewed dataset,
frame-grouped leave-one-frame-out. **Observe-only**; the detector, GUI, World
Manager, OCR, weakening reader, and runtime are unchanged. Reproduce:
`python -m bap.forge.detection.live_eval`.

## Datasets

| source | frames | badges | notes |
|---|---|---|---|
| `grading/` | 14 | 28 | one frame (frame_000070) de-duplicated into the batch |
| `live_review/` | 2 | 4 | the two H frames are byte-identical → collapsed to one |
| `review_batch_002/` | 50 | 124 | reviewed active-learning batch (incl. 6 no-badge negatives) |
| **combined (deduped)** | **66** | **156** | frames counted once by image content; reviewed source wins |

Normalization applied (deterministic, documented): the 6 intentional no-badge
negatives were marked `reviewed` so they load and count toward false-positive
measurement; the committed `.cache/` (generated checkpoints) was untracked and
git-ignored. **Percentage classes present: 20, 40, 60, 100 — there are zero 80%
examples anywhere**, so 80% is currently unclassifiable.

## What "retrain" means here (architecture preserved)

- **Percentage classifier**: the exemplar bank is rebuilt from every reviewed
  label set via `classify.default_label_sources` — review_batch_002 joins
  automatically. No code redesign.
- **Localization (detector)**: unchanged. The colour-prior + masked emblem
  template bank + NMS and its 0.62 template threshold are preserved, so these
  numbers show how the *existing* detector generalizes to the 50 new, deliberately
  hard (active-learning-selected) frames.
- **Safety threshold**: the classifier accept bar `MIN_PCT_SIM` was raised
  **0.62 → 0.70**. The larger, more diverse bank otherwise admits 20↔60 / 60↔100
  confusions that clear 0.62; 0.70 is the lowest bar that keeps **wrong-accepted
  = 0** (sweep below). A raise = strictly safer, per the standing rule "UNKNOWN
  must remain safer than a wrong-accepted percentage."

  | MIN_PCT_SIM | correct | UNKNOWN | wrong-accepted |
  |---|---|---|---|
  | 0.62 | 60 | 91 | **5** |
  | 0.66 | 47 | 107 | 2 |
  | **0.70 (chosen)** | 37 | 119 | **0** |
  | 0.74 | 31 | 125 | 0 |

## Results (frame-grouped LOFO, MIN_PCT_SIM 0.70)

| set | frames | P | R | F1 | FP/frame | centre err (med px) | class correct | UNKNOWN | **wrong-accepted** |
|---|---|---|---|---|---|---|---|---|---|
| historical | 14 | 0.833 | 0.893 | 0.862 | 0.36 | 6.0 | 11/28 | 17 | **0** |
| live-H | 1 | 1.00 | 1.00 | 1.00 | 0.0 | 4.6 | 0/2 | 2 | **0** |
| live-F | 1 | 1.00 | 1.00 | 1.00 | 0.0 | 11.8 | 0/2 | 2 | **0** |
| review_batch_002 | 50 | 0.618 | 0.847 | 0.715 | 1.30 | 7.6 | 26/124 | 98 | **0** |
| **combined** | **66** | **0.657** | **0.859** | **0.745** | **1.06** | **7.1** | **37/156** | **119** | **0** |

**Safety metric — wrong-accepted percentage = 0 on every set** (full-slice
wrong-accepted% = 0). Per-class classification (combined correct/total): 20 → 30,
40 → **0/8**, 60 → 7, 80 → **0/0 (no data)**, 100 → 2.

## Comparison vs the previous pipeline

Previous baseline (pre-batch, 17 frames): combined P 0.805 / R 0.917 / F1 0.857,
classification 6/36 correct, wrong-accepted 0.

**Improved**

- **Percentage classification coverage.** The classifier now reads badges it
  could not before: on the *same* 50 batch frames it went from **0** classified
  (grading+live-only bank) to **26/124** at the safe bar — combined correct 6 →
  37 (≈ 6×) — because the batch supplies same-scale exemplars. This is the retrain
  payoff.
- **Historical localization precision** 0.78 → 0.83 (de-dup moved a high-FP
  grading frame into the batch's accounting).
- **Wrong-accepted stayed 0** despite the larger, noisier bank — the 0.70 raise
  absorbed the 5 confusions that appeared at 0.62.

**Did not improve / regressed**

- **Combined P/R/F1 are lower than the 17-frame baseline** — not a model
  regression: the corpus now includes 50 frames the active-learning selector
  deliberately chose as the *hardest / most uncertain*. On those, the unchanged
  detector keeps high recall (0.847) but lower precision (0.618, 1.3 FP/frame) —
  red banners / lava score like emblems. Localization was not retrained (detector
  preserved).
- **40% and 80% classification.** 40% is 0/8 (few, confusable exemplars); 80% has
  **no examples anywhere** and cannot be classified. Both need labelled samples.
- **Live classification (dedup finding).** The two live-H frames are byte-identical;
  the earlier "live-H 4/4" was leakage (LOFO using an identical twin). Deduped and
  at the 0.70 bar, live-H/F percentages are honestly UNKNOWN.

## Annotated examples (`review_batch_002/annotated/`)

- **`biggest_improvement.jpg` — frame_000614.** 5 badges localized (5 TP, 1 FP);
  **4 percentages now classify that were UNKNOWN before the batch** (gain +4). The
  batch added same-scale 20/60 exemplars, so these crops clear the 0.70 bar. Why
  it works: the frame's badge scale matches new exemplars.
- **`still_failing.jpg` — frame_000762.** Both real badges are localized (2 TP) but
  the frame also yields **6 false positives**, and both percentages stay UNKNOWN.
  Why: hard red-terrain frame — banners score like emblems (detector precision
  limit), and the badge crops don't match any exemplar ≥ 0.70, so they are safely
  left UNKNOWN rather than guessed.
- **`hardest_negative.jpg` — frame_000662 (no badges).** A negative with **5 false
  positives**. Why: lava/banner reds clear the emblem template threshold; this is
  the detector's precision ceiling on hard negatives. Crucially every one is
  UNKNOWN % — **no wrong-accepted**.
- **`no_badge_negative.jpg` — frame_000238 (no badges).** **0 detections** — a clean
  negative. Why: this frame has no red emblem-like features, so the colour prior
  proposes nothing and the detector correctly stays silent.

## Remaining work (not this milestone)

- Label 40% and 80% badges (80% is absent) so those classes become classifiable.
- Detector precision on hard negatives (red terrain/banners) — a colour-prior /
  shape-filter change, deliberately deferred to preserve detector behaviour.
- More distinct live samples (the current live-H pair is a duplicate).

Observe-only throughout: the pipeline computes a would-click point and explains
itself; it never clicks, moves the cursor, types, or takes any gameplay action.
