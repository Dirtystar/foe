"""Platform-aware application directories."""

from __future__ import annotations

import sys
from pathlib import Path

import bap.ops.paths as paths_module
from bap.ops.paths import app_home, ensure_dirs, ensure_user_config, get_paths


def test_bap_home_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "custom"))
    assert app_home() == tmp_path / "custom"


def test_windows_uses_localappdata(monkeypatch):
    monkeypatch.delenv("BAP_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\beta\AppData\Local")
    home = app_home()
    assert home == Path(r"C:\Users\beta\AppData\Local") / "BAP"


def test_linux_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.delenv("BAP_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert app_home() == tmp_path / "xdg" / "BAP"


def test_get_paths_lays_out_the_standard_tree(tmp_path):
    p = get_paths(home=tmp_path)
    assert p.config_dir == tmp_path / "config"
    assert p.logs_dir == tmp_path / "logs"
    assert p.data_dir == tmp_path / "data"
    assert p.plugins_dir == tmp_path / "plugins"
    assert p.crashes_dir == tmp_path / "data" / "crashes"


def test_ensure_dirs_creates_everything(tmp_path):
    p = ensure_dirs(get_paths(home=tmp_path / "BAP"))
    for directory in p.all():
        assert directory.is_dir()


def test_get_paths_and_module_are_side_effect_free(tmp_path):
    # Computing paths must not create anything on disk.
    p = get_paths(home=tmp_path / "nope")
    assert not p.home.exists()


def test_ensure_user_config_seeds_then_preserves(tmp_path):
    bundled = tmp_path / "bundled.yaml"
    bundled.write_text("version: 1\n")
    config_dir = tmp_path / "cfg"

    target = ensure_user_config(config_dir, bundled)
    assert target == config_dir / "app.yaml"
    assert target.read_text() == "version: 1\n"

    # A second call must not overwrite user edits.
    target.write_text("version: 1\n# edited\n")
    again = ensure_user_config(config_dir, bundled)
    assert again.read_text().endswith("# edited\n")


def test_is_frozen_is_false_in_source_runs():
    assert paths_module.is_frozen() is False
