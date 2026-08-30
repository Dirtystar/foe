# CLAUDE.md — repository guide for AI agents

## What this is

**Forge of Empires Assistant is the product.** BAP (Browser Automation Platform)
is now only the **internal engine** — a hexagonal (ports/adapters) core that the
Forge product is built on. Optimize decisions for the Forge product first; do not
add generic abstractions unless a Forge feature clearly requires them.

Current state: **observe-only, with one gated manual output**. The app reads Forge
Guild-Battlegrounds tabs and *explains* what it sees (weakening gate + badge
detection + a deterministic would-click target). It performs **no clicking and no
keyboard input**. The only output action is the Milestone 5A **Move Cursor
Preview**: a manual, operator-confirmed, one-shot cursor *move* to the validated
would-click point that never clicks (`src/bap/forge/cursor/`, `CursorPreviewPort`
exposes only `move_to`). Do not add clicking, automated/ repeated cursor movement,
scheduler-triggered movement, battle flow, R cadence, daily counters, or licensing
unless explicitly asked.

## Where things live

- `src/bap/forge/` — the product: `worlds.py` (World Manager), `detection/`
  (capture geometry, ROIs, badge detector, percentage classifier, weakening
  reader/gate, scan pipeline, evaluation), `labeling/` (grading/label tools).
- `src/bap/gui/` — PySide6 UI: `main_window.py` (World Manager + Test Scan),
  `forge_debugger.py` (Vision Debugger), `forge_review.py` (Review Mode),
  `forge_scan_all.py` (multi-World summary).
- `src/bap/adapters/capture/forge_capture.py` — read-only CDP screenshot.
- `src/bap/core/` — engine ports/domain (the reusable BAP part).
- `tests/forge_assets/` — labelled datasets + vision reports:
  `grading/` (historical), `live_review/` (reviewed live H/F).
- `docs/handoffs/CURRENT_FORGE_STATE.md` — the living status handoff; read it first.
- `docs/reports/` — historical milestone reports + research evidence (archive,
  indexed by `docs/reports/README.md`).
- `docs/design/` — forward-looking design docs (e.g.
  `M6_AUTONOMOUS_CLICKING_DESIGN.md`, the click-milestone spec — design only).

## Working here

- Run **targeted tests** during development; run the **full unit suite once per
  milestone** before committing: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m
  pytest tests/unit -q`. Do not run load/stress/integration suites unless a change
  actually affects those subsystems.
- Vision changes: re-evaluate with `python -m bap.forge.detection.live_eval`
  (frame-grouped leave-one-frame-out; reports historical / live-H / live-F /
  combined). Never justify a threshold change by headline accuracy — use the
  TP/FP score distributions, and keep UNKNOWN safer than a wrong-accepted read.
- **Do not rebuild existing architecture** (World Manager, capture, detector,
  Vision Debugger, ROIs/calibration, safety gates) without a demonstrated blocker.
  Review current state before generalizing.
- Ignore `.venv`, `.git`, `build`, `dist`, raw screenshot archives, and generated
  debug/scan output folders unless a task explicitly needs them.

## Safety invariants (must hold)

- OBSERVE ONLY — the pipeline computes a would-click point but never clicks.
- Per-World weakening gate: UNKNOWN → no action; ≥ limit → STOP; only a confident
  below-limit read → CONTINUE. Weakening state is per-World, never global.
- A percentage is accepted only above the similarity bar; otherwise it stays
  UNKNOWN and is ineligible for selection. Wrong-accepted percentage must stay 0.
