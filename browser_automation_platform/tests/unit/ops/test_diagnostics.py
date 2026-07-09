"""Diagnostics export bundle."""

from __future__ import annotations

import json
import zipfile

from bap.ops.diagnostics import default_destination, export_diagnostics
from bap.ops.paths import ensure_dirs, get_paths


def test_export_bundles_logs_crashes_config_and_system_info(monkeypatch, tmp_path):
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "home"))
    paths = ensure_dirs(get_paths())
    (paths.logs_dir / "bap.log").write_text("INFO started\n")
    (paths.crashes_dir / "crash-1.json").write_text('{"x": 1}')
    (paths.config_dir / "app.yaml").write_text("version: 1\n")

    out = export_diagnostics(dest_dir=tmp_path / "out")

    assert out.exists() and out.suffix == ".zip"
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
        assert "system-info.json" in names
        assert "logs/bap.log" in names
        assert "crashes/crash-1.json" in names
        assert "config/app.yaml" in names
        info = json.loads(archive.read("system-info.json"))
    assert info["product"] == "Browser Automation Platform"
    assert "version" in info and "os" in info and "browser" in info


def test_export_handles_missing_directories(monkeypatch, tmp_path):
    # Fresh home with nothing written yet: export still succeeds with just info.
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "empty"))
    out = export_diagnostics(dest_dir=tmp_path / "out")
    with zipfile.ZipFile(out) as archive:
        assert "system-info.json" in archive.namelist()


def test_default_destination_is_a_directory():
    dest = default_destination()
    assert dest.is_dir()
