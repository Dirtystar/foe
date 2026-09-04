"""GUI entry point wires up (build + show) without entering the Qt loop."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from bap.gui.gui_main import run_gui

_DEV = "config/development.example.yaml"


def test_run_gui_builds_and_shows_without_blocking(qapp):
    # exec_app=False stops before the blocking event loop; a clean build/show
    # of the window returns 0.
    assert run_gui(_DEV, exec_app=False) == 0


def test_run_gui_rejects_invalid_config(qapp, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("profiles:\n  - id: p1\n")  # missing rule_pack
    assert run_gui(str(bad), exec_app=False) == 2
