# Vision Validation — FAIL

- World: **H**  ·  source: LIVE capture  ·  `2026-08-03T15:02:03+00:00`
- Checks: ✅ 5 PASS · ⚠️ 4 WARNING · ❌ 1 FAIL · ℹ️ 36 INFO

## ✅ Capture — PASS

_The one raw capture the whole pipeline analyses._

| check | status | value | note |
|---|---|---|---|
| capture successful | ✅ PASS | yes | A single raw capture is the input to every downstream stage. |
| resolution | ℹ️ INFO | 1600×900 | Pixel size of the captured content viewport. |
| viewport | ℹ️ INFO | (not reported) | Browser CSS viewport; only reported by a live CDP capture. |
| DPR | ℹ️ INFO | (not reported) | Device-pixel-ratio; affects calibration keying. |
| zoom | ℹ️ INFO | (not reported) | Page zoom; a zoom change invalidates a calibrated ROI. |
| capture latency | ✅ PASS | 529 ms | Round-trip to obtain the read-only screenshot. |

## ❌ Weakening — FAIL

_The per-World safety gate that decides whether any target is actionable._

| check | status | value | note |
|---|---|---|---|
| ROI present | ❌ FAIL | no | The weakening ROI is the safety gate's only input. |
| ROI calibrated | ⚠️ WARNING | no (default/uncalibrated) | A calibrated ROI is keyed to this exact capture geometry. |
| OCR confidence | ⚠️ WARNING | 0.00 | The reader could not confidently read a number. |
| human-readable value | ℹ️ INFO | UNKNOWN | No confident value → treated as UNKNOWN (fail-safe). |
| history consistency | ℹ️ INFO | single frame | No prior reads for this World in this run — nothing to compare yet. |
| gate result | ⚠️ WARNING | UNKNOWN | UNKNOWN → no action; ≥ limit → STOP; confident below-limit → CONTINUE. |

- _ROI present_ — probable reason: no weakening region is defined for this capture geometry · **action: Run Set Weakening Region on the current top bar.**
- _ROI calibrated_ — probable reason: the ROI is a default guess, not calibrated for this resolution · **action: Run Set Weakening Region so the gate reads the real number.**
- _OCR confidence_ — probable reason: unreadable region (uncalibrated ROI, glare, or no number visible) · **action: Run Set Weakening Region; confirm the number is visible in the top bar.**
- _gate result_ — probable reason: weakening unreadable → fail-safe UNKNOWN · **action: Calibrate the ROI so the gate can read.**

## ✅ Battle Map — PASS

_Where badges are detected — the whole usable battleground._

| check | status | value | note |
|---|---|---|---|
| battle ROI | ℹ️ INFO | (0,54,1600,846) | The analysed map region, in full-capture pixels. |
| size | ℹ️ INFO | 1600×846 | Width × height of the map ROI. |
| coverage | ✅ PASS | 94% of frame | The ROI should cover the usable map, not a sub-rectangle. |
| geometry validity | ✅ PASS | valid | The ROI lies fully inside the capture. |
| coordinate mapping | ✅ PASS | full-image | Detector boxes are mapped back to full-capture pixels (ROI offset applied once). |

## ℹ️ Badge Detection — INFO

_Locating weakened-sector badges. Execution health is INFO; accuracy only PASSES against human ground truth (reviewed frames)._

| check | status | value | note |
|---|---|---|---|
| detector executed | ℹ️ INFO | yes | The detector completed without error (execution health, not accuracy). |
| candidate count | ℹ️ INFO | 491 | Stage-1 colour-prior candidates before template confirmation. |
| accepted count | ℹ️ INFO | 4 | Accepted badges after template + NMS — UNVERIFIED (not confirmed real without review). |
| rejected count | ℹ️ INFO | 487 | Candidates dropped (below template threshold or NMS-suppressed). |
| false panel overlay | ℹ️ INFO | none | Whether a province-panel overlay would be drawn (guarded). |
| per-stage timing (detection) | ℹ️ INFO | 56117 ms | Detection dominates the tick; measurement only. |
| accuracy (TP/FP/FN) | ℹ️ INFO | UNVERIFIED | Accepted candidates are not confirmed real without human ground truth. |

- _accuracy (TP/FP/FN)_ — probable reason: this is a live/unreviewed scan — accuracy cannot be graded · **action: Label this frame in Review Mode to measure TP/FP/FN against ground truth.**

## ⚠️ Classification — WARNING

_Reading each badge's percentage — accepted only above the similarity bar._

| check | status | value | note |
|---|---|---|---|
| 20% | ℹ️ INFO | 0 | Classified badges at this percentage. |
| 40% | ℹ️ INFO | 0 | Classified badges at this percentage. |
| 60% | ℹ️ INFO | 0 | Classified badges at this percentage. |
| 80% | ℹ️ INFO | 0 | No labelled exemplars exist for this class yet. |
| 100% | ℹ️ INFO | 0 | Classified badges at this percentage. |
| UNKNOWN | ⚠️ WARNING | 4 | Badges whose percentage stayed UNKNOWN (fail-safe, never guessed). |
| confidence histogram | ℹ️ INFO | [0.00-0.50]2 [0.50-0.70]2 [0.70-0.85]0 [0.85-1.01]0 | Nearest-exemplar similarity buckets; accept bar = 0.70. |
| nearest exemplar similarities | ℹ️ INFO | 0.66, 0.53, 0.41, 0.38 | Top nearest-exemplar cosine similarities across candidates. |

- _UNKNOWN_ — probable reason: no exemplar cleared the similarity bar · **action: Collect more reviewed live frames covering these classes.**

## ℹ️ Decision — INFO

_The deterministic, observe-only target choice and its safety gating._

| check | status | value | note |
|---|---|---|---|
| decision | ℹ️ INFO | UNKNOWN | The per-World gate outcome for this frame. |
| selected badge | ℹ️ INFO | none | No eligible badge — nothing would be selected. |
| ignored badges | ℹ️ INFO | 4 | Badges skipped (unknown % or disabled for this World), with recorded reasons. |
| decision explanation | ℹ️ INFO | percentages not available (classifier could not read them) detections shown for verification only | Human-readable reason for the selection. |
| would-click point | ℹ️ INFO | none | No target → no would-click point. |
| gate status | ℹ️ INFO | no target | Whether the would-click is gate-actionable. Nothing is ever clicked. |

## ℹ️ Performance — INFO

_Per-stage timing of this validation (measurement only — no optimisation)._

| check | status | value | note |
|---|---|---|---|
| capture | ℹ️ INFO | 0 ms | Frame decode / obtain. |
| detector | ℹ️ INFO | 56117 ms | Badge localization (dominant cost). |
| classifier | ℹ️ INFO | 137 ms | Percentage classification + panel check. |
| OCR | ℹ️ INFO | 0 ms | Weakening reader. |
| decision | ℹ️ INFO | 0 ms | Gate + target selection. |
| total | ℹ️ INFO | 56254 ms | Whole validation tick. |
| CPU | ℹ️ INFO | 1057% | Process CPU over the validation window. |
| RAM | ℹ️ INFO | (n/a) | Process resident memory. |
