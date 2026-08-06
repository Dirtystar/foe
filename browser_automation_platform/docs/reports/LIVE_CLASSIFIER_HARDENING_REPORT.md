# Live Percentage-Classifier Hardening — Milestone 5B

_Observe-only. No detector-threshold, `MIN_PCT_SIM`, OCR, cursor-preview, browser,
geometry, scheduler, or UI change. The one behavioural change is a **safety gate
layered on top of** the unchanged `0.70` acceptance bar. Reproduce:
`python -m bap.forge.detection.live_eval`, the §5 per-frame script, and
`pytest tests/unit/forge/test_detection.py -q`._

## Headline

Folding the newly reviewed live Chrome exemplars into the bank made the raw 1-NN
classifier **re-introduce wrong-accepted percentages**: combined wrong-accepted went
**0 → 2** (a mutual **40↔60** confusion at cosine ≈ 0.702, just over the bar). The
fix — a **class-confirmed** acceptance gate (accept the nearest class only when ≥ 2
of the top-3 nearest exemplars agree) — restores **wrong-accepted = 0** *without
lowering `MIN_PCT_SIM = 0.70`*, at a measured cost of **2 correct** classifications
(the only two 100 % badges, matched by lone neighbours). The primary safety
requirement (wrong-accepted = 0) is met; no rejected improvement that raised
wrong-accepted was adopted.

## 1. Data state — the reviewed frames DO enter training

Three frames are committed to the canonical Reviewed Dataset (`dataset/`,
`reviewed: true`), discovered by `classify.default_snapshot_dataset_dir()` /
`dataset.load_all()` and folded into training + evaluation (they are **not** deduped
away — the loader reports `snapshot_frames: 3, snapshot_badges: 6`):

| frame | reviewed | badges (cx, cy, pct) | contributes |
|---|---|---|---|
| `2026-08-04_17-58-59_H.png` | true | (915, 744, **20**) | 1 × 20 exemplar |
| `2026-08-04_23-28-35_H.png` | true | (1242, 537, **null**) | 0 (weakening-only, no pct) |
| `2026-08-05_10-13-33_B.png` | true | (129,131,**60**),(1604,105,**60**),(1681,200,**60**),(830,848,**60**) | 4 × 60 exemplars |

So the reviewed live frames add **5 classified exemplars** (1 × 20, 4 × 60). The
classified-badge corpus grew from 156 → **161**; total truth badges 162 (the null-pct
badge is localised but not classified). Data state is correct — this is a model
question, not a workflow blocker (unlike the prior `LIVE_DATASET_RETRAIN_REPORT.md`,
where the frame was still `reviewed: false`).

## 2. Root cause of the low live similarity — measured, not speculated

Two independent, measured causes; both point at the percent-patch cosine, not the
detector, not OCR (there is none), not a crop-out-of-frame failure.

**(a) Capture-scale / domain gap.** Live Chrome frames sit at a different scale than
the historical 1080-tall training frames. On the reviewed live-B frame every GT badge
is **60 %**, yet the nearest historical/review exemplar is the *wrong class* and below
the bar (real pipeline, bundled classifier):

| live-B GT badge | nearest pred | nearest sim |
|---|---|---|
| (830, 848) 60 % | 20 | 0.558 |
| (129, 131) 60 % | 40 | 0.594 |
| (1681, 200) 60 % | 40 | 0.507 |
| (1604, 105) 60 % | 60 | 0.641 |

The correct class is not even the nearest neighbour for 3 of 4, and none clears 0.70.

**(b) Catastrophic centring sensitivity.** The percent-patch cosine collapses under a
few-pixel centre offset — measured on a real live 60 % badge, self-cosine vs offset:

| offset px | (+1,0) | (+2,0) | (+3,0) | (0,+3) | (+2,+2) | (+3,+3) | (0,+5) |
|---|---|---|---|---|---|---|---|
| self-cosine | 0.864 | **0.706** | 0.650 | 0.526 | 0.545 | **0.423** | 0.383 |

A **2 px** horizontal shift already sits *at* the 0.70 bar; **3 px** in both axes
drops to 0.42. The detector's measured centre error (combined median **7.1 px**, max
24 px) therefore routinely knocks a correct-class crop below the bar — this is the
dominant reason live badges read UNKNOWN even when localisation is perfect.

**Contact sheet** (per live badge: raw crop, normalized 40×24 input, nearest-5
exemplars with pct/similarity, accepted/UNKNOWN):
`live_classifier_hardening/contact_sheet_live_badges.png` (930×1722). It shows the
live crops are darker/lower-contrast and horizontally mis-registered against the
historical exemplars — the visual form of (a)+(b).

## 3. Options evaluated separately

| option | what | measured result | verdict |
|---|---|---|---|
| **A** — add reviewed live exemplars | fold the 5 live crops into the bank | this is what **caused** wrong-accepted 0 → 2 (two lone cross-scale crops reach ≈0.702 as the wrong class) | necessary for coverage, but **unsafe alone** |
| **B** — deterministic crop normalization | height-scale + contrast-normalize + **re-centre by local alignment search** before matching | alignment lifts combined *correct* 35 → ~96, but **adds 4 wrong-accepted** (it also aligns wrong-class crops to > 0.70) | **REJECTED** — raises wrong-accepted |
| **C** — class-confirmed kNN | accept only if ≥ 2 of top-3 nearest share the winning class | combined correct 35, **wrong-accepted 0**; removes both 0.702 confusions without touching the bar | **CHOSEN** |
| **D** — compact supervised classifier | train a small model over the patches | 1-NN is *not* the limiting factor — the limiter is crop registration/scale (B), which a supervised head on the same mis-registered crops would inherit; adds opacity and a training step for no safety gain | **not needed** |

Option B's contrast-only variant (no alignment) was safe but lost correct reads and
did not fix the confusions; only the alignment-search variant recovered accuracy, and
that is precisely the variant that manufactured 4 wrong-accepts, so B is rejected as a
whole for this milestone. `MIN_PCT_SIM` was **not** lowered; OCR was **not** added
(the measured failure is registration, which OCR on the same mis-registered crop does
not fix, and it would not be equally fail-safe).

## 4. Chosen change

`PercentClassifier.confirmed(patch, k=3, need=2)` — the nearest class must be shared
by ≥ 2 of the 3 nearest exemplars. `predict()` stays the raw 1-NN. Acceptance
everywhere is now **`sim >= 0.70` *and* `confirmed()`**:

- `scan._classify` and `scan._panel_state` (runtime),
- `live_eval.evaluate_classification` and `evaluate_full_slice` (honest evaluation).

A cleared-bar-but-unconfirmed match is recorded with a distinct diagnostic reason and
left UNKNOWN. The 0.70 bar, the detector, geometry, OCR stance, cursor preview and UI
are untouched; the slice stays observe-only.

## 5. Before / after — frame-grouped LOFO (`MIN_PCT_SIM = 0.70`)

**Localization (combined) — unchanged** (the change does not touch the detector):

| metric | before | after |
|---|---|---|
| truth badges | 162 | 162 |
| TP / FP / FN | 139 / 72 / 23 | 139 / 72 / 23 |
| precision / recall | 0.659 / 0.858 | 0.659 / 0.858 |

**Classification (combined, 161 classified GT badges, LOFO):**

| metric | before (raw 1-NN) | after (class-confirmed) | Δ |
|---|---|---|---|
| correct | 37 | 35 | −2 |
| UNKNOWN | 122 | 126 | +4 |
| **wrong-accepted** | **2** | **0** | **−2 ✓** |
| confusion | 40→60, 60→40 | — (none) | |
| per-class 20 | 26 / 105 | 26 / 105 | 0 |
| per-class 40 | 0 / 8 | 0 / 8 | 0 |
| per-class 60 | 9 / 43 | 9 / 43 | 0 |
| per-class 100 | 2 / 5 | 0 / 5 | −2 |

The entire cost is the two 100 % badges (100 % has only 5 exemplars; both correct
reads were lone neighbours with no confirming second). No 20/40/60 read changed. Both
wrong-accepts are eliminated.

**Full observe-only slice (combined, detected-centre badges):**

| metric | before | after |
|---|---|---|
| correct_pct | 62 | 56 |
| unknown_pct | 77 | 83 |
| **wrong_accepted_pct** | **0** | **0** |

Note: the two wrong-accepts appeared only in the **GT-centred** classification eval
(where the crop lands exactly on a wrong-class exemplar at 0.702); the detected-centre
slice was already 0, and stays 0. The gate zeroes both paths.

**By source (classification, before → after):**

| source | correct | UNKNOWN | wrong-accepted |
|---|---|---|---|
| historical (incl. 5 live-snapshot badges) | 11 → 10 | 21 → 23 | **1 → 0** |
| review_batch_002 | 26 → 25 | 97 → 99 | **1 → 0** |
| live-H (reviewed live_review) | 0 → 0 | 2 → 2 | 0 → 0 |
| live-F (reviewed live_review) | 0 → 0 | 2 → 2 | 0 → 0 |

_Grouping caveat:_ `live_eval._group` labels the 3 new reviewed **live-snapshot**
frames under `historical` (only the older `live_review` H/F frames carry the `live-*`
labels). Measured separately, the 5 classified live-snapshot badges are **0 correct /
5 UNKNOWN / 0 wrong** both before and after — all sit below 0.70 (see §6), so they add
coverage without adding risk.

## 6. Exact reviewed live snapshot — after the change (no cursor moved)

Real pipeline (`build_scan`, bundled 159-exemplar classifier) on the three reviewed
frames. **No target is selected and nothing would be clicked on any frame** — every
badge is safe UNKNOWN:

| frame | dets | per-badge (cx,cy) pred sim accepted | selected target | would-click |
|---|---|---|---|---|
| `…17-58-59_H.png` (GT 1×20) | 3 | (1059,806) 40 @0.448 ✗ · (1031,797) 60 @0.351 ✗ · (913,749) 20 @0.328 ✗ | **none** | **nothing** |
| `…23-28-35_H.png` (GT 1×null) | 0 | — (no map badge detected) | **none** | **nothing** |
| `…10-13-33_B.png` (GT 4×60) | 4 | (824,847) 20 @0.558 ✗ · (126,128) 40 @0.594 ✗ · (1682,195) 40 @0.507 ✗ · (1602,103) 60 @0.641 ✗ | **none** | **nothing** |

All nearest similarities are below 0.70, so the confirmation gate is not even the
deciding factor here — the bar alone holds them UNKNOWN, and wrong-accepted = 0. The
cursor was not moved.

## 7. Remaining class gaps (for future review batches)

- **40 %: 0 / 8** — still unclassifiable; no 40 % live/near-scale exemplar clears the
  bar. Highest-priority class to review. This is also where the confirmation cost is
  sharpest: on the grading fixture a genuine 40 % badge reads at **0.94** cosine to
  its one 40 % neighbour, but the grading bank holds only two 40 % exemplars, so its
  top-3 is `[40, 100, 100]` and the gate (safely) holds it UNKNOWN — recognition is
  intact, only confirmation is missing. More 40 % exemplars fix this directly.
- **80 %: no exemplars anywhere** — cannot be classified at all until 80 % badges are
  reviewed.
- **100 %: 0 / 5** — regressed from 2 / 5: the two correct reads were lone neighbours
  and are now (correctly) held UNKNOWN. Needs more 100 % exemplars so a *confirming*
  second neighbour exists; this is a coverage gap, not a safety cost.
- **60 % live-scale**: localises perfectly but reads UNKNOWN because same-scale 60 %
  exemplars are sparse and mis-registered (§2). The 4 reviewed live-B 60 % crops are a
  first step; more live 60 % reviews will let same-scale confirmation clear the bar.

## 8. Recommendation for Cursor Preview live testing

- The slice is **safe to exercise in live Cursor Preview**: on real live Chrome
  captures today every badge reads UNKNOWN, so no would-click point is produced and
  the manual preview stays **blocked** — which is the correct, fail-safe state until
  classification is confident. Preview must remain UNKNOWN-blocked; do **not** relax
  the gate to force a target.
- To make the preview actually reach a confident target on live captures, the lever is
  **more same-scale reviewed exemplars** (especially 40/60/80/100 %) plus, if pursued
  later, **deterministic crop re-centring measured against wrong-accepted = 0** (the
  Option B alignment search must be re-evaluated *with* the confirmation gate before it
  could be considered — on its own it failed the safety bar).
- Do **not** lower `MIN_PCT_SIM`: the live nearest similarities (0.33–0.64) are far
  below any bar that keeps wrong-accepted = 0.

## 9. Tests

- New targeted tests (`test_detection.py`): `confirmed()` accepts a two-same-class
  top-3, rejects a lone cross-class nearest, and returns False on empty/None; a
  scan-level regression that an unconfirmed ≥ 0.70 match stays UNKNOWN.
- Three pre-existing tests were updated for behaviour that this milestone's data +
  gate legitimately change — **not** to paper over a regression:
  `test_live_dataset_eval` (two tests) now expect the populated `snapshot` source
  (the 3 reviewed `dataset/` frames) and isolate the dedup case from it;
  `test_capture_geometry::test_regression_full_capture_pipeline` now asserts the
  grading fixture's 40 % badge is *recognised* (nearest = 40 % at 0.94) and that the
  confirmation gate governs *acceptance*, since the grading-only bank cannot confirm
  it (see §7).
- One pre-existing, unrelated bug was also fixed because it deterministically hung
  the whole suite (so "run the suite once" could never complete):
  `test_reopen_restores_saved_state` walked FORWARD with `next()` to reach an
  *earlier* frame, but `next()` clamps at the last index — an infinite loop latent
  since M4.14. Navigate back with `prev()` instead (test-only; no production code).
- Full unit suite: **1020 passed, 1 skipped** (`tests/unit`, offscreen).

_No detector threshold, `MIN_PCT_SIM`, OCR, cursor-preview, geometry, scheduler, or UI
was changed. The only behavioural change is the class-confirmation safety gate above
the unchanged 0.70 bar._
