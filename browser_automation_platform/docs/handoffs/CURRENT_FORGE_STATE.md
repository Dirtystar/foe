# Current Forge state — handoff

_Living status doc. Concise and factual. Update it at each milestone._

## Product direction

**Forge of Empires Assistant** is the product; **BAP** is the internal engine
only. Optimize for Forge; avoid new generic frameworks.

## Safety state

**NO CLICK PERFORMED.** No clicking, keyboard, battle flow, R cadence, daily
counters, or licensing. The pipeline computes a would-click point and explains its
decision. The one output action is the M5A **Move Cursor Preview**: a manual,
operator-confirmed, one-shot cursor *move* to that point — strictly gated, never a
click, never automated or scheduler-triggered.

## Branch / commit

- Branch: `claude/browser-automation-architecture-5784h1`.
- Latest work: Milestone 5B (Live percentage-classifier hardening) — folding the
  reviewed live exemplars into the bank made the raw 1-NN wrong-accept two
  cross-scale crops at ~0.702 (combined wrong-accepted 0 → 2). Fix adds a
  **class-confirmed** acceptance gate (`PercentClassifier.confirmed`, ≥2 of top-3
  nearest exemplars agree) layered on top of the **unchanged** `MIN_PCT_SIM = 0.70`
  bar, applied in `scan` and `live_eval`; wrong-accepted is back to 0 with no
  threshold change. Root cause measured: live-capture scale gap + few-pixel centring
  sensitivity of the percent-patch cosine. Observe-only unchanged. See
  `LIVE_CLASSIFIER_HARDENING_REPORT.md`.
- Prior: Milestone 5A.1 (Real Windows browser geometry) — measures the
  Chrome window + content viewport (CDP window bounds + layout metrics, DPR derived)
  and an operator content-origin calibration keyed by geometry, so the M5A cursor
  preview can map raw→physical screen without guessing; `MainWindow._window_geometry`
  now returns a calibrated `WindowGeometry` (was `None`). Still manual, one-shot, no
  click. See `M5A1_WINDOWS_GEOMETRY_REPORT.md`.
- Prior: Milestone 5A (Manual Move Cursor Preview) — the first output action: a
  manual, confirmed, one-shot cursor MOVE to the validated would-click point that
  **never clicks** (`bap.forge.cursor`, `CursorPreviewPort` exposes only
  `move_to`). Strict manual gate + explicit image→screen coordinate contract +
  append-only `CURSOR_PREVIEW_ONLY` audit. See `M5A_CURSOR_PREVIEW_REPORT.md`.
- Prior: Milestone 4.16 (External Chrome Attach) — BAP can attach to an
  operator-launched Chrome over CDP (`bap.adapters.browser.cdp_attach_adapter`)
  as a read-only guest that never launches or closes Chrome; explicit
  `BrowserOwnership`; persisted `BrowserMode` (default Managed). See
  `EXTERNAL_CHROME_IMPLEMENTATION_REPORT.md`.
- Prior: Milestone 4.15 (one unified Dataset / Snapshot / Review workflow) — a
  single editable Reviewed Dataset (`bap.forge.dataset_store`) that every Review
  entry point edits; snapshots are immutable archives imported into it. See
  `docs/DATASET_WORKFLOW.md`.

## Milestones completed

- M1 World Manager (persistent worlds, hostname reattach, explicit browser
  lifecycle, provably read-only capture).
- M2 Labelling tool + 15-frame grading set.
- M3 Badge detector (colour prior + masked emblem template + NMS), percentage
  classifier (exemplar cosine, no OCR), evaluation harness, Vision Debugger.
- M3.5–3.7 Weakening region calibration, OCR reader + fail-safe gate, per-World
  temporal validation.
- M4 First deterministic decision slice (lowest allowed % → confidence → centre).
- M4.5 Multi-World Test Scan routing (explicit selector, live/offline split, Scan
  All), detector stage diagnostics.
- M4.6 Removed banner covering the top bar; live classifier diagnostics + contact
  sheet; Label-in-Review-Mode; Scan-All per-World artifacts.
- M4.7 Live-data re-evaluation (this handoff): unified dataset loader, LOFO
  evaluation, justified threshold changes, live exemplars.

## Current metrics (frame-grouped LOFO; see LIVE_VISION_REPORT.md)

- Localization combined: precision **0.81** (was 0.51), recall **0.92**,
  FP/frame **0.44**. Live-H/F precision **1.00**, recall **1.00**.
- Percentage classification: **0 wrong-accepted** across all sets. live-H 4/4;
  live-F UNKNOWN (safe, needs more F samples); historical mostly UNKNOWN
  cross-frame (scale-limited, safe).
- Full slice **wrong-accepted percentage = 0** on every set (the key safety metric).

## Key source paths

- Pipeline: `src/bap/forge/detection/scan.py` (`build_scan`, `annotate`,
  `save_scan`, `select_target`, `MIN_PCT_SIM=0.62`).
- Detector: `src/bap/forge/detection/detector.py` (`score_threshold=0.62`).
- Geometry/ROIs: `geometry.py`, `calibration.py`.
- Classifier: `classify.py` (`train_from_sources` folds grading + live).
- Dataset + eval: `dataset.py`, `live_eval.py` (`python -m bap.forge.detection.live_eval`).
- Datasets: `tests/forge_assets/grading/`, `tests/forge_assets/live_review/`.
- Reports: `LIVE_VISION_REPORT.md`, `grading/DETECTOR_DIAGNOSIS.md`,
  `grading/LIVE_SCAN_DIAGNOSIS.md`, `grading/CAPTURE_GEOMETRY_REPORT.md`.

## Known blockers

1. **live-F percentage classification** is UNKNOWN — only one F frame, no
   same-scale exemplar. Needs ≥ 1 more reviewed F scan.
2. **Colour-prior recall** misses 3 historical edge/banner badges (segmentation
   limit; deferred — would widen candidates).
3. **High-score historical false positives** (banners ~0.7–0.98) need
   shape/aspect handling, not a threshold.
4. **Centre-offset jitter** on live scale slightly lowers detected-centre
   classification; a scale-aware `percent_patch` would help.

## Next Windows test checklist (when testing resumes)

1. Re-run live H — confirm 2 badges, 0 false positives, 60 % classified + selected.
2. Capture 3–5 more **F** scans (and other Worlds) covering 20/40/60/80/100 so
   each class has ≥ 2 same-scale exemplars; review + commit as live ground truth.
3. Draw **Set Weakening Region** on the now-visible top bar; confirm the gate reads.
4. A red lava/volcano frame with **no** real badge → confirm no detection at 0.62.
5. A ≥-limit weakening frame → confirm STOP gate.
6. An open province-panel frame → confirm panel stays diagnostic-only (no map box).

## Testing

Targeted tests during development; full unit suite once per milestone
(`QT_QPA_PLATFORM=offscreen`). Do not rebuild existing architecture without a
demonstrated blocker.
