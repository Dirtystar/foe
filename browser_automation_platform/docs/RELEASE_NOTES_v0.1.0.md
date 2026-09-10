# Browser Automation Platform 0.1.0

First tagged release. A generic, site-agnostic visual browser automation
platform built on Playwright with a hexagonal (ports & adapters) architecture —
it drives multiple browser tabs on a tick, reads the screen with pluggable
vision analyzers, evaluates a rule engine, and executes actions, all from YAML.

## Highlights

- **Multi-tab runtime** on a single asyncio loop with a deterministic scheduler
  and runtime job mutation (recovery never pauses the scheduler).
- **Vision** OCR + template matching, offloaded to worker threads.
- **Rule engine** with composable conditions and per-session cooldowns.
- **Resilience**: health monitoring plus bounded, isolated session recovery.
- **Persistence**: WAL SQLite with a bounded, priority-aware, non-blocking write
  buffer, and a read-only analytics repository.
- **Resource monitoring**: memory/CPU/pages/contexts with limit-driven pressure
  policy.
- **Plugins**: analyzers/actions discovered via entry points; invalid plugins
  fail at composition, not at runtime.
- **Operations**: structured logging (plain/json), fail-fast startup validation,
  idempotent graceful shutdown (SIGTERM/SIGINT), and an operational status model.
- **GUI** (PySide6) monitor and an operator **CLI** (`bap`, `bap-run`,
  `bap-gui`) with `validate-config`, `--dry-run`, and `--log-format`.

## Install

```bash
pip install "browser-automation-platform[production]"   # headless
pip install "browser-automation-platform[gui]"          # optional GUI
playwright install chromium                              # for --real runs
```

Requires Python 3.11+. See `docs/OPERATIONS.md` for first run, configuration,
persistence, health states, and troubleshooting.

## Release-candidate audit fixes

- No orphan browser/driver process on teardown or on a partial start failure.
- `SessionManager.shutdown()` reports a browser-stop failure as data.
- Corrupt/unopenable persistence file exits cleanly (`StorageError` → exit 2).
- Dev stub action handler logs params at DEBUG (keeps sensitive values out of
  the default log stream).

## Verified

- Tests: default **563 passed / 1 skipped**, load **15**, stress **9**,
  integration **5** (real Chromium).
- No performance regression vs the hardening baseline: ~13–14k ticks/s flat
  from 1→16 sessions, ~0 memory growth, threads/tasks return to baseline,
  ~0.8 ms/write persistence, recovery bounded, scheduler never pauses.

## Known limitations

- No web/HTTP health endpoint yet.
- No hard per-analyzer timeout (a hung analyzer blocks its own tick).
- Signal-based shutdown is a no-op where `add_signal_handler` is unavailable
  (Windows / non-main thread).
- Extras pin lower bounds only.

Full detail in `CHANGELOG.md` and `docs/PRODUCTION_RISK_REPORT.md`.
