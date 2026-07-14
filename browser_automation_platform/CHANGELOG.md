# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
