"""Chromium installation for real (--real) automation, driven from the GUI.

Wraps Playwright's own installer so a non-developer never needs a command line:
the GUI calls `install_chromium()` on a worker thread and streams progress. The
browser is installed into the per-user data directory so it is writable without
admin rights and is found again at launch (the same `PLAYWRIGHT_BROWSERS_PATH`).

Operational plumbing only — no core/runtime imports; Playwright is imported
lazily so this module loads even when the browser extra is absent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from bap.ops.paths import get_paths

ProgressFn = Callable[[str], None]
RunnerFn = Callable[[list[str], dict, "ProgressFn | None"], int]

# chrome executable, relative to a chromium-* build dir, per platform.
_CHROME_RELATIVE = (
    "chrome-win/chrome.exe",
    "chrome-linux/chrome",
    "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
)


def browsers_dir() -> Path:
    """Where Playwright browsers live for this install: the explicit
    `PLAYWRIGHT_BROWSERS_PATH` if set, else the per-user data directory."""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    return get_paths().data_dir / "ms-playwright"


def configure_browser_path() -> str:
    """Point Playwright at BAP's per-user browser directory so a browser
    installed via *Tools → Install browser* is found at launch — removing the
    need for a manual PLAYWRIGHT_BROWSERS_PATH. Idempotent; never overrides an
    existing value (so dev/CI setups keep their own). Returns the path in use.

    Must run before the browser launches. The entry points call it at startup;
    because install and launch both go through `browsers_dir()`, they always
    agree afterwards.
    """
    existing = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if existing:
        return existing
    path = str(get_paths().data_dir / "ms-playwright")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path
    return path


def is_chromium_installed(directory: Path | None = None) -> bool:
    """True if a full Chromium build (not just headless shell) is present."""
    directory = directory or browsers_dir()
    if not directory.exists():
        return False
    for build in directory.glob("chromium-*"):
        if any((build / rel).exists() for rel in _CHROME_RELATIVE):
            return True
    return False


def _driver_command() -> list[str]:
    """Argv that runs `playwright install chromium` via the bundled driver,
    which works from a frozen app (no python.exe on PATH). Falls back to the
    module invocation when the driver internals are unavailable."""
    try:
        from playwright._impl._driver import compute_driver_executable

        node, cli = compute_driver_executable()
        return [str(node), str(cli), "install", "chromium"]
    except Exception:
        return [sys.executable, "-m", "playwright", "install", "chromium"]


def _driver_env(target: Path) -> dict:
    try:
        from playwright._impl._driver import get_driver_env

        env = dict(get_driver_env())
    except Exception:
        env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(target)
    # A prior runtime hook may have set this to stop postinstall downloads; here
    # we explicitly *want* to download.
    env.pop("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", None)
    return env


def _stream_subprocess(argv: list[str], env: dict, progress: ProgressFn | None) -> int:
    proc = subprocess.Popen(
        argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line and progress is not None:
            progress(line)
    return proc.wait()


def install_chromium(
    progress: ProgressFn | None = None,
    *,
    target: Path | None = None,
    runner: RunnerFn | None = None,
) -> int:
    """Install Chromium into the per-user browsers directory, streaming the
    installer's output to `progress`. Returns the process exit code (0 = ok).
    `runner` is injectable for testing."""
    target = target or browsers_dir()
    target.mkdir(parents=True, exist_ok=True)
    argv = _driver_command()
    env = _driver_env(target)
    if progress is not None:
        progress(f"Installing Chromium into {target} ...")
    run = runner or _stream_subprocess
    code = run(argv, env, progress)
    if progress is not None:
        progress("Done." if code == 0 else f"Installer exited with code {code}.")
    return code


__all__ = ["browsers_dir", "configure_browser_path", "install_chromium", "is_chromium_installed"]
