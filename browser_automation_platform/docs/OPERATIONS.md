# Operations Guide

How to install, configure, run, and troubleshoot the Browser Automation
Platform without reading the source. If you are extending it with custom
analyzers or actions, see [PLUGINS.md](PLUGINS.md).

---

## 1. Installation

Requires **Python 3.11+**.

```bash
python -m venv .venv
. .venv/bin/activate           # Windows: .venv\Scripts\activate

pip install browser-automation-platform                 # core (stubs only)
pip install "browser-automation-platform[production]"   # real vision + monitoring + plugins
pip install "browser-automation-platform[gui]"          # add the desktop monitor
```

Installing from a checkout instead:

```bash
pip install -e ".[production,gui,dev]"
```

Optional extras:

| Extra        | Adds                                                      |
|--------------|----------------------------------------------------------|
| `vision`     | OCR (Tesseract) + template matching (OpenCV, Pillow, numpy) |
| `monitoring` | psutil — browser process memory/CPU in resource snapshots |
| `gui`        | PySide6 monitoring window                                 |
| `plugins`    | (no runtime deps) explicit target for plugin discovery    |
| `production` | `vision` + `monitoring` + `plugins` together              |
| `dev`        | pytest + pytest-asyncio                                   |

For real browser runs, install a browser once:

```bash
playwright install chromium
```

The core install runs entirely on **stub adapters** — no browser, no vision
libraries, no network — so `bap run` works immediately for a smoke test.

Verify the install:

```bash
bap --version
```

---

## 2. First run

Validate a bundled example, then run it on stubs for a few seconds:

```bash
bap validate-config config/development.example.yaml
bap run config/development.example.yaml --seconds 5
```

You will see structured tick and health log lines and a clean shutdown. No
browser opens — the development config uses stubs.

To dry-run a **real** config (resolves plugins and every analyzer/action type,
but launches nothing and writes nothing):

```bash
bap run config/production.example.yaml --real --real-vision --dry-run
```

Then a real headless run:

```bash
playwright install chromium
bap run config/production.example.yaml --real --real-vision --seconds 30
```

---

## 3. Configuration structure

Config is YAML describing **intent**; the runtime is assembled from it. Full
schemas live in `src/bap/config/config_models.py`; the shape is:

```yaml
version: 1

settings:                       # global runtime settings
  max_sessions: 8               # hard cap on concurrent tabs
  headless: true
  browser_engine: chromium      # chromium | firefox | webkit
  isolate_contexts_per_tab: true
  resource_monitoring:          # optional; observational limits
    enabled: true
    collect_every_ticks: 50
    limits: { max_memory_mb: 4096, max_pages: 16 }

rule_packs:                     # named, reusable sets of rules
  monitor:
    - id: act_when_value_low
      cooldown_ms: 3000         # minimum gap between firings (per session)
      condition:                # exists | compare | confidence | staleness | all | any | not
        type: compare
        field: panel.number     # <binding_name>.<fact>
        op: less_than
        value: 20
      actions:                  # click | type | navigate | wait | log | stop_session ...
        - type: click
          params: { selector: "#primary-action" }

profiles:                       # one browser tab each
  - id: dashboard
    start_url: "https://dashboard.example.com/"
    viewport: { width: 1600, height: 900 }
    session: { interval_ms: 1000, jitter_ms: 200 }
    rule_pack: monitor          # must name a defined pack
    capture_bindings:           # what to look at, and how to read it
      - name: panel
        target: selector        # full_page | region | selector
        selector: "#status-panel"
        analyzers:
          - type: ocr
            settings: { numeric: true }
```

Key rules the loader enforces (with a filename, field path, and suggested fix
on failure): unknown fields are rejected, profile/rule ids must be unique,
`rule_pack` must reference a defined pack, `region`/`selector` must match the
`target`, and numeric bounds (`interval_ms > 0`, etc.) are checked.

`bap validate-config <file>` runs the full schema check **plus** operational
validation (capacity vs `max_sessions`, sane resource limits, persistence-path
writability, and — with `--real`/`--real-vision` — that every analyzer/action
type resolves against the real adapters and installed plugins). It exits `0`
when valid, `2` when not, and never opens a browser.

---

## 4. Running headless

```bash
bap run <config> [options]
# or the direct entry point:
bap-run <config> [options]
```

Common options:

| Option              | Meaning                                                        |
|---------------------|----------------------------------------------------------------|
| `--config PATH`     | config file (also accepted as a positional argument)           |
| `--real`            | use real Playwright adapters instead of stubs                  |
| `--real-vision`     | use real OCR/template analyzers (offloaded to worker threads)  |
| `--store PATH`      | persist runtime history to a SQLite file                       |
| `--seconds N`       | run for N seconds then stop (default: run until signalled)     |
| `--log-format`      | `plain` (default, human key=value) or `json` (one object/line) |
| `--log-level`       | `DEBUG`/`INFO`/`WARNING`/…                                      |
| `--dry-run`         | validate + resolve everything, then exit; no browser, no writes|
| `--vision-workers N`| worker threads for real vision (default 4 with `--real-vision`)|

Shutdown is graceful: `Ctrl-C` (SIGINT) or SIGTERM (`kill`, container stop)
drains the current tick, stops the scheduler, flushes persistence, closes the
browser, and joins worker threads. Sending the signal twice is safe — shutdown
runs at most once.

Example under a process manager / container:

```bash
bap run config/production.example.yaml --real --real-vision \
    --store /var/lib/bap/history.db --log-format json
```

---

## 5. Running the GUI

```bash
pip install "browser-automation-platform[gui]"
bap gui <config>          # or: bap-gui <config>
```

The window is a **pure observer/controller**: Start/Stop/Tick buttons, a
per-session table (status, last tick, rules, actions, errors, timing, health),
a live log, an operational **Status** label (`starting → ready → degraded →
stopping → stopped`), and — when `--store` is given — a Dashboard tab with
analytics. It never runs business logic; it drives the same runtime the
headless entry point does.

---

## 6. Persistence location

Persistence is **opt-in** via `--store PATH`; without it the platform keeps no
history (logs only).

- The path you pass is a SQLite database file (created if missing). It uses
  **WAL mode**, so you will also see `-wal` and `-shm` sidecar files next to it
  while running — keep them together.
- Tables: `ticks`, `health_events`, `actions`, `browser_metrics`. Writes are
  buffered and drained on shutdown; under sustained overload, low-priority tick
  history is dropped first while health/recovery events are always kept.
- Choose a writable, persistent directory (e.g. `/var/lib/bap/history.db`).
  Startup validation checks the directory exists and is writable and fails fast
  otherwise.
- The GUI Dashboard and any analytics read this file through a **read-only**
  connection; you can safely inspect it with the `sqlite3` CLI while running.

---

## 7. Interpreting health states

Two related but distinct signals:

**Per-session health** (`SessionHealth`, one per profile, in tick/health logs
and the GUI table):

| State        | Meaning                                                             |
|--------------|---------------------------------------------------------------------|
| `healthy`    | ticking normally                                                    |
| `degraded`   | recent transient trouble (e.g. a failed capture) but still running  |
| `recovering` | the supervisor is restarting/reinitializing the session             |
| `failed`     | recovery exhausted; the session is disabled and no longer ticks     |

Recovery is bounded: a repeatedly-failing session is recreated a few times,
then disabled — it will not thrash forever. Recovery is isolated: one failing
session does not stop the others.

**Operational status** (`OperationalStatus`, one per process, in the `status`
log event and the GUI Status label):

| State      | Meaning                                                        |
|------------|----------------------------------------------------------------|
| `starting` | assembling and launching                                       |
| `ready`    | running; all sessions healthy                                  |
| `degraded` | running, but at least one session is not healthy               |
| `stopping` | graceful shutdown in progress                                  |
| `stopped`  | fully torn down                                                |

`degraded` is derived from the session health flow — the process stays up and
keeps working; it is a "look at the sessions" signal, not a crash.

---

## 8. Plugin installation

Third-party analyzers and action handlers install as ordinary packages and are
discovered via entry points (`bap.analyzers`, `bap.actions`) — no source
changes. Install the package into the same environment, then reference its
declared `type` name from config:

```bash
pip install my-bap-analyzer
bap validate-config my-config.yaml --real --real-vision   # confirms the type resolves
```

Discovery happens when the real registries are built (i.e. with `--real` /
`--real-vision`). A plugin whose name collides with a built-in is a conflict
error unless explicitly overridden; a plugin that fails to import or returns
the wrong type fails **during startup, before the browser opens**. Only install
plugins you trust — a plugin runs with the same capabilities as a first-party
adapter. Full contract and examples: [PLUGINS.md](PLUGINS.md).

---

## 9. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `Configuration error: ... at '<field>': ...` | Schema problem. The message names the file, field path, and a suggested fix. Re-run `bap validate-config <file>`. |
| `Startup aborted: ... max_sessions` | More profiles than `settings.max_sessions`. Raise the cap or remove profiles. |
| `Startup aborted: persistence directory ... not writable` | `--store` points at a missing/read-only directory. Create it or pick another path. |
| `no analyzer/handler registered for type '...'` | The config names a type no registry provides. Check spelling, or install the plugin and validate with `--real`/`--real-vision`. |
| Real run does nothing / can't find a browser | Run `playwright install chromium`. Confirm with `--dry-run` first. |
| OCR/template errors only with `--real-vision` | Missing vision extra or Tesseract. `pip install "...[vision]"` and install the Tesseract binary. |
| GUI won't import | Missing GUI extra. `pip install "...[gui]"`. On a headless host set `QT_QPA_PLATFORM=offscreen`. |
| Memory/CPU show as empty in resource metrics | `monitoring` extra (psutil) not installed. Page/context counts still work. |
| Want machine-readable logs | Add `--log-format json`. |
| Process won't stop | Send SIGTERM/SIGINT once and wait for the current tick to drain; check logs for `shutdown-requested` then `status stopped`. |

For a fast, side-effect-free health check of a config and its plugin/type
resolution, prefer `--dry-run` (or `validate-config`) — it exercises the whole
assembly path without launching a browser or writing anything.
