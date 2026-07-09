# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
