# Percentage Classifier V2 Benchmark — Milestone 5C

_Experimental classifier research, OBSERVE-ONLY. No clicking, cursor movement,
detector-threshold, OCR, weakening, geometry, scheduler, or UI change. The
production v1 classifier is imported read-only as the baseline and is **not**
modified. Reproduce: `python -m bap.forge.research` (metrics, folds, robustness,
live recheck, performance) and `python classifier_v2/make_audit.py` (detector-based
data audit)._

## Outcome: **C — Reject all v2 candidates. Keep v1. More data is required.**

Under a leakage-free, frame-grouped evaluation with the mandated safety layer
(**wrong-accepted = 0**), no candidate beats v1's correct-accepted count while
staying safe. v1 remains the production default, unchanged.

| candidate | correct | UNKNOWN | wrong-accepted | eligible? |
|---|---|---|---|---|
| **A — v1 (fixed 0.70 + confirm)** | **35** | 115 | **0** | baseline |
| B — robust recentre + tuned threshold | 30 | 119 | **1** | ✗ worse correct **and** leaks a wrong-accept |
| C — numpy logistic regression (tuned) | 0 | 150 | 0 | ✗ safe only by rejecting everything |
| D — compact neural | not built | — | — | ✗ data audit does not support it |

(Common 150-badge head-to-head set; see §2. v1 on the full 161-badge production set
is the M5B result: 35 correct / 0 wrong.)

## 1. Baseline frozen

The M5B production classifier (`bap.forge.detection.classify.PercentClassifier`:
fixed-crop cosine 1-NN, `MIN_PCT_SIM = 0.70`, top-3 confirmation) is preserved as
**v1** and untouched. Reproduced this milestone under the harness: **35 correct /
115 UNKNOWN / 0 wrong-accepted** combined, and byte-identical under frame-key
("identity") folds — confirming the harness matches the production frame-grouped
LOFO.

## 2. Data audit (`classifier_v2/dataset_audit.json`)

69 reviewed frames, 162 badges, **161 classified**. Deduplicated by image hash
(no exact duplicates remain). Measured:

- **Per class:** 20 → 105, 40 → **8**, 60 → 43, 100 → **5**, **80 → 0**.
- **Per source:** review_batch_002 124 (50 frames), historical 28 (14), live 4 (2),
  snapshot 5 (3). **Live-source total: 9 badges across 5 frames.**
- **Resolution:** 1920×1080 ×64, 1920×912 ×3, 1600×900 ×2.
- **Detector centre-offset (matched badges):** median **7.07 px**, mean 7.77, p90
  14.2, max 24.2 — the alignment error a robust classifier must tolerate.

**Verdict on data sufficiency:** the data does **not** support an honest neural or
even a genuinely useful supervised model. 80 % has **zero** examples (unlearnable);
40 % (8) and 100 % (5) are single-digit; 20 % is 65 % of the corpus; only ~24
non-20 % badges exist across a handful of independent scenes. No torch/sklearn is
available, and augmentation may not manufacture the missing 40/80 classes (and the
milestone forbids synthetic labels). This is the primary finding: **the limit is the
dataset, not the model family.**

## 3. Evaluation protocol (leakage-free)

`bap.forge.research.classifier_bench` — grouped leave-one-fold-group-out. Fold
groups (`classifier_v2/fold_manifest.json`): exact duplicates are removed by the
loader; **near-duplicate screenshots** (aHash Hamming ≤ 5 over the battle-map ROI)
are unioned into one fold group so two views of the same battle never straddle
train/test (69 frames → 60 fold groups; 8 multi-frame groups). No crop from a
held-out group appears in training. Rejection thresholds are tuned **only** on
training folds via grouped 5-fold out-of-fold predictions (§5); the held-out frame
never participates. Candidate C's logistic regression is deterministic (fixed seed
+ iterations); results were stable across 3 seeds (B: 30/1, C: 0/0 each).

The head-to-head set is the **150** badges whose padded context crop lies fully in
frame (11 near-edge badges are dropped for the crop-based candidates); per class
20 → 95, 40 → 8, 60 → 42, 100 → 5.

Primary metrics recorded per candidate (`classifier_v2/model_metrics.json`):
wrong-accepted, correct-accepted, UNKNOWN, per-class correct/wrong/UNKNOWN,
confusion matrix, plus latency / size / training time
(`classifier_v2/model_performance.json`).

## 4. Candidates

**A — v1 baseline.** Fixed-crop cosine 1-NN, 0.70 + top-3 confirmation.

**B — robust deterministic.** Bounded, class-independent text-centroid re-centre
(clamped to ±8 px — never an unrestricted alignment search), CLAHE local contrast,
mild blur for translation tolerance, then cosine 1-NN + confirmation, with the
acceptance threshold tuned on training folds.

**C — compact supervised.** A numpy multinomial logistic regression over the
contrast-normalized 40×24 crop (class-weighted for the 20 % imbalance),
deterministic, 23 KB. Softmax probability is the confidence; rejection threshold
tuned on training folds.

**D — compact neural.** **Not built.** The §2 audit rejects it: 80 % has no
examples, 40/100 % are single-digit, the corpus is 65 % one class, there are too few
independent scenes, and no lightweight-embedding dependency is available. Building it
would manufacture confidence the data cannot support.

### Grouped results (combined, 150 badges)

| candidate | gate | correct | UNKNOWN | wrong | confusion |
|---|---|---|---|---|---|
| A (v1) | fixed 0.70 + confirm | 35 | 115 | **0** | — |
| B | **fixed 0.70** (pre-safety) | 54 | 88 | **8** | 20→60 ×3, 40→20 ×2, 60→20 ×3 |
| B | **train-tuned** thr ≈ 0.81 + confirm | 30 | 119 | **1** | 60→20 ×1 |
| C | **fixed** default (pre-safety) | 100 | 1 | **49** | 20→60 ×20, 60→20 ×18, … |
| C | **train-tuned** thr = 1.0 | 0 | 150 | **0** | — |

Per-class (tuned): A 20→26/95, 40→0/8, 60→9/42, 100→0/5. B 20→22/95, 40→1/8,
60→7/42, 100→0/5. C all 0.

**Reading:** B's re-centring genuinely recovers accuracy — 54 correct at the fixed
gate vs v1's 35 — but it aligns *wrong-class* crops just as well, producing 8
wrong-accepts. The Step-5 safety layer raises B's bar to ≈0.81 to zero out
*training* wrong-accepts, but on held-out frames one 60→20 still slips through **and**
correct falls to 30 (below v1). C at any safe threshold must reject everything. No
class is systematically mis-mapped by v1 (it simply abstains); B's residual error is
the 60↔20 confusion at live scale.

## 5. Safety acceptance / rejection layer

Implemented as mandated: for each held-out fold, the acceptance threshold is chosen
on the **training** records only (grouped 5-fold OOF) as the smallest confidence
giving zero training wrong-accepts (with a margin); if even the most-confident OOF
prediction is wrong, the threshold is pushed above it so nothing is accepted —
UNKNOWN is always safe. Eligibility requires wrong-accepted = 0 combined **and** on
every live slice, calibrated confidence, and a real improvement over v1 not caused by
leakage/duplicates. **B fails** (held-out wrong = 1, correct < v1). **C fails** (no
value). Confidence is **not** meaningfully calibrated at this data scale (a held-out
reliability curve cannot be estimated from single-digit rare-class counts) — another
reason to abstain rather than promote.

## 6. Robustness (`classifier_v2/robustness_curves.{json,csv}`)

Per-candidate correct/wrong/UNKNOWN on **perturbed held-out crops** (LOFO; A at 0.70,
B at its tuned ≈0.81). Diagonal centre shift:

| shift (dx=dy) | A correct/wrong/unk | B correct/wrong/unk |
|---|---|---|
| −10 | 17 / 0 / 133 | 8 / **0** / 142 |
| −6 | 21 / 0 / 129 | 17 / **1** / 132 |
| −4 | 20 / 0 / 130 | 21 / **2** / 127 |
| −2 | 22 / 0 / 128 | 26 / **1** / 123 |
| **0** | **35 / 0 / 115** | 30 / 0 / 120 |
| +4 | 16 / 0 / 134 | 26 / 0 / 124 |
| +6 | 18 / **1** / 131 | 29 / 0 / 121 |
| +10 | 8 / 0 / 142 | 9 / **2** / 139 |

Both degrade sharply with centre error (confirming the M5B ≈7 px sensitivity). B
holds *more* correct at some shifts but **introduces wrong-accepts at −6/−4/−2/+10
px** — i.e. it does **not** solve the centering sensitivity *within the safety
envelope*; it trades safety for robustness. v1 stays wrong ≈ 0 (one stray at +6 px).
Scale/blur/brightness/contrast curves (in the CSV) show the same pattern: no
candidate achieves both higher correct and wrong = 0 off-centre.

## 7. Exact live-snapshot recheck (`classifier_v2/live_recheck.json`)

All **9** reviewed live Chrome badges (live_review H/F + the 3 canonical `dataset/`
frames), models trained on all non-live data, cursor **not** moved:

| model | accepted | correct | wrong |
|---|---|---|---|
| v1 | 0 | 0 | **0** |
| B | 0 | 0 | **0** |
| C | 0 | 0 | **0** |

Every live badge is UNKNOWN for every candidate — **no target, and no *wrong*
target, becomes selectable** for any model. The live badges' nearest predictions are
scattered across classes (a GT-60 reads as 20/40/60/100 depending on model),
confirming the live-scale domain gap the current data cannot bridge. Contact sheet:
`classifier_v2/contact_sheet_live_v1_v2.png`.

## 8. Performance (`classifier_v2/model_performance.json`)

| candidate | train | latency/pred | model size |
|---|---|---|---|
| A (v1) | 0.1 ms | 229 µs | 576 KB (exemplar bank) |
| B | 0.0 ms | 145 µs | 576 KB (exemplar bank) |
| C | 32 ms | 11 µs | **23 KB** (parametric) |

## 9. Selection & rationale

**Outcome C — reject all v2 candidates; keep v1.** No candidate satisfies the
eligibility bar (wrong-accepted = 0 everywhere **and** a real correct-accepted
improvement over v1). B is unsafe off-centre and no better on-centre; C is safe only
by abstaining; D is not honestly trainable. The production default is **unchanged**;
no model artifact is committed (none was selected). No feature flag or model
versioning is introduced because nothing is promoted.

## 10. Remaining data requirements (to make a v2 viable)

1. **Real 80 % badges** — currently zero; 80 % cannot be classified by any model.
2. **More 40 % and 100 %** — 8 and 5 today; too few for a fold to ever train them.
3. **More independent live-Chrome scenes** across 900/912/952/1080 captures and
   100/125/150 % Windows scaling, so a robust model has same-scale, well-centred
   exemplars for the classes that currently only appear historical-scale.
4. Balanced review beyond the 20 %-dominated corpus (20 % is 65 % of the data).

With those, re-running `python -m bap.forge.research` will re-test B/C (and make D
assessable) under the same leakage-free protocol. Until then, **v1 + UNKNOWN is the
correct, safe behaviour**, and live Cursor Preview must remain UNKNOWN-blocked.

## Artifacts

- `classifier_v2/dataset_audit.json` — full per-badge audit + offsets (`make_audit.py`).
- `classifier_v2/fold_manifest.json` — near-duplicate fold groups, no-leakage map.
- `classifier_v2/model_metrics.json` — A/B/C combined + per-source + per-class + confusion.
- `classifier_v2/robustness_curves.{json,csv}` — shift/scale/blur/contrast/brightness.
- `classifier_v2/live_recheck.json` — per-live-badge v1/B/C predictions & acceptance.
- `classifier_v2/model_performance.json` — latency / size / training time.
- `classifier_v2/contact_sheet_live_v1_v2.png` — live crops, all UNKNOWN.
- `src/bap/forge/research/` — the benchmark harness (experimental, imports v1 read-only).
- `tests/unit/forge/test_classifier_bench.py` — leakage / grouping / determinism /
  bounded-augmentation / UNKNOWN-rejection / safe-failure / no-cursor tests.

_No production classifier, threshold, or behaviour was changed. Observe-only._
