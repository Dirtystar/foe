# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Milestone 5A.1: Real Windows browser geometry (no click)

Closes the M5A gap where `MainWindow._window_geometry` returned `None`, so the
cursor-preview gate always blocked with "window geometry unavailable". Measures the
real Chrome/Chromium window + web-content viewport so the coordinate contract can
map raw screenshot → physical screen without guessing. **Clicking remains
unimplemented**; the calibration overlay reads two operator clicks on BAP's own
window and sends nothing to Chrome. See `M5A1_WINDOWS_GEOMETRY_REPORT.md`.

### Added

- **`bap.forge.cursor.window_geometry`**:
  - `measure_via_cdp(send, …)` — window rect + identity + state from
    `Browser.getWindowForTarget`/`getWindowBounds`, viewport from
    `Page.getLayoutMetrics`, **DPR derived** from capture÷viewport (no
    `Runtime.evaluate`), zoom from the visual viewport. `send` is injected (fake in
    tests).
  - `ContentOriginCalibration` + `CalibrationKey` — persisted content rectangle
    (physical px) keyed by browser mode, endpoint/profile, capture, viewport, DPR,
    zoom, monitor scale, monitor; **never reused when any key changes**.
  - `resolve_native_window` — unique CDP↔native association; **ambiguous or missing
    blocks** (no title/process guessing).
  - `build_window_geometry` — merges measurement + content origin; returns
    `(None, "content_origin_unavailable")` when unknown.
- **`WindowGeometry`** gains a measured/calibrated **`content_rect`** (physical px)
  plus `source`, `native_window_id`, `windows_dpi`, `measured_at`; `image_to_screen`
  maps directly across the content rect when present (absorbing DPR, title bar,
  toolbar, monitor scale), and `identity()` includes them for staleness.
- **Vision Debugger**: a **Set Browser Content Origin** action (a translucent,
  BAP-owned overlay — `gui/cursor_calibration.py` — where the operator clicks the
  content area's corners; no input to Chrome); the confirmation dialog now shows the
  browser window id + rect, content rect, DPR, Windows scaling, and whether geometry
  is measured or operator-calibrated; a blocked "no geometry" preview points to the
  calibration action.
- **MainWindow** builds a calibrated `WindowGeometry` from the persisted content
  origin for the current geometry key (and re-reads it at move time, so a changed
  viewport/DPR/zoom invalidates it); `_window_geometry` no longer returns a
  hard-coded `None`.
- Tests (25): CDP measurement + derived DPR + maximized; calibration persistence +
  invalidation; native-window association (unique/ambiguous/missing); calibrated
  transform at 100/125/150 % scaling, second monitor, negative coords; move-time
  staleness (moved/resized/viewport/DPR/zoom) blocks; one valid request → `move_to`
  once (External + Managed); debugger calibration action + MainWindow geometry build.

### Limitations

- Live CDP/Win32 measurement plumbing is integration-only and unverified in the
  headless container; the operator content-origin calibration is the tested,
  reliable path. A pure window *drag* needs live re-measurement (the staleness logic
  is complete and tested); a live desktop target overlay was omitted (cross-DPI
  placement would itself be subject to the scaling under test).

## [Unreleased] — Milestone 5A: Manual Move Cursor Preview (one-shot, no click)

The first real **output** action: a manual, operator-confirmed, one-shot cursor
**move** to the validated would-click point. **Clicking is not implemented** — the
only output method anywhere is `CursorPreviewPort.move_to`; there is no click,
keyboard, drag, or scroll path. A coordinate-contract + safety-validation
milestone. Detector / classifier / OCR / thresholds unchanged. See
`M5A_CURSOR_PREVIEW_REPORT.md`.

### Added

- **`bap.forge.cursor`** package:
  - `port.CursorPreviewPort` — a one-method (`move_to`) boundary, separate from the
    generic action engine, plus `FORBIDDEN_INPUT_METHODS` (asserted absent by tests).
  - `geometry` — the explicit **image→screen coordinate contract** (raw px →
    viewport CSS → content CSS → screen logical → Windows physical), applying the
    capture/DPR scale and the monitor scale exactly once, preserving negative
    multi-monitor coordinates, with a full `CoordinateTrace`.
  - `preview` — the **strict manual gate**: enabled, owned/attached window, fresh
    live scan, unchanged World+tab, target exists, confident %, weakening CONTINUE,
    inside viewport, not stale (≤5 s default), geometry available and unchanged.
    First failure returns the exact reason; never guesses a coordinate.
  - `controller` — session enable (disabled by default, never persisted → resets
    each launch), two-step evaluate→confirm→**one-shot** move, re-evaluation at
    move time, and audit.
  - `audit` — append-only `CURSOR_PREVIEW_ONLY` JSONL with `no_click: true`, the
    coordinate trace, window geometry, and safety values.
  - `context` — Qt-free bridge that builds a `PreviewRequest` from live getters
    (so a World switched while the dialog is open is caught).
- **`bap.adapters.cursor`**: `FakeCursorPreview` (tests) and `WindowsCursorPreview`
  (Win32 `SetCursorPos`, movement only, DPI-aware; unavailable off Windows).
- **Vision Debugger**: a clearly-separated, warning-styled **Cursor Preview**
  panel — "Cursor Preview: DISABLED" → "Enable for this session" → "Preview Cursor
  Target" → a Cancel-default confirmation dialog (no Enter/shortcut, Escape
  cancels) → "Cursor moved — NO CLICK PERFORMED". Offered only for a fresh live
  scan; Scan All / offline / scheduler have no path to movement.
- Tests (47): coordinate contract (100 %/125 % scaling, two monitors, negative
  coords, DPR, capture≠viewport), every gate condition, controller one-shot +
  audit + re-eval, adapter surface (no click/keyboard), and the debugger UI flow.

### Limitations

- Live window-geometry acquisition is not automated; `MainWindow._window_geometry`
  returns `None` by default, so the gate **safely refuses to move** until a
  measured/calibrated `WindowGeometry` is supplied on Windows (a documented M5A
  follow-up). No real-cursor verification is possible in the headless container.

## [Unreleased] — Milestone 4.16: External Chrome Attach (observe-only)

Adds a second browser mode: BAP can **attach to an operator-launched Chrome over
CDP** and observe the Forge tabs already open, instead of always launching and
owning its bundled Chromium. Strictly observe-only (no click / keyboard / cursor /
navigation / gameplay). **Managed Chromium stays the default**, so existing
installs, Worlds, settings, tests, and CLI entry points are unchanged. See
`EXTERNAL_CHROME_IMPLEMENTATION_REPORT.md`.

### Added

- **`bap.adapters.browser.cdp_attach_adapter`** — `CdpAttachBrowserManager`, a
  read-only CDP guest (`BrowserPort` + tab discovery/adoption): `start()` connects
  via `connect_over_cdp` (injectable), `stop()` **disconnects only and never closes
  Chrome**, `open_tab`/`navigate` are refused and `close_tab` is a no-op. Plus
  `probe_cdp()` (driver-free `GET /json/version` reachability), `normalize_endpoint`,
  `is_localhost_endpoint`.
- **`bap.forge.browser_settings`** — persisted `BrowserMode` (Managed / External),
  `cdp_endpoint`, `chrome_path`, and the copyable Windows launch command. Default
  Managed; a missing file is never an error (no migration needed).
- **Explicit ownership** — `BrowserOwnership` (`MANAGED` / `EXTERNAL`);
  `BrowserPort.ownership` (default MANAGED, all existing adapters unchanged);
  `BrowserController.ownership` / `owns_process`.
- **Worlds page** — a **Browser mode** selector and, in External mode, a **CDP
  endpoint** field, **Test Connection**, **Attach Chrome**, **Disconnect**, a live
  status line, a non-localhost warning, and the copyable launch command (no "Open
  Browser" button in External mode — BAP does not open the operator's Chrome).
- Capture provenance: `CaptureGeometry` gains `browser_mode` / `cdp_endpoint`, and
  External Chrome is kept in a separate calibration namespace (`ext:` marker in the
  key; Managed keys byte-identical). Snapshot metadata gains `browser_mode`,
  `browser_name`, `cdp_endpoint`, `zoom` (older snapshots still load).
- Tests (34 new/changed): `test_cdp_attach_adapter.py`, `test_browser_settings.py`,
  `test_external_lifecycle.py`, `test_external_chrome_ui.py`, plus additions to
  `test_browser_controller.py`, `test_snapshots.py`, `test_capture_geometry.py`.
  Faithful fake CDP adapters (injected `connect`/`fetch`) keep the unit suite
  Chrome-free.

### Changed

- `gui_main` selects the browser adapter from the persisted mode (External →
  `CdpAttachBrowserManager`, else the managed attended adapter). No silent fallback
  between modes.
- External-Chrome exit **disconnects but never closes Chrome** (no "keep the browser
  open" prompt — there is no BAP-owned browser); Stop automation never disconnects.
- `testscan.scan_world` / `scan_all_attached` thread capture provenance
  (`geometry_meta`) onto the geometry.

### Limitations

- Browser-mode change applies on the **next launch** (persisted + restart note); the
  running adapter is not hot-swapped, for observe-only safety.
- viewport/DPR/zoom remain best-effort (`None` when unavailable), as in Managed mode.
- localhost only; no real-Chrome integration test in the normal unit suite (opt-in).

## [Unreleased] — Milestone 4.15: one unified Dataset / Snapshot / Review workflow (observe-only)

Collapses the fragmented review targets into **one editable Reviewed Dataset**.
Previously three places were independently editable in Review — an AppData
`forge/live_review` folder, each snapshot's own `labels.json`, and the repo-root
`dataset/` — so a review could land somewhere other than where the operator
expected (the root cause behind repeated "lost review" / "wrong labels.json"
incidents). Now there is exactly one obvious place reviewed data live, and every
Review entry point edits *that exact* dataset. Snapshots become immutable
archives; AppData is scratch only. No detector / classifier / threshold / OCR /
weakening / runtime / scheduler change; observe-only. See `docs/DATASET_WORKFLOW.md`.

### Added

- **`bap.forge.dataset_store`** — the single source of truth for the canonical
  Reviewed Dataset. `reviewed_dataset_dir()` resolves one location
  (`BAP_DATASET_DIR` → repo-root `dataset/` → `<app-data>/dataset`);
  `add_frame()` adds a capture (dedup by image hash, seeds detections as an
  **unreviewed** starting point, carries weakening, persists ROIs);
  `dataset_review_paths()`, `dataset_summary()`, `dataset_exists()`.
- Functional **Datasets page**: shows the dataset's exact path and frame /
  reviewed / labelled counts, with **Open Dataset in Review** and **Import
  snapshot…**.
- `tests/unit/forge/test_dataset_store.py` (resolution / override / dedup /
  detection-seeding / ROI persistence / summary / loader-discovers-the-same-dataset)
  and `tests/unit/gui/test_dataset_review_flow.py` (reviewing a snapshot edits the
  canonical dataset; import has no picker; empty dataset reports clearly).

### Changed

- **Every Review entry point edits the one dataset.** The Vision Debugger's *Label
  in Review Mode* adds the capture via `dataset_store.add_frame` and opens Review on
  the canonical dataset; snapshot *Open in Review* imports the snapshot into the
  dataset and reviews the imported copy; *Import into Dataset* no longer asks for a
  directory (there is only one).
- **`classify.default_snapshot_dataset_dir`** now delegates to
  `dataset_store.reviewed_dataset_dir()`, so the classifier/eval loader and the UI
  resolve to the same dataset.
- **`snapshots.import_into_dataset`** defaults its target to the canonical dataset
  and now merges the snapshot's ROIs into the dataset calibration on import
  (existing dataset entries win).
- Removed the deprecated `save_live_review_frame` / `_default_live_review_dir`
  AppData review-scratch path from the debugger.

## [Unreleased] — Milestone 4.14: reliable Review save workflow (observe-only)

Fixes a real Windows bug where Review-Mode edits — especially `reviewed=true` —
did not persist. Root cause: `reviewed=true` was only ever written by an implicit
branch of frame navigation (`badges present AND all classified AND you navigate`),
so it was **impossible for zero-badge negatives**, never fired on close-without-nav,
and had no visible control; edits also had no dirty state, no save confirmation,
and no visible labels path. Review persistence is now explicit, reliable, and
visible. No detector/classifier/OCR/threshold/runtime/snapshot/dataset-semantics
change; observe-only.

### Changed

- **Review Mode is explicit-save.** `LabelStore` gains an `autosave` flag (default
  `True`, so the grading labeler and all other callers are unchanged);
  `LabelSession._save()` respects it. Review Mode turns autosave **off** so edits
  reach disk only on an explicit Save — which makes Discard meaningful.
- **`forge_review`** adds: a **Save** button (atomic write to the exact launch
  labels path, with a visible `✅ Saved to: <full path> · <time>` confirmation), a
  **Reviewed** checkbox (works for zero-badge negatives; preserves labels; written
  on Save; never inferred from opening a frame — the implicit nav auto-review was
  removed), a **dirty** indicator (`● Unsaved changes` / `Saved`), a **close
  confirmation** (Save / Discard / Cancel — no edit lost silently), the active
  **labels-file path**, and a **duplicate-`labels.json`-in-frames** warning.

### Added

- `tests/unit/gui/test_review_save.py` (save writes to the requested path; persists
  additions / deletions / percentages / `reviewed=true`; reviewed negative with
  zero badges; reopen restores; close prompts; Discard does not write; Cancel keeps
  the window open; no duplicate `labels.json` under `frames/`). `REVIEW_SAVE_FIX_M4_14.md`.

## [Unreleased] — Milestone 4.13b: imported-snapshot dataset source (observe-only)

Makes the repo-root `dataset/` (where "Import Snapshot into Dataset" writes) a
first-class **reviewed** source for both the classifier and the evaluation loader,
so future imported snapshots are discovered automatically. No threshold change, no
retraining, observe-only.

### Added

- `classify.default_snapshot_dataset_dir()` — resolves the repo-root `dataset/`
  robustly (walk-up, cwd-independent). `classify.default_label_sources()` now
  includes it (grading / live_review / review_batch_002 preserved).
- `dataset.load_snapshot_dataset()` + `dataset.load_all(..., snapshots=…)` load the
  imported-snapshot `dataset/` last, then de-duplicate by image content hash so an
  identical frame is never double-counted (the reviewed copy wins).
- Regression test proving future **reviewed** imports under `dataset/` are
  auto-discovered by the classifier and loader, while **unreviewed** ones are
  skipped (the standing ground-truth gate). `DATASET_SNAPSHOT_SOURCE_REPORT_M4_13.md`.

### Notes

- The committed live H snapshot (`dataset/2026-08-04_17-58-59_H`) is **unreviewed**
  (`reviewed:false`, all percentages `null` — the detector's seeded detections), so
  it correctly loads as **no** ground truth and adds **no** exemplars: the bundled
  classifier stays at 154 exemplars, the eval set stays at 66 frames, combined
  metrics are unchanged, and wrong-accepted stays 0. It counts once reviewed.

## [Unreleased] — Milestone 4.13: Snapshot workflow (observe-only)

Freeze every interesting live scan into a permanent, reproducible, immediately
reviewable artifact so the fast-changing live board can never lose a good example.
Additive only — writes files and opens the existing Review Mode; no
detector/classifier/OCR/scheduler/threshold change; still observe-only.

### Added

- `forge/snapshots.py` (Qt-free): `write_snapshot()` creates a timestamped
  directory with `frames/raw.png`, `annotated.png`, `scan.json`, `world.json`,
  `calibration.json`, `labels.json`, `metadata.json`, and (from Vision Validation)
  `validation_report.md`. `metadata.json` records World alias, URL, resolution,
  DPR, viewport, timestamp, detector version, classifier version, git commit, and
  image MD5. Plus `load_snapshot`, `review_paths`, and `import_into_dataset`
  (dedup by image content hash; preserves labels + metadata).
- `Save Snapshot` on the **Vision Debugger** (Test Scan) and the **Vision
  Validation** page, with follow-up **Open in Review** (zero-copy `run_review` on
  the snapshot's `frames/`) and **Import into Dataset**.
- The snapshot is **immutable except for `labels.json`** — reviewing never
  rewrites the raw image, annotation, or trace (proven by a byte-hash test).
- `EXTERNAL_CHROME_ATTACH.md` (design only — attach to an operator-launched Chrome
  over CDP; BAP as read-only guest; closing BAP never closes Chrome) and
  `SNAPSHOT_WORKFLOW_REPORT.md`.
- Tests: snapshot creation, metadata completeness, reload, review round-trip
  immutability, dataset import dedup + label/metadata preservation, distinct-image
  retention, and GUI button wiring.

## [Unreleased] — Milestone 4.12: Fix live validation findings (observe-only)

Root-causes and fixes the classifier wiring defect exposed by the first live
Windows Vision Validation, and corrects the validation grading semantics. No
threshold, OCR, scheduler, runtime, or detector-behaviour change; still observe
only; full unit suite green.

### Fixed

- **Classifier was never built on the live path (the reported symptom).**
  `_bundled_classifier()` resolved the reviewed dataset to a **non-existent**
  `src/tests/forge_assets` (a fixed `parents[2]` index; the data is at repo-root
  `tests/forge_assets`), returned `None`, and the pipeline then **skipped the whole
  classification stage** — so every live percentage came back UNKNOWN with "nearest
  similarities = (none)" and a zero-sample confidence histogram, even for 20%
  (which has 154 exemplars). Added `classify.default_assets_root()` (walks up from
  the module; layout- and cwd-independent) and pointed `_bundled_classifier()` and
  the identical latent bug in `perf/benchmark._ASSETS_ROOT` at it. The bundled
  classifier now loads (len 154) from any working directory. `MIN_PCT_SIM` stays
  0.70; wrong-accepted percentage stays 0.

### Changed

- **Vision Validation grading correction.** The Badge Detection section no longer
  reads PASS just because the detector executed. Execution health is INFO; accuracy
  cannot PASS without human ground truth — a live/unreviewed scan reports
  `accuracy (TP/FP/FN) = UNVERIFIED` (section INFO) with a Review-Mode action, while
  a reviewed frame (via a new `ground_truth_badges` argument) gets measured count
  accuracy (matches → PASS, accepted > real → WARNING with the FP count, accepted <
  real → WARNING with the miss count).

### Added

- Regression tests: bundled-classifier non-empty + cwd-independent; a real 20%
  frame's detections all reach the classifier and produce a similarity (not
  missing); grading UNVERIFIED/measured branches. `LIVE_WINDOWS_REVIEW_M4_12.md`
  with the full root cause, H false-positive categories (red-terrain emblems
  clearing 0.62, spatially clustered), and the performance diagnosis (detection ≈
  80 ms × stage-1 candidates; live 40–54 s is the 4–8× higher candidate count, not
  a regression).

## [Unreleased] — Milestone 4.11: Vision Validation Suite (observe-only self-diagnosis)

One button — **Validate Vision** — runs the whole observe-only pipeline against
the selected World and grades every stage so a tester immediately knows whether
Vision is healthy. Additive only: it reuses the existing capture + `build_scan`
(through the M4.9 timing harness) + weakening reader and **changes no behaviour** —
no detector/classifier/OCR/scheduler/runtime/threshold change, still observe-only.

### Added

- `forge/detection/validation.py` — Qt-free `validate_vision()` producing a
  `ValidationReport` of seven sections (Capture, Weakening, Battle Map, Badge
  Detection, Classification, Decision, Performance). Each check is graded
  **PASS / WARNING / FAIL / INFO** with a plain-language explanation and, when not
  healthy, a probable reason + a recommended operator action ("Run Set Weakening
  Region", "Collect more reviewed live frames", "No battle badges currently
  visible", …). `to_dict()` / `to_markdown()` render the report.
- `gui/vision_validation.py` + a new **Validation** nav page — a World selector, a
  Validate-Vision button (live capture of the selected World) and a
  Validate-from-screenshot button (offline), a colour-coded section report, and an
  Export-report button. Heavy work runs in a background thread.
- `VISION_VALIDATION_REPORT.md` — a generated health report (offline sample; the
  app reproduces it live).
- Unit tests for the validation core (status aggregation, no-capture FAIL,
  section structure, uncalibrated-weakening guidance, markdown/JSON, a real-frame
  end-to-end) and the GUI page (render, export, nav wiring).

### Notes

- The validator surfaces the M4.10 live finding automatically: an uncalibrated /
  low-confidence weakening read is graded WARNING with "Run Set Weakening Region",
  and the gate stays fail-safe UNKNOWN. It also flags a benign 1px battle-map
  calibration overhang in `review_batch_002` (crops are clamped) as a "recalibrate"
  WARNING — a data note, not a code change.

## [Unreleased] — Milestone 4.9: Performance Observatory (measurement only)

A complete performance-measurement framework for the observe-only pipeline, built
to answer one question before any cursor/click work begins: **can the current
architecture scale to 8 simultaneous Worlds?** Measurement only — no optimisation,
no detector/classifier/OCR/scheduler/World/dataset/threshold change. Everything
stays observe-only and the existing suite is unchanged.

**Headline finding:** the pipeline is dominated by badge **detection** — ~3 s/tick
warm (~5 s cold), vs weakening OCR ~0.1 s and classification ~0.06 s — i.e. ~0.3
FPS per World, and because Worlds are serviced by one process the aggregate
throughput stays ~0.3 FPS *total* regardless of World count. Detection already
keeps ~3 CPU cores busy, so 8 Worlds cannot be serviced anywhere near real time
without optimising detection first — captured here as reproducible numbers, not
changed. See `docs/perf/` for the generated baseline reports.

### Added

- `bap.perf` package (self-contained, no new dependency):
  - `timing` — monotonic per-stage `StageTimer` over the canonical stages
    (capture, weakening_ocr, detection, classification, decision, gui_update,
    persistence).
  - `stats` — deterministic `summarize` (mean / median / p95 / p99 / max / stdev)
    + FPS-equivalent, pure-Python percentiles (no numpy nondeterminism).
  - `system` — stdlib CPU + RAM sampler (`/proc`, `resource`, `os.times`; psutil
    used only if present) with peak/average CPU, peak/average RSS, uptime.
  - `registry` — thread-safe per-World + global `MetricsRegistry`: average /
    median / p95 / worst / tick count / skipped ticks / FPS-equivalent, per-stage
    breakdown, current bottleneck, recent + slowest ticks; a shared default the
    dashboard reads.
  - `pipeline.run_tick` — a timed harness that calls the **unmodified**
    `build_scan` stage functions in order; a drift test proves its output equals
    `build_scan` on a real frame, so the numbers describe the production path.
  - `benchmark` — offline, browser-free, reproducible: `SyntheticBenchmark`
    (1/2/4/8 Worlds → fps, tick latency, stage breakdown, CPU, RAM) and
    `StressBenchmark` (100/1k/10k/100k ticks → avg/median/p95/p99/max). Frames are
    loaded once and replayed in a fixed, sorted order with fixed World assignment.
  - `export` (JSON / CSV / Markdown) and `compare` (regression comparison of two
    runs — current vs `forge-m4-stable` — flagging regressions/improvements
    outside a ±5% tolerance).
  - `python -m bap.perf {synthetic,stress,compare}` CLI (compare exits non-zero on
    a regression so CI can gate on it).
- **Performance** dashboard page in the Forge nav-shell: per-World and global
  timing, programmatic live charts (QPainter sparkline + stage-breakdown bars, no
  external libraries), recent slow ticks, worst stage / current bottleneck,
  historical averages, and an offline-benchmark button (runs in a background
  thread). Live-refreshes only while visible.
- `docs/perf/` generated baseline reports (synthetic sweep + stress sample) and
  `docs/perf/PERFORMANCE_OBSERVATORY.md` describing the framework and findings.
- Perf unit tests (stats determinism, registry aggregation, system sampler,
  benchmark plumbing with fast fakes, harness-vs-`build_scan` drift guard,
  export/compare, CLI, and the GUI page).

## [Unreleased] — Milestone 4.8: professional desktop UI (presentation only)

A presentation-only redesign of the Forge desktop UI. No behaviour, workflow, or
feature changes: every widget, signal, and handler is preserved (full unit suite
unchanged at 820 passed). Confined to `src/bap/gui/`; observe-only invariants and
reversibility to tag `forge-m4-stable` are untouched. Original "cartographer" dark
visual language — no third-party UI, icons, or assets are copied; all ornament is
programmatic. See `docs/ui/MILESTONE_4_8_UI_SPEC.md`.

### Added

- `gui.theme`: semantic colour palette + a single application-wide QSS
  (`apply_theme(app)`), applied once at startup in `run_gui`. Offscreen/unstyled
  test runs are unaffected (the test QApplication is not themed).
- `gui.icons`: an original line-icon set rendered programmatically to `QIcon`
  (inline SVG, no raster assets); falls back to an empty icon if Qt SVG is missing.
- `gui.widgets`: reusable presentation blocks — `Card`, `StatTile`, `StatusPill`,
  `NavRail`, section/title/muted labels — behaviour-free, styled by object name.

### Changed

- **Forge MainWindow** rebuilt into a desktop nav-shell: title bar + navigation
  rail (Dashboard / Worlds / Vision / Review / Datasets / Reports / Settings) +
  stacked pages + observe-only footer. The World Manager, browser lifecycle, and
  Test Scan move onto the Worlds/Vision pages with **identical widgets and signal
  wiring**; the Dashboard adds KPI tiles over already-known state (world/attached
  counts, browser/runtime state — no fabricated metrics). The generic/attended
  monitor keeps its classic tabbed layout.
- Startup window size raised 900×600 → 1360×860 to suit the desktop layout.

## [Unreleased] — Forge: retrain on all reviewed datasets (review_batch_002)

Retrain + re-evaluate the pipeline on grading + live_review + review_batch_002
(66 unique frames, 156 badges), frame-grouped LOFO, per source + combined.
Observe-only; detector/GUI/World Manager/OCR/weakening/runtime unchanged. Full
write-up in `tests/forge_assets/RETRAIN_REPORT.md`.

### Added

- `detection.dataset`: `REVIEW_BATCH_2_DIR` + `load_review_batch()` (guarded), and
  `load_all()` now **de-duplicates by image content** (a frame reviewed in more
  than one root counts once; the reviewed source's labels win).
- `classify.default_label_sources()`: single source of truth for the reviewed
  label sets, so review_batch_002 joins the bundled classifier and `live_eval`
  automatically. `live_eval` reports review_batch_002 as its own group.
- `RETRAIN_REPORT.md` + annotated examples under `review_batch_002/annotated/`
  (biggest improvement, still-failing, hardest negative, clean no-badge negative).

### Changed

- **Classifier retrained** from all reviewed data — percentage-classification
  coverage rose from 0 → 26/124 on the new batch frames (combined correct 6 → 37).
- **`MIN_PCT_SIM` raised 0.62 → 0.70** — the lowest bar that keeps **wrong-accepted
  percentage = 0** across the full corpus (the larger bank admits 20↔60 / 60↔100
  confusions at 0.62). A raise = strictly safer; UNKNOWN over a wrong read.

### Fixed / notes

- **Leakage:** the two live_review H frames are byte-identical; content dedup
  collapses them, correcting the earlier "live-H 4/4" (LOFO on an identical twin)
  to honest UNKNOWN. The 6 intentional no-badge negatives are now loaded (marked
  reviewed) and count toward FP measurement. Committed active-learning `.cache/`
  untracked + git-ignored. Gaps: **80% has no examples** (unclassifiable), 40% is
  0/8; detector precision on hard red-terrain negatives (~1.3 FP/frame) is the
  unchanged detector's ceiling.

## [Unreleased] — Forge active-learning: fast analysis mode

Profiled the review-batch selector and added a fast analysis mode. The detector,
classifier, and thresholds are unchanged — production scans behave identically.

### Added

- **Fast analysis mode** in `detection.active_learning` (`analyze(..., cache_dir,
  progress)`): lean per-frame features (detector.scan + classification only —
  skips the weakening OCR, panel probe, and target selection, none of which feed
  a ranking factor), a **per-frame cache keyed by content + detector/classifier
  signature** written as an immediate checkpoint (resume-after-interrupt), and
  **progress reporting** with ETA. CLI gains `--cache-dir` / `--no-progress`.
- **`ACTIVE_LEARNING_PERF.md`** — the profile (matchTemplate is 90 % of scan and
  irreducible: 1-scale is 2.7× faster but *changes* the selection; whole-ROI
  precompute is 6× slower) and the before/after benchmark.

### Performance

- Selection is **byte-identical** to the committed `review_batch_001` (files and
  scores), verified by test.
- Cold first pass ~4 % faster (matchTemplate untouched); **warm re-run / resume
  ~1376×** (projected 989 s → 0.7 s for 236 frames) with checkpoints + progress,
  so a large run never hangs invisibly or loses work on interrupt.

## [Unreleased] — Forge active-learning review batch

Builds the highest-value manual-annotation batch from the committed screenshot
corpus. **No model change** — the detector, classifier, and thresholds are used
strictly read-only and nothing is retrained.

### Added

- **`detection.active_learning`** — a review-batch builder that runs the existing
  pipeline read-only to score each screenshot by expected information gain
  (unknown %, classifier uncertainty near the accept bar / close top-2 classes,
  detector-stage disagreement, near-threshold rejects, competing candidates,
  rare background, rare scale), clusters near-duplicates by a perceptual
  descriptor, and selects a **diversity-capped** batch (round-robin across
  clusters — deliberately not top-N by uncertainty). CLI:
  `python -m bap.forge.detection.active_learning <frames_dir> --n 50 --out <dir>`.
- **`tests/forge_assets/review_batch_001/`** — the batch from the current corpus:
  selected `frames/`, `manifest.json` (per-frame source/world/resolution/cluster/
  score/factors/reasons/detector-summary), `REVIEW_BATCH.md` (method, weights, a
  per-frame WHY table), and `labels.json` + merged `calibration.json` so it opens
  directly in the existing Review Mode. The committed corpus is 18 unique
  screenshots (all already reviewed ground truth), so the batch contains all 18
  rather than 50; the note and CLI make producing a true 50 a one-command step
  once the larger keep dataset is committed.

## [Unreleased] — Forge Milestone 4.7 (live-data re-evaluation)

Used the committed reviewed live scans (Worlds H, F) to honestly re-evaluate and
improve the vision pipeline, still observe-only. Every change is justified by
score distributions; the primary safety metric (wrong-accepted percentage) is
**0** on every set.

### Added

- **`detection.dataset`** — one loading contract for the two disjoint labelled
  sources (historical `grading/`, reviewed live `live_review/`), each Sample
  tagged with source, World alias, capture geometry, both ROIs, badges, and
  weakening GT. No duplicate sources, no silent fallback, images unmodified.
- **`detection.live_eval`** — leakage-free evaluation (frame-grouped
  leave-one-frame-out) of localization, percentage classification, and the full
  slice, reported per source (historical / live-H / live-F / combined). Run with
  `python -m bap.forge.detection.live_eval`.
- **`tests/forge_assets/LIVE_VISION_REPORT.md`** — dataset counts, split,
  before/after metrics, per-World results, confusion matrix, FP categories,
  remaining blockers, and the next Windows test checklist. Small annotated
  regression fixtures under `live_review/annotated/`.
- **Handoff docs**: root `CLAUDE.md` and `docs/handoffs/CURRENT_FORGE_STATE.md`.

### Changed

- **Detector template threshold 0.55 → 0.62** — between the true-badge score
  floor (0.64 hist / 0.76 live) and the live false-positive ceiling (0.61).
  Localization precision 0.51 → 0.81 combined, live-H/F 0.37 → **1.00**, FP/frame
  1.9 → 0.44, **recall unchanged** (0.92).
- **Classifier accept threshold `MIN_PCT_SIM` 0.55 → 0.62** — removes the only
  wrong-accepted percentage at no cost to the correct count (a raise, keeping
  UNKNOWN safer).
- **Percentage exemplar bank now folds in reviewed live crops**
  (`train_from_sources`; the bundled classifier loads grading + live_review), so
  live-scale badges classify (live-H 0 → 4/4 under LOFO).

## [Unreleased] — Forge Milestone 4.6 (Windows stabilization, round 2)

Second Windows-review pass, still observe-only (no mouse/keyboard/game action).
Fixes the capture that excluded the weakening top bar, surfaces the live
classifier failure, and makes multi-World scans independently inspectable.

### Fixed

- **The capture no longer hides the Forge top bar.** `annotate()` drew the red
  OBSERVE-ONLY banner across the top ~40 px of the image — exactly where the
  current-weakening top bar sits — so it could never be seen or calibrated. The
  banner is removed from the image entirely; observe-only status stays in the
  window title, the side text panel, and the GUI chrome. The full-viewport CDP
  capture already contained the top bar, which is now visible and calibratable.

### Added

- **Label in Review Mode** on the debugger — opens the current live capture in
  the existing Review Mode (click to add/move, right-click to remove, keys 1–5
  set 20/40/60/80/100, autosave) and stores it under
  `data/forge/live_review/frames/` as additional ground truth. This is the path
  to fix live percentage classification with real live crops, no external editor.
- **Live-vs-training classifier diagnostics**: `save_scan` now writes
  `08_classifier_contact_sheet.png` (each live %-crop beside its 5 nearest
  grading exemplars) and per-candidate `raw / emblem / percent / classifier_input`
  crops; `scan.json` carries each badge's top-5 exemplars + threshold.
  `LIVE_SCAN_DIAGNOSIS.md` explains why live reads come back UNKNOWN (crop
  scale/offset, dPR/zoom, background) — a classifier-input mismatch, not a
  detection failure.
- **Scan All per-World artifacts**: each attached World's scan is saved under
  `scan_all/<timestamp>/<alias>/`, and the summary table gains a per-row **Open
  result** button that opens that World's own capture in the debugger — proving
  the H row came from the H tab and F from F.

### Changed

- The province-panel detector is now **diagnostic-only**: no box on the map and
  no line in the debugger text; its score stays in `scan.json`.

## [Unreleased] — Forge Milestone 4.5 (Windows stabilization sprint)

Stabilize the observe-only pipeline across multiple Worlds. No new gameplay; no
clicking, mouse, keyboard, or battle logic. Fixes the four Windows blockers:
Test Scan implicitly using the first World, a stale live-capture mapping falling
back to a file picker, unproven multi-World behavior, and opaque detector output.

### Added

- **`detection.testscan`** — Qt-free Test-Scan orchestration: `resolve_target`,
  `capture_world_image`, `scan_world`, `scan_all_attached`. The tab is resolved
  **fresh from the assignment at scan time**, so no stale first-World closure or
  removed World can redirect a scan. Fully unit-tested (routing, stale-callback
  prevention, delete/reorder, 4/8-World independence).
- **Explicit Test Scan World selector** in the World Manager, with a target
  panel (`Alias / Hostname / Tab title / Tab URL`) shown before capture. Live is
  enabled only for the attached World.
- **Separate live vs offline actions**: *Test Scan Live World* (requires an
  attached World; clear error otherwise — never a file picker) and *Open Offline
  Screenshot…* (a distinct action that never touches live assignment).
- **Scan All Attached Worlds** — observe-only diagnostic that scans every
  attached World independently and opens a one-row-per-World summary
  (alias, hostname, capture status, weakening + decision, stage-1 candidates,
  accepted detections, unknown %, rejected candidates, selected, error).
- **Detector diagnostics**: `scan.json` now records every stage-1 candidate once
  with colour-prior area, template score, ROI + full coords, and keep/reject
  reason; each badge carries its top-5 nearest percentage exemplars and the
  classifier threshold. The debugger explanation shows a **Pipeline** line
  (stage-1 · template-confirmed · rejected · accepted / classified / unknown).
- **`DETECTOR_DIAGNOSIS.md`** — attributes the Windows H/F misses (stage-1
  colour-prior, e.g. a badge with only 5 red px → no candidate) and false
  positives (red banners/terrain in the 0.55–0.65 band; open-panel pills), with
  the TP/FP score distributions and the recall/precision cost of each threshold.
  `test_detector_regression.py` locks a missed badge, a false positive, and the
  TP/FP separation as fixtures. No thresholds were changed.

### Changed

- **Overlay colours** per the review: accepted badge = green, unknown % = amber,
  rejected stage-1 candidate = thin red marker, selected target = cyan cross.
- The Test Scan selector, live button, and Scan All refresh on every world/tab/
  browser-state change, so the selector can never point at a stale World or tab.

## [Unreleased] — Forge Test-Scan capture-geometry fix (Windows review)

The Windows review found the Test Scan analyzed only a fixed lower rectangle
(marked by a grey boundary) that excluded the top bar, so the current weakening
could never be read; badge percentages came back `?`; and a false "panel" box was
drawn on empty terrain. This reworks the Test-Scan pipeline so it starts from one
full raw capture and reasons in explicit, correctly-offset coordinates. Still
**observe-only** — nothing clicks.

### Added

- **`detection.geometry`** — `CaptureGeometry` (raw size, viewport, device-pixel
  ratio, zoom) and `ScanRois` (two ROIs in full-capture pixels). Every Test Scan
  now derives a **weakening ROI** (top bar) and a **battle-map ROI** that covers
  the whole usable map below the top bar, instead of a hardcoded sub-rectangle.
  Calibration keys by exact geometry so a region drawn for one capture setup is
  never silently reused for a different one.
- **Full debug-artifact set** from `save_scan`: `01_full_raw_capture.png` (the
  unmodified capture), `02/03_weakening_roi_raw/processed.png`,
  `04_battle_map_roi_raw.png`, `05_badge_candidate_overlay.png`,
  `06_badge_classifier_crops/` (per-candidate crop + normalized classifier
  input), `07_final_annotated_output.png`, and `scan.json` with the whole trace
  (geometry, both ROIs, every stage-1 candidate + emblem score + keep/reject
  reason, classifier inputs/results, panel state, weakening read, final decision).
- **Set Battle-Map Region** tool in Review Mode (persisted per resolution),
  alongside the existing Set Weakening Region.

### Changed

- **Coordinate contract** — detections are reported in full-capture pixels with
  both `bbox_full` and `bbox_roi` (ROI origin removed exactly once), plus
  `center_full` and `click_point_full`. A test proves the offset is applied once.
- **Percentage classification no longer silently accepts a guess** — a prediction
  is accepted only above a similarity bar (`MIN_PCT_SIM`); below it the badge
  stays UNKNOWN with a recorded reason (e.g. the open-panel pill at similarity
  0.28). Each candidate carries a classification diagnostic (crop centre,
  prediction, similarity, accepted, reason).
- **Panel detection is corroborated** — a bare emblem score at a fixed point is
  no longer enough. The province panel is reported open (and boxed) only when the
  pill spot both scores as an emblem and classifies as a confident percentage;
  otherwise `panel_present = false`, no box is drawn, and the raw score is kept
  for diagnosis. This removes the false panel box on empty terrain.
- **`annotate()` draws both ROIs** (battle-map + weakening) on the output copy
  only; analysis always runs on the untouched raw capture.

### Fixed

- The weakening (top bar) is now inside the analyzed area — the Test Scan reads
  it instead of being blind to it.

## [Unreleased] — Forge Milestone 4 (first gameplay decision slice)

The first complete Forge decision loop, end to end and **observe-only** — no
real mouse, no keyboard, no clicking. For each frame the pipeline now: reads the
current weakening, detects every badge, filters badges against the World's
allowed percentages, chooses the best target deterministically, and renders a
full human-readable explanation. This is what lets a reviewer finally *see* that
the app understands the game.

### Changed

- **`select_target()`** (`detection.scan`) rewritten as the deterministic
  strategy: among badges whose percentage is enabled for the World, prefer the
  **lowest allowed %**, then **highest confidence**, then **nearest frame
  centre**. It records every badge it `considered` and every one it `ignored`
  (with a reason: `"disabled in settings"` / `"percentage unknown"`), so the
  debugger can show the full reasoning, not just the winner.
- **`build_scan()`** now *always* computes the best candidate; the **safety gate
  governs actionability**, not visibility. A STOP / UNKNOWN weakening gate still
  shows the candidate for review but marks it `BLOCKED by gate` — nothing becomes
  actionable. Only a CONTINUE gate yields a `Would click: x=… y=…`.
- **`DebugScan.explanation()`** renders the full Milestone-4 format
  (`World / Weakening / Limit / Decision / Detected / Ignored / Selected /
  Reason / Would click`), and **`annotate()`** colour-codes badges
  (selected / considered / ignored) with a would-click marker that turns amber
  and reads `candidate … (gate X)` whenever the gate blocks action.

## [Unreleased] — Forge weakening: per-World runtime validation

Clarifies that the 15-frame grading set is **per-frame OCR accuracy only** — the
snapshots come from different Worlds and unrelated moments, so no temporal /
monotonicity / downward-jump logic is applied to it.

### Added

- **`WeakeningTracker`** (`detection.weakening`): temporal validation of weakening
  reads at **runtime, independently per World** (`last_confirmed_weakening_by_world`,
  keyed by world id / alias). A value is confirmed only when consecutive confident
  reads *for that World* agree (consensus); a large unexplained drop (e.g. an
  86 → 36 OCR misread) is treated as suspicious and does **not** overwrite the
  confirmed value — it stays UNKNOWN until stronger consensus. No global history
  across tabs; values from different Worlds are never compared. `decide()` uses
  the confirmed value, not a raw read.

## [Unreleased] — Forge Milestone 3.5 (weakening gate + Review Mode)

Adds the second required Forge signal — **current weakening** — as a safety gate,
and extends the Vision Debugger into an interactive Review Mode. Still
observe-only; no clicking or battle logic.

### Changed

- **`World.max_weakening`** (was `max_weakening_pct`): the current-weakening
  safety threshold is the top-bar **attrition counter**, an integer that can
  exceed 100 — not a badge percentage. Persistence reads the old key for
  back-compat. Badge target selection now filters purely by `allowed_pcts`; the
  weakening gate is applied separately, before badges are considered.

### Added

- **Weakening region calibration** (`detection.calibration.WeakeningCalibration`):
  a per-resolution rectangle for the current-weakening number, drawn by the user
  (Debugger → *Set Weakening Region*) and persisted.
- **Weakening reader + fail-safe** (`detection.weakening`): two readers — OCR with
  a numeric whitelist, and deterministic digit-template matching — plus a
  conservative gate: unreadable / low-confidence → **UNKNOWN (no action)**;
  value ≥ world limit → **STOP**; only a confident value below → **CONTINUE**. It
  never continues blindly. Integrated into `DebugScan` (weakening is checked
  before any badge is selected).
- **Reader spike** (`detection.weakening_eval`,
  `tests/forge_assets/grading/WEAKENING_REPORT.md`): OCR vs template matching on
  the reviewed values. Measured on auto-located regions: OCR 33% exact with
  well-calibrated confidence (correct reads score high, wrong reads ~0, so the
  fail-safe rejects them); template matching needs a tight calibrated region.
  Region location is the bottleneck — a single-setup calibration removes it.
- **Review Mode** (`bap.gui.forge_review`, `bap-forge-review`): steps through
  frames showing the detector overlay and, per frame, lets a human confirm both
  signals — badge correction (left-click add, right-click remove, keys 1-5 set
  20/40/60/80/100) and the current-weakening value (Set Weakening Region + enter
  the value), with the raw/processed crop, OCR read + confidence, world limit,
  and CONTINUE/STOP/UNKNOWN decision shown. Everything autosaves and resumes.
  Ground-truth weakening values are recorded on `FrameLabel.weakening`.

## [Unreleased] — Forge Milestone 3 (badge detector + Vision Debugger)

The weakening-badge detector, graded against the human-confirmed set, plus an
observe-only Vision Debugger. **Real clicking stays disabled** — accuracy is
below the go-live gate (see the report), which is exactly what the debugger is
for.

### Added

- **Badge detector** (`bap.forge.detection.detector`): two stages — a red
  attrition-arrow colour prior (recall) confirmed by multi-scale, background-
  masked emblem-template matching against a bundled bank (precision) + NMS.
  Reports centre, bbox, and confidence; the side-panel pill is detected
  separately as a state signal.
- **Percentage classifier** (`detection.classify`): nearest-neighbour over
  labelled percentage patches — no OCR engine.
- **Grading harness** (`detection.evaluate`, `python -m bap.forge.detection.evaluate`):
  matches predictions to reviewed ground truth and reports recall, precision,
  centre error, and classification accuracy, **leave-one-frame-out** so the
  numbers reflect generalisation. Measured now: recall 78.4%, precision 55.8%,
  centre error median 6.1 px, classification 62.1% — centre meets the ≤10 px
  target, the rest are below the gate (full write-up in
  `tests/forge_assets/grading/GRADING_REPORT.md`).
- **Vision Debugger / Test Scan** (`bap.forge.detection.scan`,
  `bap.gui.forge_debugger`, World Manager *Test Scan* button): observe-only.
  Renders the analyzed region, every detection with %/confidence/centre, the
  panel pill separately, the sector a strategy *would* select for the World, a
  proposed click point drawn as a cross, and a plain-language explanation under
  a permanent **OBSERVE ONLY — NO CLICK PERFORMED** banner. Saves the original,
  annotated image, detection JSON, and calibration metadata. Nothing clicks.

## [Unreleased] — Forge Milestone 2 (assisted labelling + grading set)

Tooling to build the human-confirmed ground truth the badge detector will be
graded against. Still no detector, OCR, clicking, or battle logic.

### Added

- **Assisted labelling tool** (`python -m bap.forge.labeling <frames_dir>`,
  console script `bap-forge-label`): a PySide6 window that shows each frame with
  **auto-suggested** badge centres, lets you confirm/place centres by clicking,
  press **1–5** for 20/40/60/80/100 %, handle **multiple badges per frame**,
  mark negatives, and moves between frames — **autosaving** to `labels.json` and
  **resuming** at the first unreviewed frame. The state/format
  (`labeling.model`, `labeling.session`) is Qt-free and fully tested.
- **CV pre-suggester** (`labeling.suggest`): proposes candidate badge centres
  from the emblem's bright-red attrition arrow so the user mostly confirms.
  OpenCV is optional — without it the tool still labels manually.
- **Grading set** (`tests/forge_assets/grading/`): 15 representative frames
  (different worlds and screen states, incl. negatives) with a pre-seeded
  `labels.json` awaiting human confirmation, plus a README describing the review
  workflow.

## [Unreleased] — Forge Milestone 1.1 (Windows-testing P0 fixes)

Fixes found in real Windows testing of Milestone 1. Still capture-only — no
detector, OCR, rules, actions, or clicking.

### Fixed

- **Capture is provably read-only (P0-1).** The capture-only tick could flicker
  the game and even open a random province. Root cause: `page.screenshot(full_page=True)`
  grew/relaid-out the WebGL canvas on every tick and could foreground a
  background world tab (delivering an incidental pointer event to the canvas). A
  new `ForgeCanvasCaptureAdapter` drives Chromium's DevTools `Page.captureScreenshot`
  directly — viewport-only, `fromSurface`, no viewport resize, no tab
  foregrounding, no input. A regression test proves repeated capture-only ticks
  invoke **only** the screenshot call and never click/type/scroll/focus/evaluate/
  bringToFront.
- **Application exit no longer silently closes Chromium (P0-4).** Closing the
  window with managed Chromium open now prompts: keep Chromium open (default),
  close both, or cancel. Stop was already automation-only.

### Added / Changed

- **Add World from a scanned tab (P0-2).** The Add World dialog offers the
  detected Forge tabs; picking one auto-fills hostname, last URL, and title —
  the user types only an alias and per-world settings. No manual URL typing.
- **Hot World CRUD (P0-3).** Add/Edit/Remove update the GUI and the runtime
  session plan immediately, with no restart: a new world gets its tab picker at
  once, edits (e.g. cadence) rebuild a running session in place without closing
  Chromium, and removing a world drops only its session — never its browser tab.
- **Forge is Worlds-only (P0-5).** The generic "Profile" framing is hidden in
  Forge mode (the activity table reads "World"); `profile_id` stays internal.
- **Capture-only is stated plainly (P0-6).** A banner reads
  "CAPTURE ONLY — NO RULES — NO ACTIONS", and every world row shows rules 0 /
  actions 0, so no one assumes automation exists.

## [Unreleased] — Forge of Empires Assistant, Milestone 1 (P0 fixes)

First milestone of the pivot to a Forge-specific product. Adds a persistent
World Manager, separates the browser lifecycle from automation, and gives Forge
its own full-canvas capture. No detector or clicking yet — this is the P0
product/lifecycle groundwork. The generic engine is unchanged and stays
site-agnostic; everything Forge-specific lives under a new `bap.forge` package.

### Fixed

- **Stop no longer closes the browser (P0).** Browser open/close is now owned by
  a dedicated `BrowserController` (app-layer), separate from automation.
  `SessionManager` no longer starts or stops the browser — its old `shutdown()`
  is now `stop_automation()` (stops ticking, detaches sessions, leaves the
  browser and every tab open). **Stop** stops automation only; **Exit** performs
  the full teardown (stop automation, then close the browser).
- **Forge capture never uses a DOM selector (P0).** Forge is a WebGL/canvas game,
  so its capture is always the full game canvas — it can no longer inherit the
  generic placeholder selectors (e.g. `#status-panel`) that broke capture.

### Added

- **Persistent Worlds** (`bap/forge/worlds.py`): a `World` carries an **alias**
  (user-facing identity) and a durable **hostname** (technical identity, e.g.
  `cz8.forgeofempires.com`), plus per-world click cadence, max weakening, and
  allowed badge percentages. `WorldStore` auto-saves to
  `data/forge/worlds.json` (atomic write) and restores every setting on the next
  launch. **Tab reattachment is by hostname, never by transient tab id.**
- **World Manager GUI** (`bap-gui --forge`): the primary product surface — a
  worlds table with **Add / Edit / Remove**, explicit **Open Browser / Close
  Browser** controls, **Scan & Reattach** (auto-matches worlds to open tabs by
  hostname, with a manual per-world tab picker as fallback), and Start gated
  until every launch-time world has a tab.
- **Forge capture config** (`bap/forge/config.py`): builds an attended,
  full-canvas `ApplicationConfig` from Worlds — one session per world, no
  selectors, per-world cadence, observe-only (no analyzers wired yet).

## [Unreleased] — Attended browser mode + browser discovery fix

Move from developer-oriented `start_url` config to user-driven tab assignment,
and make an installed Chromium discoverable without a manual env var. Core tick
pipeline, RuleEngine, ActionExecutor, Vision, and Persistence are unchanged; the
internal model stays `profile_id` (the GUI just calls them "sessions").

### Fixed

- **Installed browser is found automatically.** The app now points Playwright at
  its per-user browser directory (`configure_browser_path()` at startup), so a
  Chromium installed via *Tools → Install browser* is found at launch — no more
  setting `PLAYWRIGHT_BROWSERS_PATH` by hand.

### Added

- **Attended (user-driven) browser mode** (`settings.attended: true`):
  - `BrowserTab` model + `TabSourcePort` (core, engine-agnostic) and an
    `AttendedBrowserManager` adapter that opens a **visible, persistent**
    Chromium context, **scans** open tabs (title/url/id), and **adopts** the tab
    the user assigns — Playwright types stay inside the adapter.
  - `SessionManager` gains an optional `tab_provider` seam so sessions adopt an
    assigned tab instead of opening one and navigating (tick pipeline untouched).
  - GUI **Attended** panel: *Open Browser* → *Scan tabs* → a per-session tab
    picker; **Start** is blocked until every session has a tab.
  - Assignment persisted locally as metadata only (id/title/url) in
    `data/attended-assignment.json` — never cookies or credentials.
- **`config/attended.example.yaml`** (no URLs) and `production.example.yaml`
  converted to attended mode — replacing the old unreachable placeholder URLs.

## [Unreleased] — Windows beta distribution

Packaging and operability for a local Windows install. No runtime features, API
additions, or architecture changes — only entry-layer/operational plumbing.

### Added

- **Platform-aware paths** (`bap/ops/paths.py`): config/logs/data/plugins under
  `%LOCALAPPDATA%\BAP` on Windows, XDG on Linux, `~/Library/...` on macOS,
  overridable with `BAP_HOME`. Source/dev runs are unchanged.
- **Local crash bundles** (`bap/ops/crash.py`): on a fatal error, a
  self-contained JSON bundle (timestamp, version, OS info, exception, last
  operational status, recent log tail) is written to `data/crashes/`. No
  telemetry — nothing leaves the machine.
- **Packaged logging**: the frozen app also writes a rotating log file to
  `logs/` (via `configure_logging(log_file=...)`); console-only in dev.
- **Windows build tooling** (`packaging/windows/`): PyInstaller spec (one folder,
  `BAP.exe` GUI + `bap.exe` CLI, embedded Python, icon, version resource),
  Inno Setup installer (per-user, Start Menu shortcut, clean uninstall),
  `build.ps1` (→ installer + SHA256 + `version.txt`), `install-browser.ps1`
  (first-run Chromium), and `validate.ps1` (clean-environment smoke test).
- **Non-developer UX (no Python/Git/command line):**
  - **First-run wizard** (`bap/gui/first_run.py`): a one-time welcome shown on
    first launch, explaining demo vs real mode and offering to install the
    browser; re-openable from *Tools → Run first-run setup…*.
  - **In-GUI browser install** (`bap/ops/browser_install.py` + a threaded
    dialog): *Tools → Install browser…* downloads Chromium via Playwright's own
    installer, with a live progress log — no PowerShell needed.
  - **One-click diagnostics export** (`bap/ops/diagnostics.py`): *Tools → Export
    diagnostics…* writes a single zip (logs + crash reports + config + system
    info) to the Desktop. Local only.
  - **Tools/Help menu** with *Open data folder* and *About*.
- **Docs**: `docs/WINDOWS_BETA.md` (updated to lead with the GUI),
  `docs/WINDOWS_INSTALL_CHECKLIST.md` (step-by-step, mouse-only), and
  `docs/PACKAGING.md` (PyInstaller-vs-Nuitka rationale + build).

### Notes

- Playwright browsers are **not** bundled (installer stays small; GUI runs on
  stubs by default). Chromium installs on first `--real` use into
  `data/ms-playwright` (~300–450 MB), pinned to the release's Playwright version.

## [0.1.0] — 2026-07-09

First tagged release: a generic, site-agnostic visual browser automation
platform (hexagonal / ports & adapters) with a hardened runtime, operations
tooling, packaging, and an operator-facing CLI, GUI, and docs.

### Added

- **Runtime core** — multi-tab tick loop (capture → vision → rules → actions →
  report) on a single asyncio event loop, driven by a deterministic Scheduler
  with per-job runtime mutation (register / unregister / replace while ticking).
- **Vision** — `VisionAnalyzerPort` with OCR (Tesseract) and template-matching
  (OpenCV) analyzers; CPU-bound analyzers offloaded to a `ThreadPoolExecutor`
  via `AsyncVisionPipeline` without changing runtime ownership.
- **Rule engine** — stateless conditions (exists / compare / confidence /
  staleness / and / or / not) producing `ActionRequest`s; per-session cooldowns.
- **Actions** — `ActionHandlerPort` with Playwright click / type / navigate /
  wait handlers; handler failures contained as `FAILED` results.
- **Resilience** — health monitoring (healthy / degraded / recovering / failed),
  bounded and isolated session recovery (no scheduler pause).
- **Persistence** — SQLite sink (WAL) with a bounded, priority-aware write
  buffer and non-blocking backpressure; read-only analytics repository.
- **Resource monitoring** — `BrowserMetricsPort` snapshots (memory/CPU/pages/
  contexts) with configurable limits driving a bounded pressure policy.
- **Plugins** — analyzer/action discovery via `importlib.metadata` entry points
  (`bap.analyzers`, `bap.actions`); invalid plugins fail during composition.
- **Operations** — structured logging (`plain` key=value and `json`), startup
  validation (fail-fast, actionable), graceful shutdown (SIGTERM/SIGINT,
  idempotent), and an operational status model (starting → ready → degraded →
  stopping → stopped).
- **GUI** — PySide6 monitoring window (observer/controller only): per-session
  table, live log, operational status, and analytics dashboard.
- **Packaging & CLI** — console entry points `bap`, `bap-run`, `bap-gui`;
  optional extras `vision`, `gui`, `monitoring`, `plugins`, `production`;
  `bap validate-config`, `--dry-run`, `--version`, `--config`, `--store`,
  `--log-format`.
- **Docs** — `README.md`, `docs/OPERATIONS.md`, `docs/PLUGINS.md`,
  `docs/PRODUCTION_RISK_REPORT.md`.

### Fixed (release-candidate audit)

- **No orphan browser process on teardown.** `PlaywrightBrowserManager.stop()`
  now always reaches `playwright.stop()` (reaping the driver subprocess) even if
  an earlier context/browser close fails, and surfaces the first error
  afterward. A partial `start()` failure now tears the driver down instead of
  leaking it.
- **Best-effort shutdown reporting.** `SessionManager.shutdown()` captures a
  `browser.stop()` failure as returned error data (matching its documented
  contract) instead of propagating.
- **Clean CLI error on a corrupt/unopenable store.** A `StorageError` now exits
  `2` with a readable message instead of a traceback.
- **Sensitive-value logging.** The development stub action handler logs action
  params at `DEBUG` (not `INFO`), keeping potentially sensitive typed values out
  of the default log stream. (Production handlers never log params.)
- **Test correctness.** The shutdown-during-recovery test used a wrong tab-id
  key and never actually triggered recovery; corrected so it exercises the real
  path.

### Security / accepted risks

See `docs/PRODUCTION_RISK_REPORT.md` for the full list. In brief: plugin
installation runs third-party code with first-party capabilities (no sandbox —
a trust decision); config files are trusted operator input (paths/selectors/URLs
are not sandboxed); SQL is fully parameterized and analytics use a read-only
connection; no secrets are logged or persisted.

### Known limitations

- No web/HTTP health endpoint (deliberately out of scope; the operational-status
  object is the seam for a future probe).
- No hard per-analyzer timeout: a genuinely hung analyzer blocks its tick
  (a raising/timeout-raising analyzer is isolated as a vision failure).
- Signal-based graceful shutdown is a no-op where `add_signal_handler` is
  unavailable (e.g. Windows / non-main thread); `KeyboardInterrupt` / GUI-close
  paths still apply.
- Extras pin lower bounds only; deployers should add a lockfile/constraints.

[0.1.0]: https://github.com/Dirtystar/foe/releases/tag/v0.1.0
