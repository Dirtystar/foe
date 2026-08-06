# Engineering Review — Milestone 4 (Principal Engineer)

_Review only. No code was changed, no models retrained, no thresholds touched.
This document evaluates the whole repository for long-term (2-year) maintainability
and flags risks before they become expensive. Where something is strong, it is
called out explicitly as **keep**._

Reviewer frame: newly-joined Principal Engineer. Scope: `src/bap/**`, `tests/**`,
`docs/**`, packaging, and process. Snapshot: branch
`claude/browser-automation-architecture-5784h1`, ~17.3k LOC source across 8
packages, 860 unit tests passing.

---

## 0. What this system actually is (context for the findings)

The repository contains **two products in one tree**:

1. **BAP** — a generic, site-agnostic hexagonal automation engine: `core/`
   (ports, domain, rules, actions, vision pipeline, scheduler, session lifecycle),
   `adapters/` (Playwright browser/capture, OpenCV template-match, Tesseract OCR,
   SQLite persistence), config-driven sessions, plugin discovery via entry points.
2. **Forge of Empires Assistant** — the stated product: `forge/` (World Manager,
   detection pipeline, labelling), `gui/` (World Manager + Vision Debugger + Review
   Mode + Performance), observe-only.

`CLAUDE.md` and the handoff say "Forge is the product; BAP is the internal engine."
The most important structural fact I found: **a Forge World runs through the exact
same generic tick as a BAP profile** (`core/engine/tab_session.py`: capture →
vision → aggregate → evaluate rules → actions), but Forge wires **empty analyzers
and an empty rule pack** (`forge/config.py`). The real detection work
(`forge/detection/scan.py::build_scan`) runs **only in Test Scan / the debugger**,
not in the scheduled runtime tick. This single fact drives several findings below
(perf instrumentation location, the generic-engine boundary, and the scaling
question).

---

## 1. Strengths — architecture that should NOT be changed

These are genuine strengths. Treat them as stable API; do not refactor them for
taste.

- **S1 — Hexagonal port boundary is clean and minimal.** `core/ports/` defines a
  tight, well-named set (`browser_port`, `capture_port`, `vision_analyzer_port`,
  `action_handler_port`, `state_store_port`, `tab_source_port`,
  `browser_metrics_port`). Adapters depend on ports, not vice-versa. This is the
  backbone that let Forge reuse the runtime without touching the engine. **Keep.**
- **S2 — Observe-only safety is enforced structurally, not by convention.** The
  weakening gate is fail-safe (`weakening.py::decide`: UNKNOWN → no action, ≥ limit
  → STOP), percentages are accepted only above a similarity bar, "wrong-accepted %
  must stay 0" is a stated and tested invariant, and the pipeline computes a
  would-click point it never performs. This is exactly how safety-critical code
  should be written. **Keep, and protect it (see P0).**
- **S3 — Vision evaluation rigor.** `detection/evaluate.py` + `live_eval.py` use
  frame-grouped leave-one-frame-out, per-source reporting, and TP/FP score
  distributions; the project rule "never justify a threshold by headline accuracy"
  is followed. Reviewer-in-the-loop (`forge_review.py`) turns live data into
  labelled truth. This discipline is rare and valuable. **Keep.**
- **S4 — Scheduler concurrency primitive.** `core/engine/scheduler.py` runs each
  job as an independent asyncio task, injects `sleep`/`rng` for deterministic
  tests, and supports hot `register`/`unregister`/`replace` under a mutation lock.
  Clean, testable, no global state. **Keep.**
- **S5 — World Manager identity model.** Worlds key on **hostname** (durable) not
  tab id (ephemeral), enabling reattach-by-hostname and hot add/edit/remove with no
  restart (`forge/worlds.py`, `main_window` CRUD). This is the right domain model
  for the product. **Keep.**
- **S6 — Runtime lifecycle safety (the P0-series work).** Stop = automation-only;
  browser open/close is explicit; exit prompt defaults to keeping Chromium (and
  login) alive. This prevents the worst live-user surprises. **Keep.**
- **S7 — Optional-dependency discipline + graceful degradation.** `pyproject`
  extras (`vision`, `gui`, `monitoring`, `plugins`, `production`) are well-factored,
  and code degrades instead of crashing when an optional dep is missing
  (`perf/system.py` without psutil, `icons.py` without Qt-SVG, resource snapshots
  without psutil). **Keep.**
- **S8 — Test suite breadth and honesty.** 860 unit tests, good assert density,
  behavioral (not just smoke), offscreen-Qt GUI tests, and markers separating
  `integration`/`load`/`stress` from the fast unit gate. **Keep.**
- **S9 — Coordinate contract in the scan.** `scan.py` applies the ROI offset
  exactly once and reports both full-image and ROI-local boxes, with tests. This is
  the kind of contract that prevents a whole class of off-by-ROI bugs. **Keep.**
- **S10 — M4.9 measurement honesty.** The perf harness (`perf/pipeline.py`) times
  the **unmodified** `build_scan` stage functions and a drift test asserts harness
  output ≡ `build_scan`, so the numbers describe the production path rather than a
  copy. Deterministic stats (pure-Python percentiles). **Keep.**

---

## 2. Findings

Severity legend: **P0** critical architectural · **P1** expensive within a few
milestones · **P2** worth improving eventually · **P3** nice-to-have.
Each finding: severity · affected modules · why it matters · future cost ·
proposed solution · difficulty · benefit.

### P0 — Critical

#### P0-1 · No automated CI enforcing the safety invariants
- **Affected:** whole repo; process; `tests/**`.
- **Why it matters:** the observe-only guarantees (no click, fail-safe UNKNOWN,
  wrong-accepted % = 0) and the 860-test suite are enforced **only when a human
  remembers to run pytest locally**. There is no `.github/workflows`. Over a 2-year
  horizon with multiple contributors and AI agents, the single most likely way an
  expensive regression enters — an accidental action, a threshold drift, a
  wrong-accepted percentage — is a change that was never run through the suite. The
  safety story is only as strong as its enforcement, and today enforcement is
  manual.
- **Future cost:** high and open-ended. One un-tested merge that re-introduces a
  wrong-accepted read or a click is a trust-destroying, hard-to-detect incident.
- **Proposed solution:** add a CI workflow that runs `QT_QPA_PLATFORM=offscreen
  pytest tests/unit` on every PR, plus a scheduled job for `-m integration`. Make
  the vision-safety tests (wrong-accepted = 0, decide() fail-safe) a required
  status check. Add a "no `click(`/mouse/keyboard API" grep gate as a cheap
  belt-and-braces safety check.
- **Difficulty:** Low (a day).
- **Benefit:** Very high — converts the excellent test suite from advisory to
  enforced; protects the product's core promise.

### P1 — Expensive soon

#### P1-1 · Unresolved dual-product boundary (generic engine vs Forge)
- **Affected:** `core/rules`, `core/actions`, `core/vision`, `adapters/vision`,
  `adapters/actions`, `config/config_models`, `forge/config.py`, `app/composition`.
- **Why it matters:** the product uses **none** of the generic rules/actions/vision
  path at runtime (Forge sessions carry empty analyzers + an empty rule pack), yet
  that machinery — rule engine, condition DSL (`core/rules/conditions.py`, 279
  LOC), action executor, Tesseract/OpenCV analyzer adapters, the full pydantic
  config model, and the `World → ApplicationConfig` bridge — must still be
  maintained, tested, and reasoned about on every change. It is a **second product
  surface** delivering zero Forge value today. As Forge diverges (badge decisions,
  eventually actions), the generic abstractions will either constrain the product
  or rot. This is the central architectural debt.
- **Future cost:** medium-high and compounding — every refactor pays a "keep the
  generic engine working" tax; every new contributor must learn two mental models.
- **Proposed solution:** make an explicit, documented decision and commit to it.
  Two viable paths: **(a) Engine substrate** — freeze BAP as an internal library,
  stop presenting it as a shipped product (drop `bap`/`bap-run` from the headline,
  quarantine its docs), and keep only the runtime lifecycle Forge actually uses;
  **(b) Prune** — if the generic CLI product is not on the 2-year roadmap, delete
  the rules/actions/generic-vision path and let Forge own its tick directly. Do not
  leave it in the current ambiguous middle.
- **Difficulty:** Medium (decision is the hard part; prune is mechanical).
- **Benefit:** High — halves the conceptual surface area and clarifies every future
  design conversation.

#### P1-2 · `gui/main_window.py` is a God object (1164 LOC, 72 methods)
- **Affected:** `gui/main_window.py`.
- **Why it matters:** one class now owns the forge shell, the classic shell, world
  CRUD, browser lifecycle, Test Scan, debugger/scan-all launching, the menu, seven
  page builders, runtime control slots, report/state/health slots, and perf-page
  wiring. It mixes view construction, controller logic, and runtime orchestration.
  This is where merge conflicts, regressions, and "I'm afraid to touch it" will
  concentrate as the GUI grows over two years.
- **Future cost:** medium and rising — GUI velocity drops and every GUI bug risks
  collateral damage across unrelated features.
- **Proposed solution:** extract along the existing seams (they are already
  visible): a `WorldController` (CRUD + service calls), a `BrowserLifecycle`
  controller, a `TestScanController`, and page widgets that own their own build +
  refresh. Keep `MainWindow` as a thin composition root wiring signals. The M4.8
  page split already proves the pattern; continue it into behaviour, not just
  layout.
- **Difficulty:** Medium (presentation seams exist; the risk is the signal wiring).
- **Benefit:** High for GUI maintainability and testability.

#### P1-3 · Performance instrumentation is not wired to the live runtime; two timing systems now coexist
- **Affected:** `perf/registry.py`, `perf/pipeline.py`, `core/engine/tab_session.py`
  (`TickReport.capture_ms/vision_ms/rules_ms/actions_ms`), `gui/perf_page.py`.
- **Why it matters:** `tab_session` has **already** emitted per-stage tick timing
  since before M4.9, and M4.9 added a **second**, independent timing system
  (`bap.perf`) fed only by offline benchmarks. The live Performance dashboard
  therefore shows benchmark data, not real runtime data, and the benchmark measures
  `build_scan` (the Test-Scan path) — which is **not what the scheduler runs today**
  (empty analyzers). When detection is eventually wired into the runtime tick, there
  will be two overlapping notions of "stage timing" to reconcile, and the dashboard
  will need a real data source. Left unaddressed, the observatory measures a path
  the product doesn't run in production.
- **Future cost:** medium — divergence between "what we benchmark" and "what runs"
  quietly erodes trust in the numbers exactly when scaling decisions depend on them.
- **Proposed solution:** define one timing contract. Route `TickReport` stage
  timings into `MetricsRegistry` so the dashboard reflects the live scheduler, and
  treat `perf.pipeline.run_tick` as the offline mirror of whatever the runtime
  actually executes. When detection moves into the tick, the benchmark and the
  runtime should call the same stage functions.
- **Difficulty:** Low-Medium.
- **Benefit:** High — makes the (excellent) measurement framework describe reality.

#### P1-4 · Detection is a hard performance ceiling for the stated goal (measured, not a bug)
- **Affected:** `forge/detection/detector.py`, `scan.py`; roadmap.
- **Why it matters:** M4.9 measured ~3 s/tick warm (~5 s cold), ~95% in badge
  detection, ~0.3 FPS per World, aggregate throughput flat regardless of World count
  because the work is single-process and cv2 already saturates ~3 cores. The
  explicit goal — 8 simultaneous Worlds — is unreachable with the current detector.
  This is correctly out of scope for M4.9 (measurement only), but it is now a
  known, quantified ceiling that blocks the product direction and must be planned
  for **before** detection is wired into the live loop (or the loop will inherit a
  3–5 s stall per World).
- **Future cost:** high if ignored — it caps the product; medium if scheduled now.
- **Proposed solution:** an M5 detection-performance workstream (ROI narrowing,
  candidate-stage cost profiling, resolution/scale reduction, optional worker-pool
  offload with honest core-contention measurement). Use the new perf harness to
  gate any change against `forge-m4-stable` via `python -m bap.perf compare`.
- **Difficulty:** Medium-High (real algorithm work — separate milestone, guarded).
- **Benefit:** Very high — it is the gate on the product's core scalability claim.

#### P1-5 · Production vision depends on data under `tests/`
- **Affected:** `gui/forge_debugger.py::_bundled_classifier`
  (`parents[2]/"tests"/"forge_assets"`), `forge/detection/classify.py::
  default_label_sources`, packaging.
- **Why it matters:** the shipped classifier is trained **at runtime from
  `tests/forge_assets/`**. Test fixtures and production model inputs are the same
  files. Any packaging that excludes `tests/` (a normal instinct for a wheel/PyInstaller
  build) ships an app with **no classifier** — silent loss of percentage reads,
  which the gate then treats as UNKNOWN. It also blurs the test/prod boundary: a
  change to a "test asset" changes production behaviour.
- **Future cost:** medium — a latent packaging landmine plus ongoing conceptual
  confusion.
- **Proposed solution:** move the reviewed label sets to a first-class data package
  (e.g. `src/bap/forge/detection/assets/labels/…` or a versioned data dir resolved
  by `ops/paths.py`), and have tests read from there. Optionally persist a trained
  classifier artifact so startup does not retrain from raw labels every launch.
- **Difficulty:** Medium (path plumbing + packaging manifest).
- **Benefit:** High — removes a shipping risk and clarifies the data boundary.

#### P1-6 · No schema/versioning/migration for the JSON persistence
- **Affected:** `forge/worlds.py` (worlds JSON), `LabelStore` (labels JSON),
  `detection/calibration.py` (calibration JSON), review batch manifests.
- **Why it matters:** four independent, hand-rolled JSON stores persist durable user
  state (worlds, labels, per-resolution calibration). None carries a schema version
  or migration path. The first time a field is renamed or a structure changes, old
  user files either break loudly or, worse, load partially. Over two years, schema
  evolution is a certainty.
- **Future cost:** medium — a future format change risks silent data loss for real
  users' worlds/calibration.
- **Proposed solution:** add a `version` field to each store, a tiny
  load-time migration hook, and round-trip tests for at least one prior version.
  Consider a single `ops/paths`-anchored data dir with a documented layout.
- **Difficulty:** Low-Medium.
- **Benefit:** Medium-High — protects real user state and future refactors.

### P2 — Worth improving

#### P2-1 · Broad exception swallowing (78 `except Exception` sites)
- **Affected:** across `gui/`, `perf/`, `ops/`, `forge/detection/` (e.g.
  `perf/system.py`, `benchmark._git_ref`, `_bundled_classifier`, calibration load).
- **Why it matters:** many are legitimate "never crash the UI/headless" guards and
  fit the fail-safe philosophy. But a blanket `except Exception: return None` in the
  persistence/training paths can convert a real error (corrupt labels, unreadable
  calibration) into a silent degradation that looks like "no data" rather than a
  fault. Silent is the enemy of debuggable.
- **Future cost:** medium — intermittent, hard-to-reproduce field issues.
- **Proposed solution:** audit the 78 sites; keep the UI guards but ensure every one
  logs at debug/warning with context, and narrow the persistence/training ones to
  the specific expected exceptions so unexpected ones surface.
- **Difficulty:** Low (mechanical, but needs judgement per site).
- **Benefit:** Medium — materially improves field diagnosability.

#### P2-2 · Documentation sprawl and a stale living handoff
- **Affected:** `docs/handoffs/CURRENT_FORGE_STATE.md` (says "Latest work: M4.7",
  lists through M3.7 — the repo is at M4.9), plus `RELEASE_BASELINE.md`,
  `RELEASE_CHECKLIST.md`, `docs/PRODUCTION_RISK_REPORT.md`, a 40 KB `CHANGELOG.md`,
  and per-milestone spec docs.
- **Why it matters:** the doc that explicitly says "update at each milestone" is two
  milestones behind, and status is spread across five overlapping documents. New
  contributors cannot trust any single source of truth — the exact failure mode
  documentation is meant to prevent.
- **Future cost:** low-medium — onboarding friction and decisions made on stale info.
- **Proposed solution:** designate `CHANGELOG.md` as the canonical history and
  `CURRENT_FORGE_STATE.md` as the canonical *current* state, refresh the latter now,
  and make "update the handoff" part of the release checklist (ideally a CI check
  that the top CHANGELOG milestone matches the handoff).
- **Difficulty:** Low.
- **Benefit:** Medium — restores a trustworthy front door.

#### P2-3 · Product identity vs package identity mismatch
- **Affected:** `pyproject.toml` (name `browser-automation-platform`, description
  "Generic, site-agnostic visual browser automation platform", five console
  scripts), `README.md`.
- **Why it matters:** the packaging and README still present the generic platform as
  the headline, while the actual product is Forge. This reinforces the P1-1
  ambiguity at the most visible layer and will confuse future maintainers and any
  external consumer.
- **Future cost:** low-medium — sustained conceptual drag; ties to P1-1.
- **Proposed solution:** once P1-1 is decided, align name/description/entry points
  and README with the chosen reality (Forge product front-and-center; BAP as engine
  library if kept).
- **Difficulty:** Low.
- **Benefit:** Medium — the cheapest way to make the codebase legible.

#### P2-4 · Training/dataset pipeline is implicit and un-versioned
- **Affected:** `forge/detection/classify.py` (`train_from_sources` at startup),
  `dataset.py`, `active_learning.py`, `tests/forge_assets/**`.
- **Why it matters:** the model is retrained in-process on every launch from raw
  labels; there is no persisted, versioned model artifact and no dataset registry
  outside `tests/`. Reproducibility rests entirely on the frozen label files.
  Retrains are documented in the CHANGELOG (good) but not pinned to an artifact hash
  (harder to audit a regression to a specific dataset state).
- **Future cost:** medium — as the dataset grows, "which data produced this model"
  becomes hard to answer; startup retrain cost grows.
- **Proposed solution:** persist a trained classifier artifact keyed by a dataset
  content hash; make `default_label_sources` a versioned dataset manifest. Couples
  well with P1-5.
- **Difficulty:** Medium.
- **Benefit:** Medium — auditability and faster startup.

### P3 — Nice-to-have

- **P3-1 · Perf stress ladder is impractical at large N.** `python -m bap.perf
  stress --ticks 100000` is an overnight run at ~3 s/tick. Document the intended use
  and/or add a wall-clock budget guard. Low effort, low benefit.
- **P3-2 · Review/placeholder GUI surfaces.** The Review/Datasets/Reports nav pages
  are informational placeholders pointing at dedicated windows; fine for now, but
  track them so they don't ossify as dead-ends. Low/Low.
- **P3-3 · Two "review" concepts** (`gui/forge_review.py` Review Mode vs the nav
  "Review" placeholder) risk naming collision as they converge. Low/Low.

---

## 3. Dependency graph & boundary health (summary)

- **Direction is correct:** `adapters → ports ← core`, `forge → core (lifecycle)`,
  `gui → forge + app`, `perf → forge.detection` (read-only, measurement). No
  inversion of the hexagon was found.
- **The one boundary leak worth naming:** `gui/forge_debugger.py` reaching into
  `tests/forge_assets` for the production classifier (P1-5) — the only place source
  depends on the test tree.
- **No dead packages found.** The generic vision/rules/actions path is *unused by
  the product* but *live* (imported by `tab_session`, `composition`, `translation`,
  and its own tests). It is debt (P1-1), not dead code.
- **Build hygiene is good:** `*.egg-info`, `__pycache__`, caches, and the
  active-learning `.cache/` are git-ignored and untracked.

---

## 4. Closing sections

### 4.1 Top 10 strongest architectural decisions (do not destabilize)
1. Hexagonal ports/adapters with a minimal, well-named port set (**S1**).
2. Structurally-enforced observe-only safety + fail-safe UNKNOWN gate (**S2**).
3. Reviewer-in-the-loop vision evaluation with LOFO + TP/FP distributions (**S3**).
4. Deterministic, injectable scheduler with hot job mutation (**S4**).
5. Hostname-keyed World identity enabling reattach + hot CRUD (**S5**).
6. Runtime lifecycle safety: Stop = automation-only, explicit browser control (**S6**).
7. Optional-dependency extras with genuine graceful degradation (**S7**).
8. Broad, behavioral, marker-segmented test suite (860 tests) (**S8**).
9. The scan coordinate contract (ROI offset applied once, tested) (**S9**).
10. M4.9's measurement honesty (harness ≡ `build_scan`, deterministic stats) (**S10**).

### 4.2 Top 10 risks (ranked)
1. **No CI enforcing the safety invariants** (P0-1).
2. **Unresolved generic-engine vs Forge boundary** (P1-1).
3. **Detection performance ceiling blocks the 8-World goal** (P1-4).
4. **`main_window.py` God object** (P1-2).
5. **Production vision depends on `tests/` data** (P1-5).
6. **Perf instrumentation not wired to the live runtime; two timing systems** (P1-3).
7. **No schema/versioning/migration for JSON persistence** (P1-6).
8. **Silent broad-exception swallowing in persistence/training paths** (P2-1).
9. **Stale handoff + documentation sprawl** (P2-2).
10. **Package/product identity mismatch** (P2-3).

### 4.3 Recommended roadmap for M5
Sequenced so cheap risk-reducers land first and the big decision unblocks the rest.

- **M5.0 — Lock the safety net (P0-1).** CI on every PR: offscreen unit suite +
  required safety-invariant checks + a "no input-API" grep gate. ~1 day, highest ROI.
- **M5.1 — Decide the boundary (P1-1) and align identity (P2-3).** One design doc,
  one decision (engine-substrate vs prune), then align `pyproject`/README. Nothing
  else should be built on the ambiguous middle.
- **M5.2 — Unify timing + wire the runtime (P1-3).** Route `TickReport` timings into
  `MetricsRegistry`; make the dashboard reflect the live scheduler; converge the
  benchmark path with the runtime path. Prerequisite for trusting M5.3's numbers.
- **M5.3 — Detection performance workstream (P1-4).** Behaviour-preserving only,
  guarded by `perf compare` against `forge-m4-stable`, with the "wrong-accepted % =
  0" test as a hard gate. This is where the product's scalability is won or lost.
- **M5.4 — Data boundary + persistence durability (P1-5, P1-6, P2-4).** Move
  reviewed labels out of `tests/`, add schema versions + migrations, optionally
  persist a hashed model artifact.
- **Continuous — P1-2 GUI decomposition and P2-1 exception audit** as background
  refactors, each behind the now-mandatory CI.

### 4.4 Things I would explicitly refuse to change
- **The observe-only safety model and the fail-safe UNKNOWN gate.** Do not "optimize"
  UNKNOWN into a guess; the asymmetry (UNKNOWN safer than a wrong read) is the whole
  point. Any change here must clear the wrong-accepted = 0 bar first.
- **The hexagonal port boundary.** Do not let `forge/` or `gui/` reach past ports
  into adapters, and do not collapse the layers for convenience.
- **The vision evaluation methodology** (LOFO, per-source, TP/FP distributions, "no
  headline-accuracy justification"). Keep it exactly as-is; it is the reason the
  vision work is trustworthy.
- **The scheduler's injected-time/rng determinism and per-job isolation.** These are
  what make the runtime testable; keep them.
- **The World hostname-identity + hot-CRUD model.** Correct domain modeling; don't
  regress to tab-id coupling or restart-to-apply.
- **The M4.9 harness-equals-production drift guard.** Never let the benchmark drift
  into measuring a copy of the pipeline; the equivalence test must stay.
- **Deterministic percentiles / stats in `perf/stats.py`.** Keep pure-Python
  determinism; do not swap in a nondeterministic dependency for convenience.

---

_End of review. No files other than this document were created or modified._
