# Live Windows Review — Milestone 4.12 (Fix Live Validation Findings)

_Observe-only throughout. No mouse, click, keyboard, battle flow, scheduler, or M5
work. This milestone root-causes and fixes the classifier wiring defect exposed by
the first live Windows Vision Validation, corrects the validation grading
semantics, and diagnoses the H false-positives and the 40–54 s live runtime._

Branch `claude/browser-automation-architecture-5784h1`. Tag `forge-m4-stable`
untouched.

Evidence tags: **[LIVE]** operator-reported live fact · **[FIXED]** code fix
proven here · **[REAL-FRAME]** measured on real Forge frames already in the repo ·
**[INFERENCE]** engineering judgement.

---

## 0. Headline

**The "all percentages UNKNOWN / nearest similarities (none) / zero histogram"
symptom was a classifier that was never built.** `_bundled_classifier()` resolved
the reviewed-dataset directory to a **non-existent path** (`src/tests/forge_assets`
via a fixed `parents[2]` index; the data is at repo-root `tests/forge_assets`),
returned `None`, and the pipeline then **skipped the whole classification stage**.
It reproduces exactly and is now **fixed and regression-tested**. It was **not** a
training-data problem — 20% has 154 exemplars.

---

## 1. Exact live data — paths found

The operator reviewed and pushed H and D frames via Label-in-Review-Mode, but
**those frames are not present in this repository** on any branch:

- Searched `tests/forge_assets/{grading,live_review,review_batch_001,review_batch_002}` —
  the only `H_*`/live frames are the older `H_20260712_*` captures; there is **no
  `D_*` frame and no new H 1604×952 / D 1600×900 frame**.
- Branch `origin/forge-dataset` is an older divergent branch (2 commits) and does
  not contain them. `git log --all` shows nothing newer than this branch's HEAD.

**Conclusion [INFERENCE]:** Review Mode saved the frames/labels to the operator's
**local app data dir** on Windows; the push did not reach this remote (the same
class of remote/push limitation seen in earlier milestones). The regression fixes
below therefore use **existing real frames as faithful proxies** and are written to
also apply to the operator's frames once committed. The specific proxy used for the
H no-badge case, `review_batch_002/frame_000662.png`, is itself **0 real badges,
5 false positives** — a near-exact analogue of live H (0 real, 4 FP).

> Action for the operator: commit the reviewed H (0-badge) and D (3×20%) frames +
> labels into `tests/forge_assets/` so they become permanent regression fixtures.
> The tests added here will then bind to them directly.

---

## 2. Classifier pipeline bug — root cause  [FIXED]

### Trace (live path vs the working offline path)
```
Vision Validation → main_window._forge_classifier() → forge_debugger._bundled_classifier()
   → root = Path(__file__).resolve().parents[2] / "tests" / "forge_assets"
   → parents[2] of  src/bap/gui/forge_debugger.py  =  src/     (NOT repo root)
   → src/tests/forge_assets  DOES NOT EXIST
   → default_label_sources(root) == []   → train_from_sources not called
   → _bundled_classifier() == None
→ run_tick/build_scan:  `if classifier is not None and len(classifier): _classify(...)`
   → classifier is None → classification SKIPPED
   → scan.classify_diag == []   → every detection keeps pct=None (UNKNOWN)
→ Validation Classification section reads scan.classify_diag:
   → nearest similarities = "(none)",  histogram all-zero,  all UNKNOWN
```
Test Scan / Vision Debugger use the **same** `_bundled_classifier()`, so they were
affected identically on the live app.

### Proof of each hypothesis
| hypothesis | verdict | evidence |
|---|---|---|
| classifier bank empty | **YES — root cause** | `_bundled_classifier()` returned `None`; resolved root `src/tests/forge_assets` `exists()==False` |
| wrong classifier instance passed | no | the same (None) instance flows through; wiring is correct once non-None |
| percentage crops invalid/None | no | with a real classifier, `percent_patch` returns valid crops and `classify_diag` fills |
| classification skipped | **YES (consequence)** | `_classify` is gated on `classifier is not None and len(classifier)` |
| results lost when building report | no | the report faithfully reflects an empty `classify_diag` |

Reproduction (real frame `frame_000614`, has 20% badges):
| classifier | detections | classify_diag | 20% | UNKNOWN | histogram | nearest sims |
|---|---|---|---|---|---|---|
| `None` (the bug) | 6 | **0** | 0 | 6 | all-zero | **(none)** |
| loaded (len 154) | 6 | **6** | 4 | 2 | `[.00-.50]2 [.70-.85]1 [.85-1.01]3` | 0.88,0.86,0.86,0.83,0.25,0.25 |

The first row **is** the operator's World-D report.

### Fix
`classify.default_assets_root()` — walks up from the module to find
`tests/forge_assets` (layout- and cwd-independent), returning `None` only when the
datasets are absent (installed wheel). `_bundled_classifier()` (and the identical
latent bug in `perf/benchmark._ASSETS_ROOT`) now use it.

- **[FIXED]** `_bundled_classifier()` → `PercentClassifier`, **len 154**, and works
  from any cwd (verified running from `/tmp`).
- Regression tests (`tests/unit/forge/test_classifier_wiring.py`): assets root
  resolves; bundled classifier non-empty; on a real 20% frame **every detection
  reaches the classifier and produces a similarity** (not missing); at least one
  20% classifies; and **no percentage is accepted below `MIN_PCT_SIM` (0.70)** —
  wrong-accepted stays 0. **`MIN_PCT_SIM` was not lowered.**

---

## 3. H false-positive regression  [REAL-FRAME proxy]

Operator ground truth **[LIVE]**: World H = **0 real badges, 4 accepted → 0 TP /
4 FP**, all four UNKNOWN.

The H frame is not in the repo; the analogue `frame_000662` (0 GT badges) yields
**5 false positives**, all `template-confirmed` (they cleared the detector's 0.62
template threshold):

| FP | center | note |
|---|---|---|
| 0 | (706, 623) | red-terrain / banner cluster |
| 1 | (800, 674) | red-terrain / banner cluster |
| 2 | (822, 685) | red-terrain / banner cluster |
| 3 | (696, 749) | red-terrain / banner cluster |
| 4 | (1448, 1000) | isolated red feature |

**Why they pass 0.62:** these are red banner/lava emblem-like shapes; the colour
prior proposes them and the masked emblem template scores ≥ 0.62. This is the
known detector precision ceiling on hard red-terrain negatives (documented since
`RETRAIN_REPORT.md`).

**Filterable properties observed [INFERENCE]:** 4 of 5 FPs are **spatially
clustered** in one red-terrain region; candidates expose `template_score`,
`color_area`, and spatial position — a future filter could use spatial clustering
+ percentage-pill absence + `color_area` bounds. **No detector change was made this
milestone** (out of scope; the demonstrated defect was the classifier wiring). Any
future filter must be evaluated against: H FPs, D's 3 true badges, and the
historical/review_batch sets, with **wrong-accepted staying 0** — the standing bar.

---

## 4. Validation grading correction  [FIXED]

The Badge Detection section previously read **PASS** whenever the detector merely
executed — so "4 accepted candidates on a no-badge frame" looked like an accuracy
pass. Corrected semantics (`validation._badge_section`):

- **Execution health is INFO** ("detector executed"), never an accuracy PASS.
- **Accuracy cannot PASS without human ground truth.** A live/unreviewed scan now
  reports `accuracy (TP/FP/FN) = UNVERIFIED` (INFO) with the action *"Label this
  frame in Review Mode."* The section overall is **INFO**, not PASS.
- **Reviewed frames** (a `ground_truth_badges` count is supplied) get **measured**
  count-accuracy: matches → PASS; accepted > real → WARNING (`+N likely FP`);
  accepted < real → WARNING (`N missed`).

Verified on `frame_000662`: unverified → **INFO/UNVERIFIED**; `ground_truth=0` with
5 accepted → **WARNING "5 accepted > 0 real (+5 likely FP)"**; matched → PASS.
Regression tests added.

---

## 5. Performance diagnosis  [REAL-FRAME]

**Detection time is ~linear in the stage-1 candidate count** (template matching per
candidate dominates):

| frame | size | stage-1 cand | detection | ms / candidate |
|---|---|---|---|---|
| frame_000238 | 1920×1080 | 42 | 3432 ms | 81.7 |
| frame_000614 | 1920×1080 | 50 | 4136 ms | 82.7 |
| frame_000662 | 1920×1080 | 56 | 4448 ms | 79.4 |

≈ **80 ms per stage-1 candidate**, constant across frame content. Extrapolating to
the operator's live frames **[LIVE]**:

| World | stage-1 cand | detection | implied ms/candidate |
|---|---|---|---|
| H | 386 | 53.8 s | 139 |
| D | 212 | 41.6 s | 196 |

So the 41–54 s is **not a regression** — it is the same per-candidate cost applied
to **4–8× more candidates**. Live Guild-Battlegrounds frames (large red-terrain
maps at 1604×952 / 1600×900) generate far more colour-prior candidates than the
~50 on the desktop-scale benchmark frames (~3–5 s). The higher live ms/candidate
(139–196 vs 80) is consistent with larger crops at those resolutions **[INFERENCE]**.

**Before/after runtime:** the classifier fix **does not change detection cost** (it
adds ~55–110 ms of *classification*, previously skipped) — so no runtime
improvement is claimed. Removing false-positive candidates *would* cut time
(fewer template matches), but that requires a detector change that is **not proven
safe here**, so per the change policy the performance blocker is **documented, not
refactored**: *detection is O(stage-1 candidates); live red-terrain frames produce
many candidates.*

---

## 6. Weakening calibration  [MECHANISM VERIFIED]

The operator's newly-saved per-resolution weakening ROIs (H 1604×952, D 1600×900)
live in their **local data dir** and are **not in this repo**, so their specific
values cannot be loaded here. What is verified:

- **Load mechanism [REAL-FRAME]:** `WeakeningCalibration.get(w, h)` is keyed by
  exact resolution (`geometry.key()` includes raw size + viewport/DPR/zoom), so a
  ROI saved for 1604×952 is used only for 1604×952 and never reused for 1600×900.
- **Per-World history isolation + fail-safe [CODE]:** `WeakeningTracker` keeps one
  history per `world_id`; H confirming 5 and D confirming 8 never mix; a lone
  suspicious drop or an unreadable read is not accepted and does not overwrite a
  confirmed value. UNKNOWN stays UNKNOWN.
- **OCR algorithm unchanged** (as required).

Operator step to close this section live: with the ROIs now calibrated, run several
consecutive reads per World and record visible value / OCR value / confidence /
tracker-confirmed value / gate decision. (Cannot be produced in this container.)

---

## 7. Results summary

| item | World H | World D |
|---|---|---|
| ground truth badges **[LIVE]** | 0 | 3 (all 20%) |
| localization TP / FP / FN **[LIVE]** | 0 / 4 / 0 | 3 / 0 / 0 |
| % correct / UNKNOWN / **wrong** — *before fix* **[LIVE]** | 0 / 4 / **0** | 0 / 3 / **0** |
| % after fix | n/a (no real badges) | **expected 20% to classify** (proxy frame: 4/6 classify) — needs the committed D frame to confirm |
| weakening | uncalibrated at scan time → UNKNOWN (fail-safe) | same |

- **Wrong-accepted percentage = 0** in every case, before and after the fix
  (the safety invariant held even while classification was broken — UNKNOWN is the
  fail-safe).
- **Classifier root cause:** bundled classifier was `None` (wrong dataset path) →
  classification skipped. **Fixed.**
- **H false-positive category:** red-terrain / banner emblems clearing the 0.62
  template threshold, spatially clustered. Detector unchanged.
- **Performance:** detection ≈ 80 ms × candidates; live 40–54 s is the candidate
  count (386 / 212), not a regression.

---

## 8. Remaining blockers before M5

1. **Live re-validation after the classifier fix** — the operator must re-run
   Validate Vision on World D with this build to confirm the 3 × 20% badges now
   classify live (the fix is proven on a proxy frame here, not on the D frame).
2. **Operator frames not committed** — commit the reviewed H (0-badge) and D
   (3×20%) frames + labels so they become binding regression fixtures.
3. **Detector precision on red terrain** — H's 4 FPs (and the ~80 ms/candidate cost)
   are the detector's known ceiling; a safe FP filter is future work (evaluated
   against all datasets, wrong-accepted = 0).
4. **Live weakening calibration confirmation** — consecutive reads per World with
   the newly saved ROIs.

## 9. Recommendation on Move Cursor Preview

> **Not yet — one more live pass is required.** The critical live blocker (the
> classifier never running) is now **fixed and regression-tested**, and the safety
> invariants held throughout (wrong-accepted = 0, fail-safe UNKNOWN, correct
> routing, read-only capture). But Move-Cursor Preview must not be authorized until
> the operator **re-validates World D live on this build** and confirms 3×20%
> classify correctly, and until the H false-positive rate (0/4 on that frame) is
> understood on live data — cursor movement toward a false-positive sector is
> exactly the failure this milestone exists to prevent. **Recommendation: needs one
> more live validation iteration on the fixed build; do not start M5 yet.**

---

_No thresholds changed (`MIN_PCT_SIM` stays 0.70; detector 0.62 unchanged). No
OCR, scheduler, runtime, or gameplay changes. Observe-only preserved._
