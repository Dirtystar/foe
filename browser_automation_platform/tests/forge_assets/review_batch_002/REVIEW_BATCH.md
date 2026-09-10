# Review batch 001 — active-learning selection (observe-only, no retrain)

Corpus analysed: **236** screenshots · clusters: **66** · requested: **50** · selected: **50**.

The detector, classifier, and thresholds were used **read-only** — nothing was modified or retrained. Selection maximises expected information gain while capping near-duplicate clusters (it is deliberately NOT the top-N by uncertainty).

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
| 1 | frame_000299.png | corpus | — | 1920x1080 | 27 | 5.1757 | 277/7/270/7/7 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); multiple competing accepted candidates |
| 2 | frame_000390.png | corpus | — | 1920x1080 | 34 | 4.7274 | 190/4/186/4/4 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm |
| 3 | frame_000523.png | corpus | — | 1920x1080 | 41 | 4.6408 | 283/5/280/3/3 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); high rejected-candidate count |
| 4 | frame_000713.png | corpus | — | 1920x1080 | 62 | 4.2201 | 145/6/139/6/6 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 5 | frame_000619.png | corpus | — | 1920x1080 | 53 | 3.9561 | 170/5/165/5/5 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 6 | frame_000608.png | corpus | — | 1920x1080 | 50 | 3.8164 | 124/6/118/6/6 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; multiple competing accepted candidates |
| 7 | frame_000614.png | corpus | — | 1920x1080 | 51 | 3.7919 | 159/8/152/7/7 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); multiple competing accepted candidates; detector-stage disagreement — colour prior fires but template rejects |
| 8 | frame_000133.png | corpus | — | 1920x1080 | 8 | 3.7871 | 118/5/114/4/4 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 9 | frame_000563.png | corpus | — | 1920x1080 | 46 | 3.7474 | 170/4/166/4/4 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 10 | frame_000583.png | corpus | — | 1920x1080 | 48 | 3.6856 | 118/2/116/2/2 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 11 | frame_000443.png | corpus | — | 1920x1080 | 39 | 3.5533 | 173/2/171/2/2 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm |
| 12 | frame_000809.png | corpus | — | 1920x1080 | 64 | 3.4853 | 153/6/148/5/5 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 13 | frame_000592.png | corpus | — | 1920x1080 | 49 | 3.4386 | 197/3/194/3/3 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm |
| 14 | frame_000284.png | corpus | — | 1920x1080 | 22 | 3.4188 | 154/3/151/3/3 | detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 15 | frame_000393.png | corpus | — | 1920x1080 | 36 | 3.4146 | 182/2/180/2/2 | detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 16 | frame_000217.png | corpus | — | 1920x1080 | 15 | 3.3948 | 136/7/131/5/5 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 17 | frame_000330.png | corpus | — | 1920x1080 | 31 | 3.3946 | 221/1/220/1/1 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); high rejected-candidate count |
| 18 | frame_000560.png | corpus | — | 1920x1080 | 44 | 3.3816 | 93/3/90/3/3 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 19 | frame_000352.png | corpus | — | 1920x1080 | 32 | 3.3785 | 148/2/146/2/2 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 20 | frame_000017.png | corpus | — | 1920x1080 | 0 | 3.3776 | 84/3/81/3/3 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 21 | frame_000762.png | corpus | — | 1920x1080 | 63 | 3.3587 | 125/9/117/8/8 | multiple competing accepted candidates; rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 22 | frame_000537.png | corpus | — | 1920x1080 | 42 | 3.2375 | 122/0/122/0/0 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 23 | frame_000181.png | corpus | — | 1920x1080 | 12 | 3.2118 | 124/6/120/4/4 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 24 | frame_000544.png | corpus | — | 1920x1080 | 43 | 3.1921 | 125/3/122/3/3 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 25 | frame_000315.png | corpus | — | 1920x1080 | 28 | 3.1577 | 122/2/120/2/2 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 26 | frame_000441.png | corpus | — | 1920x1080 | 38 | 3.1243 | 130/2/128/2/2 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm |
| 27 | frame_000688.png | corpus | — | 1920x1080 | 60 | 3.0557 | 105/4/101/4/4 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 28 | frame_000019.png | corpus | — | 1920x1080 | 1 | 3.0299 | 116/2/114/2/2 | near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects |
| 29 | frame_000241.png | corpus | — | 1920x1080 | 18 | 2.9796 | 108/3/105/3/3 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 30 | frame_000642.png | corpus | — | 1920x1080 | 55 | 2.9764 | 126/3/123/3/3 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 31 | frame_000282.png | corpus | — | 1920x1080 | 21 | 2.9734 | 157/1/156/1/1 | detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 32 | frame_000288.png | corpus | — | 1920x1080 | 24 | 2.9364 | 116/4/113/3/3 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 33 | frame_000195.png | corpus | — | 1920x1080 | 14 | 2.9318 | 109/4/105/4/4 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 34 | frame_000303.png | corpus | — | 1920x1080 | 26 | 2.9285 | 124/4/121/3/3 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 35 | frame_000060.png | corpus | — | 1920x1080 | 4 | 2.8949 | 129/6/125/4/4 | detector-stage disagreement — colour prior fires but template rejects; rare background — battle-map colour far from the corpus norm; multiple competing accepted candidates |
| 36 | frame_000389.png | corpus | — | 1920x1080 | 33 | 2.8749 | 135/1/134/1/1 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 37 | frame_000777.png | corpus | — | 1920x1080 | 65 | 2.8027 | 160/2/158/2/2 | detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN); rare background — battle-map colour far from the corpus norm |
| 38 | frame_000175.png | corpus | — | 1920x1080 | 11 | 2.7762 | 111/5/107/4/4 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; multiple competing accepted candidates |
| 39 | frame_000158.png | corpus | — | 1920x1080 | 10 | 2.7732 | 110/1/109/1/1 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 40 | frame_000074.png | corpus | — | 1920x1080 | 6 | 2.6576 | 106/2/104/2/2 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 41 | frame_000035.png | corpus | — | 1920x1080 | 3 | 2.6523 | 108/1/107/1/1 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 42 | frame_000083.png | corpus | — | 1920x1080 | 7 | 2.6417 | 106/4/102/4/4 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 43 | frame_000219.png | corpus | — | 1920x1080 | 16 | 2.4757 | 83/3/80/3/3 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 44 | frame_000326.png | corpus | — | 1920x1080 | 30 | 2.4757 | 115/0/115/0/0 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 45 | frame_000287.png | corpus | — | 1920x1080 | 23 | 2.2821 | 98/4/95/3/3 | rare background — battle-map colour far from the corpus norm; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 46 | frame_000662.png | corpus | — | 1920x1080 | 59 | 2.1145 | 79/6/74/5/5 | rare background — battle-map colour far from the corpus norm; multiple competing accepted candidates; detector-stage disagreement — colour prior fires but template rejects |
| 47 | frame_000238.png | corpus | — | 1920x1080 | 17 | 2.1106 | 106/0/106/0/0 | rare background — battle-map colour far from the corpus norm; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 48 | frame_000200.png | corpus | — | 1920x1080 | 13 | 2.0577 | 101/11/94/7/7 | multiple competing accepted candidates; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |
| 49 | frame_000036.png | corpus | — | 1920x1080 | 2 | 1.7841 | 71/8/64/7/7 | multiple competing accepted candidates; near-threshold rejects — candidates just under the accept bar (possible FP/FN); detector-stage disagreement — colour prior fires but template rejects |
| 50 | frame_000070.png | corpus | — | 1920x1080 | 5 | 1.6938 | 75/8/68/7/7 | multiple competing accepted candidates; detector-stage disagreement — colour prior fires but template rejects; near-threshold rejects — candidates just under the accept bar (possible FP/FN) |

Regenerate against a larger dataset: `python -m bap.forge.detection.active_learning <frames_dir> --n 50 --out <batch_dir>`.