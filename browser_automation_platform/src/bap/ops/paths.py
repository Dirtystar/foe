"""Platform-aware application directories.

Resolves where an *installed* build keeps its config, logs, data, and plugins,
per-OS, without breaking source/dev runs:

    Windows : %LOCALAPPDATA%\\BAP\\{config,logs,data,plugins}
    macOS   : ~/Library/Application Support/BAP/{...}
    Linux   : $XDG_DATA_HOME/BAP/{...}  (default ~/.local/share/BAP)

`BAP_HOME` overrides the base on every platform — the packaged app sets it, and
tests use it to redirect the tree into a temp dir. Nothing here creates
directories until `ensure_dirs()` is called, so importing this module is a
pure, side-effect-free computation. This is operational plumbing (where files
live), not a runtime component: core/runtime code never imports it.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_APP_DIRNAME = "BAP"


def app_home() -> Path:
    """Base directory for this application's per-user data. `BAP_HOME` wins;
    otherwise the platform convention is used."""
    override = os.environ.get("BAP_HOME")
    if override:
        return Path(override).expanduser()

    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / _APP_DIRNAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIRNAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / _APP_DIRNAME


@dataclass(frozen=True)
class AppPaths:
    home: Path
    config_dir: Path
    logs_dir: Path
    data_dir: Path
    plugins_dir: Path
    crashes_dir: Path

    def all(self) -> tuple[Path, ...]:
        return (
            self.home, self.config_dir, self.logs_dir,
            self.data_dir, self.plugins_dir, self.crashes_dir,
        )


def get_paths(home: Path | None = None) -> AppPaths:
    """Compute the standard subdirectories under the app home (no I/O)."""
    root = home or app_home()
    return AppPaths(
        home=root,
        config_dir=root / "config",
        logs_dir=root / "logs",
        data_dir=root / "data",
        plugins_dir=root / "plugins",
        crashes_dir=root / "data" / "crashes",
    )


def ensure_dirs(paths: AppPaths) -> AppPaths:
    """Create every standard directory (idempotent). Returns the same paths."""
    for directory in paths.all():
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def is_frozen() -> bool:
    """True when running from a PyInstaller/Nuitka bundle (the installed app)."""
    return bool(getattr(sys, "frozen", False))


def ensure_user_config(config_dir: Path, bundled_default: Path, *, name: str = "app.yaml") -> Path:
    """Return the per-user config path, seeding it from a bundled default on
    first run. Never overwrites an existing user config."""
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / name
    if not target.exists() and bundled_default.exists():
        shutil.copyfile(bundled_default, target)
    return target


__all__ = [
    "AppPaths",
    "app_home",
    "ensure_dirs",
    "ensure_user_config",
    "get_paths",
    "is_frozen",
]
