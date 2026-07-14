# Retrain status — all reviewed datasets

Observe-only. No detector/GUI/World-Manager/OCR/weakening/runtime redesign; no
clicking, cursor, keyboard, or gameplay.

## Blocker: `review_batch_002` is not in the repository

The requested retrain is over three sources:

- `tests/forge_assets/grading/` — present (15 frames)
- `tests/forge_assets/live_review/` — present (3 frames, but see dedup below)
- `tests/forge_assets/review_batch_002/` — **absent**

Verified: the `review_batch_002` directory does not exist, has no `frames/` or
`labels.json`, and has **no git history on this branch**. The reviewed batch
(corrected positions, removed false positives, added badges, assigned
percentages, intentional negatives) is on the Windows machine but was not pushed
— the same pattern as the original keep dataset. The stray empty
`tests/forge_assets/labels.json` (0 frames) is unrelated.

Because that data is not here, the pipeline **cannot** be retrained on the
operator's review_batch_002 corrections. Rather than fabricate data or ship a
misleading "retrain" that silently omits it, this change makes review_batch_002 a
first-class dataset source that is picked up automatically the instant it is
pushed, and records the honest pre-batch baseline for comparison.

## What changed (ready for the data)

- `detection.dataset`: `REVIEW_BATCH_2_DIR` + `load_review_batch()` (guarded — an
  empty list while absent), and `load_all()` now concatenates grading + live +
  review_batch_002 and **de-duplicates by image content** (a frame reviewed in
  more than one root is counted once; the later, reviewed source's labels win).
- `classify.default_label_sources()`: single source of truth for the label sets
  (grading, live_review, review_batch_002) used by both the bundled classifier
  and any retrain. The GUI's bundled classifier already trains from all present
  sources, so review_batch_002 joins automatically.
- `live_eval`: reports `review_batch_002` as its own group alongside historical /
  live-H / live-F / combined.

**No architecture was redesigned.** The detector, percentage classifier, OCR,
weakening reader, World Manager, GUI, and runtime are unchanged. "Retraining" the
classifier is simply rebuilding the exemplar bank from the reviewed label sets —
which now includes review_batch_002 when present.

## Correctness finding: duplicate live-H frame (leakage removed)

The two `live_review` H frames are **byte-identical** (`md5 81cf62a9…`) — the same
capture saved twice. The M4.7 "live-H classified 4/4" was therefore **leakage**:
frame-grouped LOFO classified one H frame using its identical twin (effectively
itself). Content de-duplication now collapses them, so the honest combined corpus
is **17 unique frames** and live-H percentage classification is correctly
**UNKNOWN** (no genuinely distinct same-scale sibling). This is a truer number,
and it reinforces why diverse review_batch_002 samples are needed.

## Pre-batch baseline (frame-grouped LOFO, detector 0.62 / MIN_PCT_SIM 0.62)

Reference point for the review_batch_002 comparison. Reproduce:
`python -m bap.forge.detection.live_eval`.

| set | frames | badges | precision | recall | F1 | FP/frame | centre err (med px) | class correct | UNKNOWN | wrong-accepted |
|---|---|---|---|---|---|---|---|---|---|---|
| historical | 15 | 32 | 0.784 | 0.906 | 0.841 | 0.53 | 6.1 | 6/32 | 26 | **0** |
| live-H (deduped) | 1 | 2 | 1.00 | 1.00 | 1.00 | 0.0 | 4.6 | 0/2 | 2 | **0** |
| live-F | 1 | 2 | 1.00 | 1.00 | 1.00 | 0.0 | 11.8 | 0/2 | 2 | **0** |
| **combined** | **17** | **36** | **0.805** | **0.917** | **0.857** | **0.47** | **6.1** | **6/36** | **30** | **0** |

Safety intact: **wrong-accepted percentage = 0** on every set.

## To complete the retrain (one step, once the data is pushed)

1. Push `tests/forge_assets/review_batch_002/` — `frames/*.png`, `labels.json`
   (reviewed, including the intentional no-badge negatives), and a
   `calibration.json` covering its resolutions.
2. Re-evaluate: `python -m bap.forge.detection.live_eval` — it will now include a
   `review_batch_002` group and an updated `combined`, directly comparable to the
   baseline table above (precision / recall / F1 / FP-per-frame / wrong-accepted /
   UNKNOWN / localization error).
3. The bundled classifier retrains automatically from all present sources
   (`default_label_sources`); no code change needed.

The annotated comparison examples (biggest improvement, still-failing, hardest
negative, one no-badge frame) will be generated from review_batch_002 at that
point — they require the reviewed frames to exist.
