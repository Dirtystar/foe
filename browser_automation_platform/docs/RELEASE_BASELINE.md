# RELEASE BASELINE — Forge M4 (stable Vision baseline)

Git tag: **`forge-m4-stable`**. This is the last fully validated Vision baseline
**before** any GUI/UX work (Milestone 4.8) begins. Reverting to this tag returns
the whole system to a known-good, observe-only state with every Vision result
intact.

## Product

**Forge of Empires Assistant** — the product. **BAP (Browser Automation
Platform)** — the internal hexagonal engine it is built on. The assistant reads
Forge Guild-Battlegrounds tabs and **explains** what it sees; it takes no game
actions.

## Safety guarantees (observe-only)

- **OBSERVE ONLY — NO CLICK PERFORMED.** No mouse movement, clicking, keyboard
  input, battle logic, R cadence, daily counters, or licensing.
- Capture is **read-only** via CDP `Page.captureScreenshot` (`fromSurface`, no
  foregrounding, no viewport resize, no input) — see
  `adapters/capture/forge_capture.py`.
- The pipeline computes a *would-click* point and draws it; it never performs it.
- Per-World weakening **safety gate**: UNKNOWN → no action; ≥ limit → STOP; only a
  confident below-limit read → CONTINUE. Weakening state is per-World, never
  global.
- A percentage is accepted only above the similarity bar; otherwise it stays
  **UNKNOWN** and is ineligible for selection. **Wrong-accepted percentage = 0.**

## Architecture (unchanged at this baseline)

- `src/bap/core/` — engine ports/domain (reusable BAP).
- `src/bap/adapters/capture/forge_capture.py` — read-only CDP screenshot.
- `src/bap/forge/` — the product:
  - `worlds.py` — persistent World Manager (hostname reattach).
  - `detection/` — `geometry` (capture geometry + ROIs), `calibration`,
    `detector` (colour-prior + masked emblem template + NMS), `classify`
    (exemplar cosine, no OCR), `weakening` (OCR reader + fail-safe gate +
    per-World temporal validation), `scan` (build_scan / annotate / save_scan /
    select_target), `dataset` + `live_eval` (leakage-free evaluation),
    `active_learning` (review-batch selector), `evaluate`.
  - `labeling/` — grading/label store + session.
- `src/bap/gui/` — PySide6 UI (the surface Milestone 4.8 will restyle):
  `main_window` (World Manager + monitor + dashboard), `forge_debugger` (Vision
  Debugger), `forge_review` (Review Mode), `forge_scan_all` (Scan-All summary),
  `forge_panel` (World dialog), `dashboard`, `first_run`, `report_view`,
  `qt_bridge`, `runtime_service`.

## Completed milestones

- **M1** — World Manager (persistent worlds, hostname reattach, explicit browser
  lifecycle, provably read-only capture).
- **M2** — Labelling tool + grading set.
- **M3 / M3.5–3.7** — Badge detector, percentage classifier (no OCR), evaluation
  harness, Vision Debugger; weakening region calibration, OCR reader + fail-safe
  gate, per-World temporal validation.
- **M4** — First deterministic decision slice (lowest allowed % → confidence →
  nearest centre) with full explanation.
- **M4.5** — Multi-World Test Scan routing (explicit selector, live/offline split,
  Scan All) + detector stage diagnostics.
- **M4.6** — Removed the banner covering the top bar; live classifier diagnostics
  + contact sheet; Label-in-Review-Mode; Scan-All per-World artifacts.
- **M4.7** — Live-data re-evaluation, justified threshold changes, live exemplars.
- **Retrain** — folded in `review_batch_002`; classifier retrained from all
  reviewed data; safety threshold raised to keep wrong-accepted = 0.

## Vision pipeline

Raw capture → **battle-map ROI** + **weakening ROI** (calibrated per geometry) →
colour-prior candidates → masked emblem template confirmation (threshold **0.62**)
→ NMS → percentage classification (exemplar cosine, accept bar **MIN_PCT_SIM =
0.70**) → World allowed-% filter → deterministic selection → would-click marker →
human-readable explanation. Every stage is traced in `scan.json`.

## Supported datasets

| source | frames | badges | role |
|---|---|---|---|
| `tests/forge_assets/grading/` | 15 | 32 | historical regression set |
| `tests/forge_assets/live_review/` | 3 | 6 | reviewed live H/F captures |
| `tests/forge_assets/review_batch_002/` | 50 | 124 | reviewed active-learning batch |
| **combined (deduped by content)** | **66** | **156** | training + LOFO evaluation |

Loaded through one contract (`detection.dataset`) with content de-duplication;
the classifier trains from all present sources (`classify.default_label_sources`).

## Current evaluation metrics (frame-grouped LOFO)

`python -m bap.forge.detection.live_eval` (see `RETRAIN_REPORT.md`):

| set | P | R | F1 | FP/frame | class correct | wrong-accepted |
|---|---|---|---|---|---|---|
| historical | 0.833 | 0.893 | 0.862 | 0.36 | 11/28 | **0** |
| review_batch_002 | 0.618 | 0.847 | 0.715 | 1.30 | 26/124 | **0** |
| **combined** | **0.657** | **0.859** | **0.745** | **1.06** | **37/156** | **0** |

## Known limitations

- **80% percentage has no labelled examples anywhere** → unclassifiable; **40% is
  0/8** (few, confusable). Both need labels.
- **Detector precision on hard negatives** (red terrain / province banners /
  lava) ≈ 1.3 FP/frame — the colour prior fires on emblem-like reds. Unchanged.
- **Colour-prior recall** misses a few edge/banner badges (too few red pixels for
  a stage-1 candidate).
- **Duplicate live-H frame** — the two live_review H captures are byte-identical;
  live-H classification is honestly UNKNOWN (needs distinct same-scale samples).
- Test verification runs on grading-scale desktop screenshots and a small live
  set; broader live coverage is future work.

## Test status

Full unit suite: **820 passed, 1 skipped** (`QT_QPA_PLATFORM=offscreen
.venv/bin/python -m pytest tests/unit -q`).

## Reverting to this baseline

Primary anchor: the annotated git tag **`forge-m4-stable`**.
`git checkout forge-m4-stable` (or reset a branch to it) restores this exact
Vision state.

> **Note:** this session's git remote does not accept tag pushes (it holds no
> tags), so the tag currently lives locally. The equivalent remote anchor is the
> **commit on `claude/browser-automation-architecture-5784h1` that adds this
> file** (the retrain state `7cdb037` plus these baseline docs). To restore:
> `git checkout <that-commit>`; and `git tag -a forge-m4-stable <that-commit>`
> re-creates the tag anywhere the remote supports tags.

Milestone 4.8 changes only presentation; if its direction is rejected, returning
here loses no Vision work.
