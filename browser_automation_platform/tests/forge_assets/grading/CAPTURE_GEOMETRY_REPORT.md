# Test-Scan capture geometry & classification diagnosis

Response to the Windows capture-geometry review. Everything below is
**observe-only** — no clicking is performed or enabled.

Regression fixture: `frames/frame_000536.png` — a full raw capture containing the
Forge top bar (current weakening `16`), the whole visible map, on-map badges
(20 % and 40 %), and an open province panel. Reproduce with
`test_regression_full_capture_pipeline`.

## 1. One full raw capture, two explicit ROIs

Every Test Scan starts from one unmodified full capture and derives two ROIs, in
full-capture pixels:

| ROI | 1920×1080 fixture | Purpose |
|---|---|---|
| `weakening_roi` | `x678 y477 w56 h25` (calibrated) | current-weakening safety gate |
| `battle_map_roi` | `x0 y502 w1920 h578` (whole map below the top bar) | on-map badge detection |

The weakening ROI sits **above** the battle-map ROI, so the top-bar value is now
inside the analyzed area. The battle-map ROI spans the full width down to the
bottom — not an arbitrary lower rectangle. Both are drawn on the annotated output
only; analysis runs on the raw pixels.

Calibration is keyed by exact capture geometry (raw size + viewport + device
pixel ratio + zoom when the browser reports them), so a region calibrated for a
full-desktop screenshot is never silently reused for a page-content capture that
happens to share a pixel size.

## 2. Coordinate contract

Detector output is expressed in full-capture pixels and carries both boxes:

```
badge: center_full [945,714]  bbox_full [925,694,40,40]  bbox_roi [925,192,40,40]
```

`bbox_roi = bbox_full − battle_map_roi origin (y=502)`, applied **exactly once**
(`694 − 502 = 192`). `test_coordinate_contract_offset_applied_exactly_once` locks
this in. The proposed click point is `click_point_full`, in the same space.

## 3. Why some badge percentages classify and others do not

On the fixture the classifier accepts the two clean on-map badges and rejects the
rest, recording a reason per candidate:

| candidate (full px) | predicted | similarity | result |
|---|---|---|---|
| 945, 714 | 20 % | 0.58 | accepted (≥ 0.55) |
| 1201, 917 | 40 % | 0.94 | accepted |
| 1384, 782 (open-panel pill) | 20 % | 0.28 | **UNKNOWN** — below bar |

Root cause of the `?` percentages the reviewer saw:

- **Scale / crop misalignment.** The classifier compares a fixed-geometry patch
  (`percent_patch`, pixel offsets tuned on the grading crops) against labelled
  exemplars. On badges rendered at a different on-map scale — and on the *panel*
  pill, whose layout differs from an on-map pill — the patch does not line up, so
  cosine similarity drops below the acceptance bar.
- **Live-capture rendering.** A page-content capture at a different device pixel
  ratio / zoom than the exemplar frames shifts glyph size and anti-aliasing,
  lowering similarity further.

The fix is **not** to silently trust a low-confidence guess. A prediction is
accepted only at similarity ≥ `MIN_PCT_SIM` (0.55); otherwise the badge stays
UNKNOWN and the strategy ignores it with a reason. Improving *recall* of the
percentage classifier (more exemplars, scale-robust patch) is a follow-up, not
part of this observe-only fix, and detector localization thresholds were left
untouched as instructed.

## 4. No false panel box

The province panel is no longer inferred from a bare emblem score at a fixed
point. It is reported open only when that spot **both** scores as an emblem and
classifies as a confident percentage. On the fixture the fixed pill spot scores
0.34 → `panel_present = false`, no box drawn, score kept in `scan.json` for
diagnosis. On empty terrain it is likewise suppressed
(`test_no_false_panel_on_empty_terrain`).

## 5. Artifacts

`save_scan` writes `01_full_raw_capture.png`, `02/03_weakening_roi_raw/processed`,
`04_battle_map_roi_raw`, `05_badge_candidate_overlay`, `06_badge_classifier_crops/`,
`07_final_annotated_output`, and `scan.json` (geometry, both ROIs, all stage-1
candidates + scores + reasons, classifier results, panel state, weakening read,
final decision).
