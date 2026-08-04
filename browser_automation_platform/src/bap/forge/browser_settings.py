"""Forge browser-mode settings (Milestone 4.16) — Managed Chromium vs External Chrome.

BAP can either **manage** its own bundled Chromium (the long-standing default) or
**attach** to an operator-launched Chrome over CDP. Which one is used is an
explicit, persisted operator choice — never guessed and never silently switched.

Persisted to ``<data>/forge/browser_settings.json``. A missing file yields the
safe default (**Managed Chromium**), so existing installs are unchanged and no
migration is required. Qt-free and dependency-free so it loads anywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"


class BrowserMode(str, Enum):
    MANAGED = "managed_chromium"
    EXTERNAL = "external_chrome"

    @property
    def label(self) -> str:
        return "Managed Chromium" if self is BrowserMode.MANAGED else "External Chrome (CDP)"


@dataclass(frozen=True)
class BrowserSettings:
    """The operator's browser-mode choice and the External-Chrome connection
    details. ``chrome_path`` is only used to build the copyable launch command
    shown to the operator — BAP never launches Chrome in External mode."""

    mode: BrowserMode = BrowserMode.MANAGED
    cdp_endpoint: str = DEFAULT_CDP_ENDPOINT
    chrome_path: str = ""

    @property
    def is_external(self) -> bool:
        return self.mode is BrowserMode.EXTERNAL

    def with_changes(self, **changes) -> "BrowserSettings":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "mode": self.mode.value,
            "cdp_endpoint": self.cdp_endpoint,
            "chrome_path": self.chrome_path,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "BrowserSettings":
        data = data or {}
        raw_mode = str(data.get("mode", BrowserMode.MANAGED.value))
        try:
            mode = BrowserMode(raw_mode)
        except ValueError:
            mode = BrowserMode.MANAGED  # unknown value -> safe default
        endpoint = str(data.get("cdp_endpoint") or DEFAULT_CDP_ENDPOINT)
        return cls(mode=mode, cdp_endpoint=endpoint, chrome_path=str(data.get("chrome_path", "")))


def load_browser_settings(path: Path | str) -> BrowserSettings:
    """Load settings from JSON. A missing or unreadable file yields the safe
    default (Managed Chromium) — so absence is never an error."""
    path = Path(path)
    if not path.exists():
        return BrowserSettings()
    try:
        return BrowserSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return BrowserSettings()


def save_browser_settings(path: Path | str, settings: BrowserSettings) -> None:
    """Atomically persist settings to JSON (creating parent dirs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)


def default_settings_path():
    """The per-user settings path (``<data>/forge/browser_settings.json``)."""
    from bap.ops.paths import ensure_dirs, get_paths

    return ensure_dirs(get_paths()).data_dir / "forge" / "browser_settings.json"


def windows_launch_command(settings: BrowserSettings, *, profile_dir: str | None = None) -> str:
    """The exact Windows command the operator runs to launch a dedicated Chrome
    with remote debugging on the configured port and an isolated profile — never
    their normal personal profile."""
    from urllib.parse import urlparse

    port = urlparse(settings.cdp_endpoint).port or 9222
    chrome = settings.chrome_path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    profile = profile_dir or r"%LOCALAPPDATA%\BAP\chrome-profile"
    return f'"{chrome}" --remote-debugging-port={port} --user-data-dir="{profile}"'


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_CDP_ENDPOINT",
    "BrowserMode",
    "BrowserSettings",
    "load_browser_settings",
    "save_browser_settings",
    "default_settings_path",
    "windows_launch_command",
]
