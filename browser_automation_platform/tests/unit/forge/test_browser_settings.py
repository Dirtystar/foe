"""Forge browser-mode settings (Milestone 4.16): default, persistence, migration.

The default MUST be Managed Chromium so existing installs are unchanged and no
migration is required; the choice round-trips through JSON.
"""

from __future__ import annotations

from bap.forge.browser_settings import (
    BrowserMode,
    BrowserSettings,
    load_browser_settings,
    save_browser_settings,
    windows_launch_command,
)


def test_default_is_managed_chromium():
    s = BrowserSettings()
    assert s.mode is BrowserMode.MANAGED
    assert s.is_external is False
    assert s.cdp_endpoint == "http://127.0.0.1:9222"


def test_missing_file_yields_managed_default(tmp_path):
    # Absence is never an error — an install with no settings file stays Managed.
    s = load_browser_settings(tmp_path / "does-not-exist.json")
    assert s.mode is BrowserMode.MANAGED


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "browser_settings.json"
    original = BrowserSettings(
        mode=BrowserMode.EXTERNAL, cdp_endpoint="http://127.0.0.1:9333",
        chrome_path=r"C:\chrome.exe")
    save_browser_settings(path, original)
    loaded = load_browser_settings(path)
    assert loaded == original
    assert loaded.is_external is True


def test_unknown_mode_falls_back_to_managed(tmp_path):
    path = tmp_path / "browser_settings.json"
    path.write_text('{"version":1,"mode":"quantum_browser"}', encoding="utf-8")
    assert load_browser_settings(path).mode is BrowserMode.MANAGED


def test_corrupt_file_falls_back_to_managed(tmp_path):
    path = tmp_path / "browser_settings.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_browser_settings(path).mode is BrowserMode.MANAGED


def test_windows_launch_command_uses_configured_port_and_isolated_profile():
    s = BrowserSettings(mode=BrowserMode.EXTERNAL, cdp_endpoint="http://127.0.0.1:9250",
                        chrome_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    cmd = windows_launch_command(s)
    assert "--remote-debugging-port=9250" in cmd
    assert "--user-data-dir=" in cmd
    assert "chrome.exe" in cmd
