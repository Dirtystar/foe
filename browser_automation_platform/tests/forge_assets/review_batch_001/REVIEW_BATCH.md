# Review batch 001 — active-learning selection (observe-only, no retrain)

Corpus analysed: **18** screenshots · clusters: **13** · requested: **50** · selected: **18**.

The detector, classifier, and thresholds were used **read-only** — nothing was modified or retrained. Selection maximises expected information gain while capping near-duplicate clusters (it is deliberately NOT the top-N by uncertainty).

> **Note:** The committed screenshot corpus is smaller than the requested batch size; the batch contains every diversity-selected frame available. Re-run against a larger keep dataset to fill a full batch.

## How to review

Open this folder in the existing Review Mode and label each frame (left-click add, right-click remove, keys 1-5 set 20/40/60/80/100, autosave):

```
python -m bap.gui.forge_review tests/forge_assets/review_batch_001/frames \
    --labels tests/forge_assets/review_batch_001/labels.json \
    --calibration tests/forge_assets/review_batch_001/calibration.json
```

## Scoring factors (weights)

- **unknown_pct** (3.0) — unknown percentage(s) — detected badge the classifier could not read
- **uncertain** (2.5) — uncertain classifier — similarity near the accept bar / close top-2 classes
- **stage_disagree** (2.0) — detector-stage disagreement — colour prior fires but template rejects
- **near_thresh_reject** (1.5) — near-threshold rejects — candidates just under the accept bar (possible FP/FN)
- **competing** (1.0) — multiple competing accepted candidates
- **rejected** (0.6) — high rejected-candidate count
- **candidates** (0.4) — high stage-1 candidate count
- **rare_background** (1.5) — rare background — battle-map colour far from the corpus norm
- **rare_scale** (2.0) — unusual capture scale/resolution (under-represented)

## Selected frames — why each was chosen

| # | frame | source | world | res | cluster | score | detector (cand/conf/rej/acc/unk) | why |
|---|---|---|---|---|---|---|---|---|
| 1 | F_20260712_231811_628314.png | live_review | F | 1600x900 | 11 | 10.2045 | 87/2/85/2/1 | uncertain classifier — similarity near the accept bar / close top-2 classes; unusual capture scale/resolution (under-represented); detector-stage disagreement — colour prior fires but template rejects |
| 2 | frame_000183.png | grading | — | 1920x1080 | 2 | 8.3204 | 64/10/58/6/5 | unknown percentage(s) — detected badge the classifier could not read; uncertain classifier — similarity near the accept bar / close top-2 classes; detector-stage disagreement — colour prior fires but template rejects |
| 3 | frame_000070.png | grading | — | 1920x1080 | 1 | 5.8478 | 54/8/47/7/6 | unknown percentage(s) — detected badge the classifier could not read; multiple competing accepted candidates; detector-stage disagreement — colour prior fires but template rejects |
| 4 | frame_000596.png | grading | — | 1920x1080 | 8 | 5.8443 | 31/4/27/4/3 | uncertain classifier — similarity near the accept bar / close top-2 classes; unknown percentage(s) — detected badge the classifier could not read; multiple competing accepted candidates |
| 5 | frame_000460.png | grading | — | 1920x1080 | 6 | 5.6675 | 100/0/100/0/0 | detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 6 | H_20260712_231142_650431.png | live_review | H | 1920x912 | 12 | 5.6358 | 96/2/94/2/1 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); high rejected-candidate count |
| 7 | H_20260712_231606_382772.png | live_review | H | 1920x912 | 12 | 5.6358 | 96/2/94/2/1 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); high rejected-candidate count |
| 8 | frame_000565.png | grading | — | 1920x1080 | 8 | 5.2256 | 20/4/16/4/3 | uncertain classifier — similarity near the accept bar / close top-2 classes; unknown percentage(s) — detected badge the classifier could not read; multiple competing accepted candidates |
| 9 | frame_000346.png | grading | — | 1920x1080 | 4 | 4.0962 | 66/0/66/0/0 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 10 | frame_000021.png | grading | — | 1920x1080 | 0 | 3.6166 | 31/6/26/5/4 | unknown percentage(s) — detected badge the classifier could not read; multiple competing accepted candidates; detector-stage disagreement — colour prior fires but template rejects |
| 11 | frame_000466.png | grading | — | 1920x1080 | 6 | 3.5717 | 64/0/64/0/0 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; high rejected-candidate count |
| 12 | frame_000302.png | grading | — | 1920x1080 | 3 | 3.4473 | 61/4/58/3/1 | detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm; unknown percentage(s) — detected badge the classifier could not read |
| 13 | frame_000654.png | grading | — | 1920x1080 | 10 | 3.3084 | 14/4/11/3/3 | unknown percentage(s) — detected badge the classifier could not read; rare background — battle-map colour far from the corpus norm; multiple competing accepted candidates |
| 14 | frame_000348.png | grading | — | 1920x1080 | 5 | 2.8882 | 54/1/53/1/1 | detector-stage disagreement — colour prior fires but template rejects; unknown percentage(s) — detected badge the classifier could not read; rare background — battle-map colour far from the corpus norm |
| 15 | frame_000486.png | grading | — | 1920x1080 | 7 | 1.974 | 36/1/35/1/1 | detector-stage disagreement — colour prior fires but template rejects; unknown percentage(s) — detected badge the classifier could not read; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 16 | frame_000536.png | grading | — | 1920x1080 | 7 | 1.7404 | 34/2/32/2/1 | unknown percentage(s) — detected badge the classifier could not read; detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 17 | frame_000650.png | grading | — | 1920x1080 | 9 | 1.7276 | 35/3/34/1/1 | unknown percentage(s) — detected badge the classifier could not read; rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 18 | frame_000687.png | grading | — | 1920x1080 | 9 | 0.7013 | 16/0/16/0/0 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; high rejected-candidate count |

Regenerate against a larger dataset: `python -m bap.forge.detection.active_learning <frames_dir> --n 50 --out <batch_dir>`.