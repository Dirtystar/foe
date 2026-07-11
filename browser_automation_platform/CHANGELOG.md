# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
