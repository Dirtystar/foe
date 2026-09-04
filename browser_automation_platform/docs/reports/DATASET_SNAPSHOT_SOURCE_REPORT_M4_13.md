# Imported-Snapshot Dataset Source — Report (Milestone 4.13b)

_Observe-only. No thresholds changed, no retraining, no detector/classifier/OCR
change. This wires the repo-root `dataset/` (where "Import Snapshot into Dataset"
writes) into the production classifier and evaluation loader as a first-class
reviewed source, and reports the state of the committed live H snapshot._

Branch `claude/browser-automation-architecture-5784h1`. Committed data inspected:
`dataset/frames/2026-08-04_17-58-59_H.png`, `dataset/labels.json`,
`dataset/imported_meta/2026-08-04_17-58-59_H.json`, `VISION_VALIDATION_REPORT_H2.md`,
`VISION_VALIDATION_REPORT_D2.md`.

---

## ⚠️ Headline finding — the committed H snapshot is NOT reviewed

The imported label is **unreviewed** and its badges are **unclassified**:

```json
// dataset/labels.json → 2026-08-04_17-58-59_H.png
"reviewed": false,
"badges": [ {"cx":1059,"cy":806,"pct":null},
            {"cx":1031,"cy":797,"pct":null},
            {"cx":913,"cy":749,"pct":null} ],
"weakening": null
```

Those three badges are the **detector's own accepted detections**, seeded into the
snapshot at save time — not human ground truth. The pipeline's standing rule is
"only **reviewed** frames count as ground truth" (`dataset._load` and
`classify._examples_from` both skip `reviewed == false`). Therefore this frame,
as committed, contributes **no ground truth and no training exemplars**. It needs
a Review Mode pass (assign 20/40/60/80/100 to the real badges, remove any false
positive, mark reviewed) before it counts. The infrastructure below makes that
review "just work" the moment it is done.

> Two of the three seeds — (1059,806) and (1031,797) — are 28 px apart, likely a
> double-detection of one badge (or two adjacent sectors). Only human review can
> resolve that; it is exactly what Review Mode is for.

---

## 1. Did the loader/classifier discover `dataset/`? — No (now fixed)

**Before:** classifier sources were `grading, live_review, review_batch_002`; the
eval loader's sources were `historical, live, review_batch_002`. The repo-root
`dataset/` was **not** discovered by either.

**Change (first-class source, dedup, sources preserved, no threshold change):**
- `classify.default_snapshot_dataset_dir()` — walks up from the module to find the
  repo-root `dataset/` (cwd-independent), like the M4.12 assets-root fix.
- `classify.default_label_sources()` now appends `dataset/` (grading / live_review /
  review_batch_002 preserved).
- `dataset.load_snapshot_dataset()` + `dataset.load_all(..., snapshots=…)` load
  `dataset/` **last**, then de-duplicate by image content hash so an identical
  frame is never double-counted (the reviewed copy wins).

**After:** classifier sources are `grading, live_review, review_batch_002, dataset`;
`default_snapshot_dataset_dir()` resolves the repo `dataset/`.

## 2. Is the new H snapshot loaded? — No (because it is unreviewed)

`load_snapshot_dataset()` returns **0** samples and `load_all()` still yields the
**same 66 reviewed frames** as before (`historical 14 + live 2 + review_batch_002
50`). The H frame is correctly excluded by the reviewed-gate. Adding the source did
**not** weaken that gate — an unreviewed import is invisible to evaluation, which
is the safe behaviour.

## 3. Ground-truth badge count / classes — none yet (unreviewed)

- Human ground truth: **unavailable** (frame not reviewed; percentages `null`).
- Detector output on the frame (INFO only — not scored against GT): 351 stage-1
  candidates → **3 accepted** at (1059,806), (1031,797), (913,749).

## 4. Detector TP / FP / FN — cannot be scored (no ground truth)

Without a reviewed label there is no truth set to match against, so TP/FP/FN are
**undefined** for this frame. Reported instead: **3 detections accepted**; whether
they are true badges or false positives is exactly what review must decide. (The
paired H2 validation report, a *different* Aug-3 capture, showed 4 accepted / all
UNKNOWN — also unreviewed.)

## 5. Classification correct / UNKNOWN / wrong

On the committed frame, the classifier (unchanged, 154 exemplars) reads all three
detections as **UNKNOWN** — nearest-exemplar similarities **0.45 / 0.35 / 0.33**,
all below the 0.70 accept bar, so none is accepted:

| metric | value |
|---|---|
| classified (accepted %) | 0 |
| UNKNOWN | 3 |
| **wrong-accepted** | **0** |

"Correct/wrong" cannot be computed without GT; the safety-relevant number,
**wrong-accepted = 0**, holds (the accept gate rejects every sub-0.70 read).

## 6. Effect on combined metrics — none

- **Classifier unchanged:** 154 exemplars before and after (the unreviewed frame
  supplies zero classified badges). The bundled classifier is byte-for-byte the
  same model.
- **Evaluation set unchanged:** 66 reviewed frames (the H frame is excluded).
- Frame-grouped LOFO is therefore **deterministically identical** to the M4.12
  reproduction (same 66-frame set, same 154-exemplar classifier): historical /
  review_batch_002 / live-H / live-F / combined all reproduce M4.12's numbers, with
  **wrong-accepted = 0 on every set**.
  <!--EVAL_REPRO-->**Confirmed this session** — `live_eval` reproduced the M4.12
  numbers exactly: combined 156 truth badges · 134 TP / 22 FN / 70 FP · correct_pct
  62 · unknown 72 · **wrong_accepted 0**; review_batch_002 124/105/19/65, correct 50,
  **wrong 0**; live-H 2/2, **wrong 0**; live-F 2/2, **wrong 0**. The `dataset/`
  addition changed nothing loaded.<!--/EVAL_REPRO-->
- **Wrong-accepted percentage across all sets: 0** (unchanged, the key safety metric).

## 7. Regression test (future imports auto-discover)

`tests/unit/forge/test_snapshot_dataset_source.py` pins the contract:
- the repo `dataset/` is discovered and is a classifier source (existing sources
  preserved);
- a **reviewed** imported snapshot loads (`load_snapshot_dataset` / `load_all`),
  with de-dup keeping it once;
- an **unreviewed** snapshot is skipped (mirrors the committed H frame);
- an absent `dataset/` is a no-op.

So the next time the operator imports a **reviewed** snapshot into `dataset/`, it
is automatically part of both training and evaluation — no code change needed.

## 8. Recommendation

1. **Review the committed H snapshot** in Review Mode: confirm/remove the three
   detections, assign percentages to the real badges, mark reviewed, and re-commit
   `dataset/labels.json`. It then counts automatically (test-proven).
2. Keep importing reviewed live frames to `dataset/` — especially any real 40% /
   80% badges (80% still has zero exemplars anywhere).
3. No retraining was done and none is warranted from an unreviewed frame ("do not
   retrain blindly"). Re-run `python -m bap.forge.detection.live_eval` after the
   frame is reviewed to measure its true effect.

_Observe-only preserved; `MIN_PCT_SIM` stays 0.70; detector 0.62 unchanged._
