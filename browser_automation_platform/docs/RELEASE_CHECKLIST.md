# Release Checklist

Steps to cut a release of the Browser Automation Platform. This checklist was
used for **v0.1.0**.

## Supported environment

- **Python:** 3.11 and 3.12 (`requires-python = ">=3.11"`).
- **OS:** Linux and Windows for headless runs; the GUI needs a display (or
  `QT_QPA_PLATFORM=offscreen`). Real browser runs require a Playwright-managed
  Chromium/Firefox/WebKit.

## Installation (verify on a clean environment)

```bash
python -m venv .venv && . .venv/bin/activate
pip install "browser-automation-platform[production]"   # headless
pip install "browser-automation-platform[gui]"          # optional GUI
playwright install chromium                              # for --real runs
bap --version                                            # smoke check
bap validate-config config/production.example.yaml
```

Editable/from-source:

```bash
pip install -e ".[production,gui,dev]"
```

## Pre-release verification

- [ ] Working tree clean; on the release branch.
- [ ] `bap/__init__.py __version__` matches `pyproject.toml [project].version`
      (guarded by `tests/unit/cli/test_packaging.py`).
- [ ] `CHANGELOG.md` has a dated section for this version.
- [ ] Full test matrix green (see below).
- [ ] Benchmarks show no regression vs `docs/PRODUCTION_RISK_REPORT.md`
      (throughput ~13–14k ticks/s flat 1→16; memory growth ~0; threads return
      to baseline; persistence ~0.8 ms/write; recovery bounded; scheduler never
      pauses).
- [ ] Wheel builds and declares the three console scripts + all extras.

## Test matrix

```bash
pytest                                   # default unit/component (+ reliability + boundary)
pytest -m load                           # 1/4/8/16-session load benchmarks
pytest -m stress                         # recovery + persistence stress
QT_QPA_PLATFORM=offscreen \
  PLAYWRIGHT_EXECUTABLE_PATH=<chrome> \
  pytest -m integration                  # real Playwright
```

Last run (v0.1.0): default **563 passed, 1 skipped**; load **15**; stress
**9**; integration **5**.

The `integration` job needs a real browser binary; `gui` tests need PySide6 and
run under `QT_QPA_PLATFORM=offscreen`. The one skip is a root-only
write-permission case.

## Build & inspect the distribution

```bash
pip wheel . --no-deps -w dist/
python - <<'PY'
import zipfile, glob
z = zipfile.ZipFile(glob.glob("dist/*.whl")[0])
print(z.read([n for n in z.namelist() if n.endswith("entry_points.txt")][0]).decode())
PY
```

Expect `bap`, `bap-run`, `bap-gui` under `[console_scripts]` and
`Provides-Extra: vision|gui|monitoring|plugins|production|dev` in `METADATA`.

## Tag & release

```bash
git tag -a v0.1.0 -m "Browser Automation Platform 0.1.0"
git push origin v0.1.0
```

Then draft the GitHub release from the tag using the notes in
`docs/RELEASE_NOTES_v0.1.0.md` (or the CHANGELOG section).

## Known limitations (communicate in the release)

- No web/HTTP health endpoint yet.
- No hard per-analyzer timeout (a hung analyzer blocks its own tick).
- Signal-based graceful shutdown is a no-op where `add_signal_handler` is
  unavailable (Windows / non-main thread).
- Extras pin lower bounds only — deployers should add a constraints/lockfile.

## Windows beta build (packaging/windows)

On Windows 10/11 x64 with Python 3.11/3.12 and Inno Setup 6 (`ISCC.exe` on PATH):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

- [ ] `Output\BAP-Setup-<version>.exe` produced.
- [ ] `Output\BAP-Setup-<version>.exe.sha256` and `Output\version.txt` produced.
- [ ] Validate on a clean VM / fresh user profile:
      `powershell -ExecutionPolicy Bypass -File packaging\windows\validate.ps1 -Installer .\packaging\windows\Output\BAP-Setup-<version>.exe`
      (silent install → version → validate-config → headless run + persistence →
      logs present → GUI launches → uninstall).
- [ ] Manual sanity: Start Menu shortcut launches the GUI; `install-browser.ps1`
      fetches Chromium; uninstall offers to remove `%LOCALAPPDATA%\BAP`.

See `docs/PACKAGING.md` (build + tool rationale) and `docs/WINDOWS_BETA.md`
(end-user guide).

## Upgrade notes

- **From pre-release checkouts:** `--plain-logs` was replaced by
  `--log-format {plain,json}`. Console scripts (`bap`, `bap-run`, `bap-gui`)
  are new — reinstall (`pip install -e .`) to regenerate them.
- **Config:** unchanged and forward-compatible; validate with
  `bap validate-config <file>` before upgrading a deployment.
- **Persistence:** the SQLite schema is additive across this series; existing
  history files open unchanged.
