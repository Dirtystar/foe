# Windows Packaging

How the Windows beta build is produced, and why it is built this way. For the
end-user guide see [WINDOWS_BETA.md](WINDOWS_BETA.md).

## Tool choice: PyInstaller vs Nuitka

**Decision: PyInstaller** (one-folder build), wrapped by **Inno Setup 6**.

| Factor | PyInstaller | Nuitka |
|---|---|---|
| Maturity / ecosystem | Very mature, huge user base | Mature but smaller community |
| PySide6 support | First-class hooks (`collect_all`) | Works via `--enable-plugin=pyside6`, more fragile |
| Playwright bundling | `collect_all('playwright')` pulls driver + data reliably | Less battle-tested for the node driver |
| Build speed | Fast (bytecode bundling) | Slow (C compilation), heavier toolchain |
| Runtime speed | Python-native (fine here) | Faster CPU-bound code |
| Two-exe onedir (GUI + CLI) | Straightforward (`MERGE`) | More involved |
| Installer integration | Clean onedir → Inno Setup | Same, but build friction is higher |

**Why PyInstaller wins for this beta.** Our runtime bottleneck is the browser
and vision work, not Python interpreter speed, so Nuitka's main advantage
(compiled CPU performance) buys us little. What we need is *reliable bundling of
two awkward dependencies* — PySide6 and Playwright — plus a fast build loop for
iterating on a beta. PyInstaller's hooks handle both dependencies out of the
box, produces a clean one-folder tree that Inno Setup wraps directly, and builds
in a fraction of Nuitka's time. We revisit Nuitka only if startup time, bundle
size, or source-protection requirements become real constraints.

**Why one-folder (not one-file).** One-folder starts faster (no per-launch
unpack to a temp dir), is friendlier to antivirus/SmartScreen heuristics, and
maps cleanly onto an Inno Setup install directory. The single-exe convenience is
provided by the installer instead.

## What the bundle contains

- **Embedded Python runtime** (CPython, via PyInstaller) — users need no Python.
- **Two executables** sharing one runtime (deduped with `MERGE`):
  `BAP.exe` (windowed GUI) and `bap.exe` (console CLI: `validate-config`, `run`).
- **Application version** stamped into both exes (`version_info.txt`) and into
  the installer; the single source of truth is `bap.__version__`.
- **Icons** (`assets/bap.ico`, multi-resolution 16–256 px).
- **Bundled example configs** (`config/*.yaml`) used to seed the per-user config
  directory on first run.
- A **runtime hook** that points Playwright at the per-user browser directory.

It deliberately does **not** bundle a browser — see the Playwright section in
[WINDOWS_BETA.md](WINDOWS_BETA.md).

## Files

```
packaging/windows/
    bap.spec            PyInstaller spec (GUI + CLI -> dist/BAP/)
    launcher_gui.py     frozen entry -> bap.gui.gui_main:main
    launcher_cli.py     frozen entry -> bap.cli:main
    runtime_hook.py     sets PLAYWRIGHT_BROWSERS_PATH under %LOCALAPPDATA%/BAP
    version_info.txt    Windows VERSIONINFO resource (0.1.0)
    assets/bap.ico      application icon
    bap-setup.iss       Inno Setup installer (per-user, Start Menu, uninstall)
    build.ps1           end-to-end build -> installer + SHA256 + version.txt
    install-browser.ps1 first-run Chromium install helper
    validate.ps1        clean-environment smoke validation
```

## Build

On Windows 10/11 x64 with Python 3.11/3.12 and Inno Setup 6 (`ISCC.exe` on
PATH), from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Steps performed: create an isolated build venv, install `.[gui,vision,monitoring]`
+ PyInstaller, assert the packaged version matches `bap.__version__`, run
PyInstaller (`dist\BAP\`), run Inno Setup, then emit the installer, its
`.sha256`, and a `version.txt` manifest into `packaging\windows\Output\`.

## Release artifacts

- `Output\BAP-Setup-0.1.0.exe` — the installer.
- `Output\BAP-Setup-0.1.0.exe.sha256` — SHA256 checksum (verify with
  `Get-FileHash`).
- `Output\version.txt` — product, version, installer name, checksum, build time,
  target, and the packaged `bap.__version__`.
