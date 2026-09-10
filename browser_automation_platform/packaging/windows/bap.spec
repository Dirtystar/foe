# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-folder Windows bundle containing two executables —
`BAP.exe` (windowed GUI) and `bap.exe` (console CLI) — sharing one embedded
CPython runtime and the bundled dependencies.

Build (on Windows, from the repo root, inside the build venv):
    pyinstaller packaging\\windows\\bap.spec --noconfirm

Output: dist\\BAP\\  (BAP.exe, bap.exe, _internal\\ ...). The Inno Setup script
(bap-setup.iss) wraps dist\\BAP into an installer.
"""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")
ICON = os.path.join(SPECPATH, "assets", "bap.ico")
VERSION = os.path.join(SPECPATH, "version_info.txt")
RUNTIME_HOOK = os.path.join(SPECPATH, "runtime_hook.py")

# Ship the example configs so first run can seed %LOCALAPPDATA%/BAP/config.
datas = [(os.path.join(ROOT, "config"), "config")]
binaries = []
hiddenimports = ["bap.cli", "bap.gui.gui_main"]

# PySide6 (GUI) and Playwright (driver + package data) need their full trees.
for pkg in ("PySide6", "playwright"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

_common = dict(
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[RUNTIME_HOOK],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

gui_a = Analysis([os.path.join(SPECPATH, "launcher_gui.py")], **_common)
cli_a = Analysis([os.path.join(SPECPATH, "launcher_cli.py")], **_common)

gui_pyz = PYZ(gui_a.pure)
cli_pyz = PYZ(cli_a.pure)

# Both executables share one COLLECT (one dist folder). `exclude_binaries=True`
# keeps the heavy dependencies out of the exes and in _internal/, where COLLECT
# de-duplicates the (identical) trees the two analyses produce.
gui_exe = EXE(
    gui_pyz, gui_a.scripts, [], exclude_binaries=True,
    name="BAP", console=False, icon=ICON, version=VERSION,
)
cli_exe = EXE(
    cli_pyz, cli_a.scripts, [], exclude_binaries=True,
    name="bap", console=True, icon=ICON, version=VERSION,
)

coll = COLLECT(
    gui_exe, cli_exe,
    gui_a.binaries, gui_a.zipfiles, gui_a.datas,
    strip=False, upx=False, name="BAP",
)
