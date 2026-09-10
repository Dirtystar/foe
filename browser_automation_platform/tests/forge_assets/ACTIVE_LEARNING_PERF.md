# Active-learning selector — performance

Profiling and the fast analysis mode for `bap.forge.detection.active_learning`.
The detector, classifier, and thresholds are unchanged — the fast mode adds
caching/checkpoints/progress and skips work that does not affect ranking.

## Where the time goes (per frame)

`cProfile` of `detector.scan()` on a live H frame (1595×885 battle-map ROI, 96
stage-1 candidates):

| function | time | share |
|---|---|---|
| `cv2.matchTemplate` (10 064 masked calls) | **6.81 s** | **90 %** |
| `np.nan_to_num` (per match result) | 0.39 s | 5 % |
| `cv2.resize` (template/mask per candidate) | 0.17 s | 2 % |
| everything else | ~0.2 s | 3 % |
| **total `detector.scan`** | **7.5 s** | |

matchTemplate dominates: 96 candidates × 37 templates × 3 scales masked
`TM_CCOEFF_NORMED`.

## Why template matching cannot simply be cut

The information-gain factors depend on the per-candidate emblem scores
(confirmed / near-threshold / stage-disagreement), so changing the scores changes
the ranking. Measured, on the 18-frame benchmark:

- **1 scale instead of 3** → 2.74× faster, but the **selection changes**
  (diverges at rank 5). Rejected.
- **Whole-ROI precompute** (match each template once over the ROI, read candidate
  maxima) → **6× slower** (46.7 s): masked matching can't use the DFT path, and
  the ROI is far larger than the union of candidate windows. Rejected.
- No exact-duplicate templates exist to drop for free.

So the per-candidate masked match is already near-optimal, and its cost is
irreducible **without changing the selection**.

## Fast analysis mode (identical selection)

`analyze(..., cache_dir=…, progress=…)`:

1. **Lean features** — computes ranking features from `detector.scan` +
   percentage classification only, skipping the weakening OCR, the province-panel
   probe, and target selection (none feed a factor). Byte-identical features.
2. **Per-frame cache / checkpoints** — each frame's features are keyed by content
   hash + detector/classifier signature and written immediately. A re-run or a
   resume-after-interrupt reuses completed frames; a `KeyboardInterrupt` now loses
   at most the in-flight frame.
3. **Progress reporting** — a per-frame `(done, total, file, cached, elapsed)`
   callback with ETA.

## Benchmark (before → after)

Measured on the 18 committed frames; the 236-frame corpus is those frames
replicated ×13.1, so the projection is exact for it.

| | 18 frames | 236 (projected) |
|---|---|---|
| **before** (full `build_scan` per frame) | 75.4 s | ~989 s (16.5 min) |
| **after — cold** (lean, no cache) | 72.5 s | ~951 s |
| **after — warm** (cache hit / resume) | 0.05 s | **~0.7 s** |

- **Cold first pass: ~4 % faster** — the lean path removes OCR/panel/select, but
  matchTemplate is 90 % and untouched, so the first scan of *new* frames is still
  compute-bound (~4 s/frame). This is the honest ceiling for identical output.
- **Warm: ~1376×** (989 s → 0.7 s). Any re-run — tuning weights, re-clustering,
  re-selecting, or resuming after an interrupt — is effectively instant.
- **Selection is byte-identical** to the previously committed
  `review_batch_001/manifest.json` (files **and** scores), verified in
  `test_active_learning.py`.

## Takeaway

The dominant cost (matchTemplate) is irreducible without changing which frames
are selected. The fast mode's value is therefore: run the expensive pass **once**,
with **progress** and **resumable checkpoints** so a 236-frame run never hangs
invisibly or loses work, and make every subsequent selection **instant** via the
cache. Reproduce: `python -m bap.forge.detection.active_learning <frames_dir>
--n 50 --out <dir>` (re-run to resume / reuse the cache).
