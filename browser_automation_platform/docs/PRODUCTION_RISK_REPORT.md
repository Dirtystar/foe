# Production Risk Report — Load & Stress Hardening

Scope: validate runtime behaviour under realistic workloads using the real
runtime wired to stub adapters (no architecture bypassed, no test-only hooks
in production code beyond added observability). Drivers are deterministic
(`run_once` + drained recovery) except where real-time scheduling is required.

Harness: `tests/loadkit.py`; scenarios in `tests/load/` and `tests/stress/`
(run with `-m load` / `-m stress`; deselected from the default suite).

---

## Summary

The platform is stable under the target workload (1–16 sessions). No memory,
thread, or asyncio-task leaks were found. Recovery is correctly isolated and
bounded. Persistence keeps up with realistic tick rates and flushes cleanly.

**One real defect was found and fixed:** `create_application` silently dropped
`on_report`/`sleep` when a pre-built `scheduler` was injected — it now raises
instead (`ValueError`). Two scaling risks are documented below as
known-and-monitored rather than fixed, because fixing them would require
architectural change disproportionate to current needs.

---

## Measured results (this environment)

| Scenario | Result |
|---|---|
| Throughput (stub, single event loop) | ~13–14k ticks/s, flat from 1→16 sessions |
| Fairness | Every session ticked exactly N times per N rounds — zero starvation |
| Memory growth (4000 ticks, 8 sessions) | −1 objects — no per-tick retention |
| Thread lifecycle (10 store open/close) | baseline 1 → 1 — every writer thread joined |
| asyncio tasks after shutdown | ≤ baseline — all job tasks terminated |
| Slow (hung) session | Other sessions kept ticking (cooperative loop holds) |
| Scheduler interval accuracy | Every requested sleep == configured interval (no scheduler-induced drift) |
| Jitter | interval + rng()·jitter exactly, bounded |
| Recovery isolation | 1 crashing session recovered; other 7 opened once, untouched |
| Recovery bound | Permanently-broken session recreated ≤3× then disabled |
| Disabled session | Stops ticking — no further tab opens or capture calls |
| Persistence volume | 4800 ticks + 4800 actions persisted, 0 lost, 0 failed |
| Write latency | avg 0.88 ms, max ~129 ms (first write / WAL checkpoint) |
| Writer queue | Drains to 0 between bursts and on `close()` |
| WAL | Enabled (concurrent-reader friendly) |
| Slow writer | Tick loop finished in <0.2s for 200 ticks while writer lagged — enqueue never blocks runtime |

---

## Tested limits

- **Concurrency:** validated 1, 4, 8, 16 concurrent sessions on one asyncio
  loop. Fairness and isolation hold at 16.
- **Volume:** 4800 ticks/actions persisted in one burst with zero loss.
- **Failure density:** a permanently-failing session and a transiently-failing
  session under an 8-session load; recovery stayed isolated and bounded.

These are validated *functional* limits with stub adapters — i.e. the
orchestration, recovery, persistence, and scheduling logic are correct at
these scales. They are **not** real-browser throughput numbers.

---

## Expected production limits

Real limits are set by the browser and vision work, not the orchestration:

- **Playwright/Chromium:** each real tab is ~tens–hundreds of MB RAM and real
  CPU for rendering + screenshots. 8 tabs is comfortable on a developer
  machine; 16+ depends on host RAM/CPU. This is the dominant constraint.
- **Vision:** OCR/template matching are CPU-bound (tens–hundreds of ms per
  frame). At 8 sessions capturing every ~500 ms, vision is the real
  throughput ceiling, and today it runs inline on the event loop (see risks).
- **Persistence:** SQLite comfortably absorbs the realistic rate (a few writes
  per second per session). At ~0.9 ms/write it sustains >1000 writes/s
  single-threaded — far above any realistic tick rate.

Practical guidance: **8 sessions at ≥300 ms intervals is the comfortable
production envelope** on a single machine; treat 16 as the upper bound pending
the vision-offload fix below.

---

## Identified bottlenecks / scaling risks (documented, not fixed)

1. ~~**Vision runs inline on the event loop.**~~ **FIXED.** `AsyncVisionPipeline`
   (`adapters/vision/async_pipeline.py`) offloads analyzer execution to a shared
   `ThreadPoolExecutor` (`create_application(vision_workers=N)`; default 4 with
   `--real-vision`). A drop-in subclass of `VisionPipeline`, so CaptureBinding,
   TabSession, and the analyzer port are unchanged. Measured: with one blocking
   (20 ms) analyzer, a co-scheduled fast session ticked **20× inline vs 700×
   offloaded** in the same 0.4 s window. Threads are joined on `Application.stop`
   (`shutdown(wait=True)`). Note: still thread-based, so genuinely parallel
   CPU work is bounded by the GIL for pure-Python analyzers — cv2/tesseract
   release the GIL during native work, so real OCR/template matching parallelise;
   a `ProcessPoolExecutor` variant is the next step only if a pure-Python
   analyzer becomes the bottleneck.

2. ~~**Recovery pauses the whole scheduler.**~~ **FIXED.** The Scheduler now
   supports safe runtime job mutation — `register_job` / `unregister_job` /
   `replace_job` operate while it keeps ticking, each job running in its own
   task with a per-job cancel event so cancellation interrupts only the *sleep*,
   never an in-flight *tick*. `SessionManager.recover_session` now uses
   `replace_job` (no stop/start), and create/close use register/unregister — so
   no runtime lifecycle operation pauses the scheduler. Verified: recovery
   (single and 4-way concurrent) while running never stops the scheduler; a
   16-session live-scheduler run with continuous periodic failures kept every
   session ticking (15–16 ticks each, no starvation), recovered the flaky
   sessions repeatedly, and the scheduler never paused. Invariants covered by
   tests: in-flight tick finishes normally on removal, no second tick after
   removal, no duplicate/lost jobs under concurrent replacement, fairness
   preserved across replacement, failed replacement leaves a consistent state.

3. ~~**Writer queue is unbounded.**~~ **FIXED.** The write buffer is now bounded
   (`SqliteStateStore(max_queue_size=N)`, default 10 000) with a non-blocking,
   priority-aware overload policy: the runtime never blocks on storage, and when
   the buffer is full, records are dropped lowest-priority-first (LOW successful
   history → NORMAL action successes → IMPORTANT failures), while CRITICAL
   health/recovery events bypass the bound and are never dropped. `stats()` now
   exposes `pending`, `dropped`, `overloaded`, and write latency. Verified under
   a 16-session load against a 50-slot buffer + slow writer: 3200 ticks
   enqueued, ~3142 dropped by priority, **every session still completed all
   ticks**, and written+dropped reconciled exactly (no silent loss).
   **Tradeoff:** under sustained overload, low-priority tick *history* is
   sacrificed to keep the runtime responsive and the diagnostic
   (health/failure) record intact — a deliberate lossy-telemetry choice, not
   backpressure. The residual risk is a sustained flood of CRITICAL records
   (bypasses the bound); bounded in practice by how often health transitions
   occur.

4. **WAL checkpoint latency spikes.** Max write latency (~129 ms) corresponds
   to WAL setup / autocheckpoint, versus ~0.9 ms typical. Not a correctness
   issue; if it matters, tune `wal_autocheckpoint` or checkpoint on a timer.

---

## Fix applied

- **`create_application` mutually-exclusive scheduler vs on_report/sleep.**
  Passing a pre-built `scheduler` together with `on_report` or `sleep`
  previously dropped the latter silently (the injected scheduler kept its own
  config), so reports never reached the sink. Now raises `ValueError`. Found by
  the scheduler-validation harness; covered by a unit test.

- **Persistence observability added** (`SqliteStateStore.stats()` /
  `pending_writes`) — required to measure the persistence-stress scenario and
  to monitor risk #3 in production.

No other production code was changed: the load/stress work is otherwise pure
test harness over existing ports.

---

## Next scaling risks (in priority order)

1. ~~Offload CPU-bound vision analyzers~~ — **done** (AsyncVisionPipeline). A
   `ProcessPoolExecutor` variant remains a future option if a *pure-Python*
   analyzer (not GIL-releasing cv2/tesseract) becomes the bottleneck.
2. ~~Dynamic per-job scheduler mutation~~ — **done** (register/unregister/
   replace while ticking; recovery no longer pauses the scheduler).
3. ~~Bounded/backpressured persistence queue~~ — **done** (bounded + priority
   dropping). A future refinement could make dropped-priority thresholds
   configurable per deployment.
4. Real-browser resource benchmarking at 8/16 tabs (RAM/CPU) — **now
   observable**: browser resource monitoring (memory/CPU/pages/contexts) is
   collected via a `BrowserMetricsPort`, persisted to a `browser_metrics`
   table, shown on the dashboard, and enforced against configurable limits
   that raise `RESOURCE_PRESSURE` (a browser-level health signal driving a
   bounded degrade → recover → disable policy). Memory/CPU require the
   `monitoring` extra (psutil); without it, page/context counts still work and
   memory/CPU report None. What remains is establishing *deployment-specific*
   limits from real hardware — a tuning exercise, not a code gap.

---

## Plugin extensibility (entry-point discovery)

Third-party analyzers/action handlers install as normal packages and are
discovered via `importlib.metadata` entry points (`bap.analyzers`,
`bap.actions`); see `docs/PLUGINS.md`. Discovery is explicit (a caller merges
plugins into a registry), injectable/testable, and has no global state.
Invalid plugins fail during composition (bad import/non-callable →
`PluginError`; wrong return type → `CompositionError` when the handler/analyzer
is instantiated and type-checked before the browser starts). Name collisions
with built-ins are conflict errors unless explicitly overridden.

**Residual risk — plugin trust.** Installing a plugin runs its code with the
same capabilities as a first-party adapter; there is no sandbox. This is by
design (the extension seam), but it means plugin installation is a trust
decision equivalent to adding a dependency. A future hardening option is an
allowlist of permitted entry-point names in config, or running plugin
analyzers in the existing vision worker-process pool for a degree of
isolation — deferred, as it trades flexibility for containment and needs a
product decision.

## Resource monitoring (this milestone)

- **Observational-first, adapter-isolated.** `BrowserMetricsPort.collect()`
  returns a generic `BrowserResourceSnapshot` (no Playwright/Chromium types in
  core). The Playwright adapter reads page/context counts from the browser and
  memory/CPU best-effort via psutil over the Chromium process tree; a missing
  process or absent psutil yields None, never an error.
- **Rides the existing report stream.** A `ResourceMonitor` sits in the report
  sink chain (like Supervisor/PersistenceSink), forwards every report, and uses
  the report cadence to trigger periodic collection *off* the callback — no
  TabSession change, no second event system. Measured: monitoring adds
  negligible tick-throughput overhead (0.137s vs 0.135s baseline over 200
  rounds × 8 sessions; 16 sessions monitored show no starvation).
- **Bounded pressure policy.** Limits (`max_memory_mb`, `max_pages`) are
  evaluated per snapshot; breaches feed a `ResourcePressurePolicy` in the
  Supervisor that degrades on brief pressure, recovers all sessions once at a
  sustained threshold, and disables them only if pressure persists — it never
  kills the browser directly.
- **Residual risk:** memory attribution is browser-global (not per-tab), so the
  recover/disable actions are coarse (all sessions). Per-tab memory attribution
  (CDP per-target metrics) would allow targeting the heaviest tab — a future
  refinement, not required for safe operation.

## Operational lifecycle (this milestone)

Turns the startup/shutdown/observability edges from ad-hoc into a hardened,
testable layer. New code lives under `src/bap/ops/` (logging, validation,
status, lifecycle); wired only at the composition roots (`main.py`,
`gui_main.py`) — no runtime component (TabSession, Scheduler, Supervisor,
stores) changed. StateStorePort is unchanged; no new event bus (status rides
the existing `on_health` callback chain).

- ~~**Ad-hoc log strings, no correlation.**~~ **FIXED.** `log_event` emits a
  stable event name plus `key=value` correlation fields (`profile_id`,
  `tick_id`, `status`, `error_category`, `health`, recovery/plugin/action
  where relevant) via a `StructuredFormatter`. Plain `logger.info` calls are
  untouched (no fields → nothing appended), so existing consumers still work.
  `--plain-logs` disables the field suffix.
- ~~**No startup validation — misconfig surfaces mid-run.**~~ **FIXED.**
  `validate_startup` runs *before the browser launches* and fails fast with an
  actionable `OperationalError`: capacity vs `max_sessions`, positive
  intervals, sane resource limits (≥128 MB when monitoring is enabled),
  writable persistence path, and (when registries are supplied) analyzer/action
  type resolution. Complements — does not replace — the pydantic load-time gate
  and composition-time type check. `main()` exits non-zero without a traceback.
- ~~**Shutdown correctness unverified.**~~ **HARDENED.** Teardown is wrapped in
  `IdempotentShutdown` so overlapping triggers (SIGTERM/SIGINT + timed expiry +
  `finally`) collapse into exactly one clean shutdown; SIGTERM/SIGINT now
  request a graceful stop (`loop.add_signal_handler`) instead of a hard
  interrupt. Verified: clean start/stop returns to baseline task **and** thread
  counts with every tab closed (opens == closes); shutdown mid-tick and
  mid-recovery (real in-flight recovery tasks) both complete with no leaked
  asyncio tasks/threads; persistence drains on `close()`. The GUI's `closeEvent`
  path (stop loop → stop runtime → close store) is unchanged and still valid.
- ~~**No operational readiness signal.**~~ **FIXED.** An `OperationalState`
  machine (`starting → ready → degraded → stopping → stopped`) derives
  `ready↔degraded` from the same health events the sinks see, and pushes changes
  through a single `on_change` fanned out to the headless logs (a `status`
  event) and the GUI (a status label via one Qt signal). No HTTP endpoint yet
  (explicitly out of scope); the state object is the seam a future
  health/readiness HTTP probe would read.
- **Residual risks.** (1) Signal handling is a no-op on platforms/threads where
  `add_signal_handler` is unavailable (e.g. Windows / non-main thread) — there
  the `KeyboardInterrupt`/GUI-close paths still apply, but a Windows service
  wrapper would need its own stop hook. (2) `validate_startup` checks *path*
  writability, not disk space or SQLite file health — a corrupt existing DB
  still surfaces at first write (logged, non-fatal). (3) Orphan-Chromium
  prevention rests on `Application.stop` closing every tab and the browser; it
  is verified with stub adapters (opens == closes) and the Playwright adapter's
  `close`, but a hard `kill -9` of the Python process still can't guarantee
  child cleanup — an OS-level concern outside the runtime.

## Deployment / package readiness (this milestone)

Makes the hardened runtime installable and operable by a non-developer, without
touching core or changing runtime behaviour. All new code is at the CLI/entry
and packaging layer (`bap/cli.py`, extended `bap/main.py` and `gui_main.py`,
`pyproject.toml`, config examples, docs); the core (`bap/core/`) and the
runtime flows are unchanged.

- ~~**No installable distribution / console entry points.**~~ **FIXED.**
  `pyproject.toml` now declares three console scripts — `bap` (dispatcher),
  `bap-run`, `bap-gui` — and groups optional extras `vision`, `gui`,
  `monitoring`, `plugins`, and an umbrella `production` (self-referencing
  `[vision,monitoring,plugins]`). Metadata completed (readme, license,
  classifiers, keywords, `__version__` as the single source of truth). Verified
  by building a wheel (entry points + `Provides-Extra` present) **and** a clean
  install into a fresh virtualenv where `bap --version` and
  `bap validate-config` run from the generated scripts. A packaging test asserts
  the scripts/extras exist and every entry-point target imports.
- ~~**No pre-flight config check.**~~ **FIXED.** `bap validate-config <file>`
  loads the config, runs full startup validation (capacity, limits, path
  writability, and — with `--real`/`--real-vision` — analyzer/action/plugin type
  resolution), and exits `0`/`2` without launching a browser. Validation
  messages now name the **file**, the **field path** (e.g.
  `profiles.0.session.interval_ms`), the problem, and a **suggested fix**.
  Shipped `config/development.example.yaml` (stub, offline) and
  `config/production.example.yaml` (real stack, resource monitoring, persistence
  guidance).
- ~~**Thin, single-mode CLI.**~~ **FIXED.** Added `--version`, `--config`,
  `--store`, `--log-format {plain,json}`, and `--dry-run`. **Dry-run** builds
  the whole application (resolving plugins and type-checking every
  analyzer/action/handler) and then stops before starting — it opens no browser
  and makes no persistence writes (the store is never opened; the path is still
  validated). A test asserts dry-run never calls `Application.start` and leaves
  no store file.
- ~~**No operator documentation.**~~ **FIXED.** `docs/OPERATIONS.md` covers
  installation, first run, config structure, running headless/GUI, persistence
  location (incl. WAL sidecars), interpreting health vs operational status,
  plugin installation, and a troubleshooting table. `README.md` added as the
  quick-start entry point.
- **Release verification tests added:** CLI help/version, valid & invalid
  config exit codes (`validate-config` and `run`), dry-run-never-starts-browser,
  production-config-validates, GUI entry point builds/shows without blocking
  (`run_gui(exec_app=False)`), and a packaging-surface test. Full matrix
  unchanged: default **546 passed / 1 skipped**, `-m load` **15**, `-m stress`
  **9**, `-m integration` **5**.
- **Residual risks.** (1) Extras pin lower bounds only (`>=`); a lockfile/
  constraints file is left to the deployer. (2) No published artifact yet — the
  wheel builds cleanly but is not uploaded to an index; distribution channel is
  a release-process decision. (3) `bap validate-config` without `--real`
  validates against the built-in dev types (which include `log`/`stop_session`);
  to check the exact production adapter + plugin set, pass `--real`/
  `--real-vision` (documented). (4) No web/HTTP health endpoint — deliberately
  out of scope; the `OperationalState` seam remains ready for it.

## Release-candidate audit (v0.1.0)

A final pre-release audit across architecture, security/trust, reliability, and
performance. No new features, API additions, or architecture changes — only
correctness fixes discovered by the audit. New automated guards were added
where a boundary or failure mode was unverified.

### Architecture

- **Layering is clean.** Static boundary guards (scanning source text) now
  enforce: core imports nothing outward (config/app/adapters/gui/ops); ops
  depends only on core; config builds no runtime; app never imports gui;
  adapters never import gui; and gui is imported only lazily outside the gui
  package (so the headless runtime never requires PySide6).
- **One intentional inward dependency — documented and fenced.** Adapters
  import `bap.app.registries` / `bap.app.plugins` in the production registry
  *factory* functions that live beside the adapters. A new allowlist test
  (`test_adapters_app_dependency_is_limited_to_the_registry_seam`) permits
  exactly those two modules and fails on any other adapters→app import. This is
  the registry-assembly seam, kept deliberately (moving the factories would be
  an architecture change, out of scope).
- **No duplicate event path.** The report/health stream is the single fan-out
  (resource monitor → supervisor → persistence → log/GUI); the `core/events`
  EventBus is dormant infrastructure, not wired into the runtime, so there is no
  second event system.
- **No hidden global state.** No module-level mutable singletons, caches
  (`lru_cache`), `global` statements, or mutable default arguments in `src/`.
- **No test-only shortcuts in production.** The "for testing" hooks are all
  legitimate dependency-injection seams (injectable registries/entry points,
  step APIs like `run_once`) and dev stubs — none are conditional test
  backdoors.

### Security / trust (accepted risks)

- **Plugins execute untrusted code** with first-party capabilities (no sandbox).
  Installing a plugin is a trust decision equivalent to adding a dependency.
- **Config is trusted operator input.** Paths (`--store`, template paths),
  selectors, and URLs are taken at face value; there is no path-traversal
  sandbox because the config author is the operator, not a remote party.
- **SQLite is safe.** Every statement is parameterized (no string-built SQL);
  analytics use a dedicated read-only (`mode=ro`) connection; WAL is enabled. A
  corrupt/unopenable DB fails fast with `StorageError` (now surfaced as a clean
  CLI exit 2). Accepted: the read-only URI assumes a well-formed local path.
- **Browser lifecycle** cannot orphan the driver on normal teardown or on a
  partial start (fixed below). A hard `kill -9` of the process is still an OS
  concern outside the runtime.
- **No sensitive values are logged or persisted.** Tick/health/status logs carry
  ids, counts, durations, statuses, and error *categories* — never action
  params, typed text, selectors, or URLs. Production action handlers do not log
  params; the dev stub handler now logs them at DEBUG, not INFO. The database
  stores action type/status/rule id, never params/values. Accepted: exception
  messages and `reason` strings could echo page-derived text.

### Reliability (failure injection)

New suite `tests/unit/reliability/test_failure_injection.py` drives the real
runtime over stubs and injects each fault, asserting the loop survives, the
fault is reported, and after shutdown there are **no leaked tasks, no leaked
threads, and no orphan tabs**:

| Injected fault | Behaviour verified |
|---|---|
| Browser/capture crash during a tick | error surfaced in the report; session recovered; clean shutdown |
| Browser crash during recovery | broken session dropped (not thrashing); no leak |
| Analyzer timeout/exception | isolated as a `vision_failed` report; loop continues |
| Action handler exception | isolated as a `FAILED` action; tick still `completed` |
| Persistence write failure during shutdown | `close()` drains without raising; failure counted + reported via `on_error` |
| Corrupted SQLite database | fails fast with `StorageError` ("cannot open store") |
| Invalid plugin package | `PluginError` at composition (import failure / non-callable) |
| SIGTERM during startup | graceful teardown; no leaked tasks/threads |

**Correctness fixes made during this audit:**

- **Orphan-process on teardown (fixed).** `PlaywrightBrowserManager.stop()` was
  skipping `playwright.stop()` if `browser.close()` raised, leaking the driver
  subprocess. It now performs best-effort teardown that always reaches
  `playwright.stop()`, then re-raises the first error. Covered by
  `test_stop_still_stops_driver_when_browser_close_fails`.
- **Orphan-process on partial start (fixed).** If `launch()`/`new_context()`
  failed after the driver started, the driver leaked. `start()` now tears the
  driver down and re-raises the original error. Covered by
  `test_partial_start_failure_stops_the_driver`.
- **Best-effort shutdown reporting (fixed).** `SessionManager.shutdown()` now
  captures a `browser.stop()` failure as returned error data instead of
  propagating, honouring its documented contract.
- **Clean CLI error on a bad store (fixed).** `StorageError` (corrupt/unopenable
  persistence) exits `2` with a message instead of a traceback.
- **Test-only correctness (fixed).** `test_shutdown_during_recovery` used a
  wrong tab-id key (`"s0-tab"` vs `"s0"`) and never actually triggered recovery;
  corrected so it exercises real in-flight recovery and asserts no orphan tabs.

### Performance (no regression)

Benchmarks re-run and compared to the hardening baseline above:

| Benchmark | Baseline | This audit |
|---|---|---|
| Throughput 1/4/8/16 sessions | ~13–14k ticks/s, flat | 13.1k / 13.6k / 13.7k / 14.0k — flat |
| Memory growth (500 rounds × 8) | ~0 objects | −1 objects |
| Threads after 10 store lifecycles | baseline → baseline | 1 → 1 |
| Persistence (4800 ticks) | avg 0.88 ms/write | avg 0.77 ms/write |
| Overload dropping | written+dropped reconcile | 52+3148 = 3200, reconciles |
| Recovery storm (16 sessions) | 15–16 ticks each, no pause | 15–16 ticks each, no pause |
| Vision offload (0.4 s window) | inline 20 vs offloaded ~700 | inline 20 vs offloaded ~940 |
| Monitoring overhead | ~1.5% | within noise |

No regression attributable to the audit changes (which touch teardown, error
reporting, and log level only — not the hot tick path). The 16-session
throughput fluctuates with host load; isolated it holds ~14k ticks/s.
