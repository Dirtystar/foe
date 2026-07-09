"""One-click diagnostics export — a single zip a beta user can attach to a report.

Bundles the log files, any crash bundles, the current config, and a system-info
summary from the per-user data tree. Local only: it reads existing files and
writes one archive; nothing is transmitted. Log/crash contents already exclude
sensitive values (typed text, page contents, selectors, URLs) by design.

Operational plumbing only — no core/runtime imports.
"""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from bap import __version__
from bap.ops.browser_install import browsers_dir, is_chromium_installed
from bap.ops.paths import AppPaths, get_paths


def _system_info() -> dict:
    return {
        "product": "Browser Automation Platform",
        "version": __version__,
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "os": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sys_platform": sys.platform,
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "browser": {
            "browsers_dir": str(browsers_dir()),
            "chromium_installed": is_chromium_installed(),
        },
    }


def _add_tree(archive: zipfile.ZipFile, directory: Path, arc_prefix: str) -> int:
    added = 0
    if not directory.exists():
        return 0
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=f"{arc_prefix}/{path.relative_to(directory).as_posix()}")
            added += 1
    return added


def default_destination() -> Path:
    """Where the export lands by default: the Desktop if present, else home."""
    desktop = Path.home() / "Desktop"
    return desktop if desktop.is_dir() else Path.home()


def export_diagnostics(dest_dir: Path | None = None, *, paths: AppPaths | None = None) -> Path:
    """Write a diagnostics zip (system info + logs + crashes + config) and
    return its path. Creates the destination if needed."""
    paths = paths or get_paths()
    dest_dir = Path(dest_dir) if dest_dir is not None else default_destination()
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = dest_dir / f"bap-diagnostics-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("system-info.json", json.dumps(_system_info(), indent=2))
        _add_tree(archive, paths.logs_dir, "logs")
        _add_tree(archive, paths.crashes_dir, "crashes")
        _add_tree(archive, paths.config_dir, "config")
    return out


__all__ = ["default_destination", "export_diagnostics"]
