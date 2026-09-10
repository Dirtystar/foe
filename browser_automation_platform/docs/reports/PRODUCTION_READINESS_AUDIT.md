# Production-Readiness Audit — engineering-quality milestone

_Cleanup-only milestone. No new features. No change to the detector, classifier,
OCR, thresholds, review workflow, live-collection workflow, cursor preview, or
automation. Every behaviour-bearing subsystem is byte-for-byte unchanged; the full
unit suite is green before and after (**1075 passed, 1 skipped**)._

## Executive summary

The codebase was already in good internal health: **0 TODO/FIXME/HACK in `src/`,
0 bare `except:`, 0 never-imported modules, 0 high-confidence dead code** (vulture,
`--min-confidence 80`). The real debt was **repository clutter** — 22 loose files in
the project root — and a few stale doc pointers. This milestone is therefore a
**declutter + documentation** pass, not code surgery. Nothing in a frozen subsystem
was touched; the one `src/` edit is a single doc-path fix inside a docstring.

## 1. Dead-code audit

| Check | Method | Result |
|---|---|---|
| Unused modules | import-graph scan over `src/` + `tests/` (every dotted path + `from pkg import leaf`) | **0** never-imported modules |
| Dead functions/vars | `vulture src --min-confidence 80` | **0** items |
| TODO/FIXME/HACK/XXX | grep `src/` | **0** |
| Bare `except:` | grep `src/` | **0** |
| Stray runtime `print()` | grep `src/` | only in offline CLIs (`evaluate.py`, `weakening_eval.py`, `active_learning.py`), never in the runtime pipeline |

**Nothing was removed from `src/` because nothing is dead.** The `vulture
--min-confidence 60` pass surfaced 94 candidates, but every one is a **false
positive that must remain**:

- `navigate` / `list_tabs` / `connected` on the browser adapters
  (`attended_adapter`, `cdp_attach_adapter`, `playwright_adapter`, `stubs`) —
  **`BrowserPort` / `TabSourcePort` Protocol methods**, called polymorphically
  through the ports layer, not by name.
- `_check_target_params` / `_check_shape` / `model_config` in `config_models.py` —
  **pydantic validators / config**, invoked by pydantic at validation time.
- Metrics/telemetry fields (`p50_duration_ms`, `error_rate`, `pending_writes`,
  `overload_state`, …) — **serialized schema** consumed by the persistence and
  dashboard layers.

Removing any of these would break the hexagonal port contracts or the persisted
data schema, so they are documented here and kept.

**Compatibility shims — kept, with rationale:**

| Shim | File | Why it must remain |
|---|---|---|
| Legacy `max_weakening_pct` (0–100) key | `forge/worlds.py` | reads existing `worlds.json` files written by older builds |
| Legacy dict/list dataset shape tolerance | `forge/collection/validate.py` | reads datasets committed in earlier shapes |

These guard **persisted user/contributor data on disk**; they are not obsolete.

## 2. Repository cleanup (the main change)

The project root held **22 loose files** (17 milestone reports + 3 guides + 2
research bundles' reports). New developers had to wade through a decade of
milestone history before finding `README`/`CHANGELOG`.

**Root: 22 loose `.md` → 3** (`README.md`, `CHANGELOG.md`, `CLAUDE.md`). Nothing
was deleted — everything was relocated with `git mv` (history preserved):

| Moved | From | To |
|---|---|---|
| 17 milestone reports | root | `docs/reports/` |
| `classifier_v2/` + `live_classifier_hardening/` research bundles | root | `docs/reports/` (co-located with their reports, so the reports' bare-relative links still resolve) |
| `LIVE_DATA_COLLECTION_GUIDE.md` | root | `docs/` |
| `RELEASE_BASELINE.md`, `RELEASE_CHECKLIST.md` | root | `docs/` |

**Added for navigability:** `docs/reports/README.md` (an indexed table of the
archived reports) and a `docs/reports/` + `Marek/` pointer in `CLAUDE.md`.

**Reference integrity (all updated, nothing left dangling):**
- `docs/handoffs/CURRENT_FORGE_STATE.md` — 6 report links + 1 guide link rewritten
  to `docs/reports/…` / `docs/…`.
- `src/bap/gui/cursor_calibration.py` docstring — the one `M5A1_…REPORT.md` pointer
  rewritten to `docs/reports/M5A1_WINDOWS_GEOMETRY_REPORT.md` (comment only; **no
  code change**).
- `.gitignore` — root-anchored `/classifier_v2/` added, because
  `python -m bap.forge.research` regenerates `classifier_v2/` at the repo root; the
  committed evidence snapshot now lives at `docs/reports/classifier_v2/`, so the
  regenerated copy is ignored instead of reappearing as clutter.

Verified no `src/` or `tests/` code path reads a moved artifact (only
`research/__main__.py` names `classifier_v2/`, and that is its own **output** dir,
resolved relative to cwd — unaffected).

## 3. Performance audit

Scope was limited by the freeze: the potential hotspots the brief lists (repeated
image decode, classifier construction, dataset scans) all live **inside the
detector / classifier / collection subsystems, which are frozen this milestone**.
Where those were measurable, prior milestones already addressed them and the fixes
are still in place — e.g. the Capture-All path builds the detector+classifier
**once per batch, not per World** (see `CAPTURE_ALL_CONCURRENCY_REPORT.md`), and the
corpus `load_all()` refresh runs **off the GUI thread**. No new algorithmic change
was made (and none is permitted). No safe, measurable, in-scope optimisation was
found that isn't already done.

## 4. Startup audit (measured)

Measured with `python -X importtime` and warm-construction timing (offscreen Qt):

| Fact | Measurement |
|---|---|
| `import bap.gui.gui_main` loads cv2 / numpy / detector / classifier? | **No** — all four are `not-loaded` after import (verified via `sys.modules`). The vision stack is already lazy-imported and only loads when a scan/capture actually runs. |
| `MainWindow(--forge)` construction (warm, best of 3) | **46 ms** |
| Cold module import (subprocess, incl. Qt bridge, **excl.** cv2) — Review / Collection / Debugger | **1.13 s / 0.70 s / 0.81 s** |
| Eager `load_all()` / `dataset_statistics` at startup or dashboard build? | **None** — the dashboard does not scan the corpus at construction. |

**Conclusion: startup is already well-structured.** The dominant cost is the
unavoidable one-time import of PySide6 (and, on first scan, OpenCV) — inherent to a
Qt vision app. Construction does no avoidable work (46 ms), and the heavy libraries
are already deferred. **No lazy-load change was warranted**; adding one would be
churn against already-lazy code.

## 5. Memory audit

No change made; findings from inspection + existing guarantees:

- **No corpus retained at startup** — `load_all()` is not called at app or dashboard
  construction (§4); the full corpus is read on demand and not held.
- **Single frame in flight** — the capture path processes one image at a time and
  never pickles/duplicates frames across processes (`CAPTURE_ALL_CONCURRENCY_REPORT.md`
  §7; peak memory unchanged there).
- **No leaked Qt worker refs** — the async capture worker holds only the job, never
  a widget (asserted by `test_capture_async.py::test_worker_touches_no_gui_object`).

Deeper image-copy/QPixmap-retention tuning would require editing the frozen
review/collection/detection code and is therefore **out of scope**; recorded as
remaining debt below.

## 6. Code consistency

Already consistent; **no style rewrites made** (per the brief). Evidence:
`from __future__ import annotations` + PEP 604 typing throughout, `logging` used in
13 modules with no bare excepts, module docstrings present on the audited files.
The `print()` calls that exist are confined to offline CLI/eval tools
(`evaluate.py`, `weakening_eval.py`, `active_learning.py`) where stdout **is** the
interface — left as-is.

## 7. Test audit

- **Suite:** 1075 passed, 1 skipped, **421.9 s** (7:01), offscreen.
- **No obsolete or duplicate tests found.** The 3 `test_classifier_wiring` "reaches
  classifier" tests assert different post-conditions (non-empty bank vs live
  diagnostics vs validation section) and are not redundant.
- **Slowest tests are inherent real-vision coverage** and must remain: detector
  regression over the corpus (**43.5 s**), bundled-classifier non-empty (27 s), live
  dataset eval (18.6 s + 18.3 s), pipeline-drift parity (17.4 s). They run genuine
  OpenCV over the committed frames and exercise the **safety-critical, frozen**
  subsystems (`wrong-accepted = 0`, localization recall). Speeding them up means
  shrinking the corpus or mocking the pipeline — both reduce coverage or touch
  frozen code. **No test was removed, merged, or weakened.**

## 8. Documentation audit

- `README.md` — the Forge-contributor pointer (added last milestone) now points at
  `Marek/`; general BAP sections unchanged.
- `CLAUDE.md` — added a `docs/reports/` + `Marek/` location pointer.
- `docs/handoffs/CURRENT_FORGE_STATE.md` — report/guide links repointed to their new
  homes.
- `docs/reports/README.md` — **new** index of the archived reports.
- Contributor docs (`Marek/`) — unchanged and still correct.

## 9. Deliverable summary

**Removed:** nothing deleted — 0 files, 0 lines of code. (No dead code existed; the
conservative call was to relocate, not delete, historical reports.)

**Relocated:** 22 root files → `docs/` (`git mv`, history preserved). Root `.md`
count **22 → 3**.

**Simplified:** the project root now shows only `README.md`, `CHANGELOG.md`,
`CLAUDE.md`, `pyproject.toml`, `.gitignore`, `.gitattributes`, and source dirs — a
new developer sees the essentials immediately.

**Files affected (13):** `docs/reports/*` (19 moved in + new index), `docs/*`
(3 guides moved in), `.gitignore`, `CLAUDE.md`, `docs/handoffs/CURRENT_FORGE_STATE.md`,
`src/bap/gui/cursor_calibration.py` (docstring path only). **Zero** changes under
`src/bap/forge/detection`, `…/collection`, `…/cursor`, or any threshold/model file.

**Measurable outcomes:**
- Root file count: **22 → 3** loose `.md`.
- Startup: cv2/numpy/detector **not loaded** at app import (verified); construction
  **46 ms** — unchanged (already optimal).
- Memory: unchanged (no eager corpus retention; single-frame capture; no leaked Qt
  refs) — all pre-existing guarantees re-verified.
- Test runtime: **421.9 s**, 1075 passed / 1 skipped — unchanged (no test edited).

**Startup comparison:** before = after (46 ms construction; vision stack lazy). No
regression, no improvement claimed — the point of the measurement was to confirm no
avoidable work exists, and it doesn't.

**Memory comparison:** before = after (no code changed on the hot path).

**Test-runtime comparison:** before = after (~7:01; no test changed).

## 10. Remaining technical debt (documented, out of scope this milestone)

1. **Slow real-vision tests (≈2.5 min of the 7 min).** Inherent to running OpenCV
   over the committed corpus; a future non-frozen milestone could add a fast
   `-m "not slowvision"` marker to split a quick inner-loop suite from the full
   safety suite **without** deleting coverage.
2. **`classifier_v2/` committed evidence (~260 KB JSON/PNG).** Regenerable via
   `python -m bap.forge.research`; kept as the benchmark's evidence snapshot. Could
   be dropped once the benchmark is re-run and the numbers are quoted inline.
3. **Image-copy / QPixmap-retention review** in the review/collection/detection GUI
   was deferred because those files are frozen this milestone.
4. **Generic BAP engine surface** (`bap.core`, `bap.app`, `bap.adapters`) carries
   port methods the Forge product doesn't call directly (they satisfy Protocols).
   Not dead, but a future decision could narrow the engine to the Forge subset if
   the generic framework is never revived.

_No behaviour changed. The audit's finding is that the code was already clean; the
value delivered is a navigable repository and verified, documented health._
