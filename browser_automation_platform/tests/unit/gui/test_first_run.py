"""First-run wizard and browser-install dialog (headless / offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from bap.gui.first_run import (
    BrowserInstallDialog,
    FirstRunDialog,
    is_first_run,
    mark_setup_complete,
)
from bap.ops.paths import get_paths


def test_first_run_marker_roundtrip(monkeypatch, tmp_path, qapp):
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "home"))
    paths = get_paths()
    assert is_first_run(paths) is True
    mark_setup_complete(paths)
    assert is_first_run(paths) is False


def test_first_run_dialog_marks_complete_on_close(monkeypatch, tmp_path, qapp):
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "home"))
    paths = get_paths()
    dialog = FirstRunDialog(paths=paths)
    assert dialog.show_again.isChecked() is False

    dialog.done(1)  # user clicked Continue
    assert is_first_run(paths) is False


def test_first_run_dialog_keeps_flag_when_show_again_checked(monkeypatch, tmp_path, qapp):
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "home"))
    paths = get_paths()
    dialog = FirstRunDialog(paths=paths)
    dialog.show_again.setChecked(True)

    dialog.done(1)
    assert is_first_run(paths) is True  # will be shown again next launch


def test_browser_install_dialog_reflects_installed_state(monkeypatch, qapp):
    import bap.gui.first_run as fr

    monkeypatch.setattr(fr.browser_install, "is_chromium_installed", lambda: False)
    dialog = BrowserInstallDialog(install_fn=lambda cb: 0)
    assert dialog.install_button.isEnabled() is True  # not yet installed

    monkeypatch.setattr(fr.browser_install, "is_chromium_installed", lambda: True)
    installed = BrowserInstallDialog(install_fn=lambda cb: 0)
    assert installed.install_button.isEnabled() is False  # nothing to do


def test_browser_install_finished_success_and_failure(qapp):
    dialog = BrowserInstallDialog(install_fn=lambda cb: 0)

    dialog._finished(0)
    assert dialog.close_button.isEnabled() is True
    assert "successfully" in dialog.output.toPlainText()

    dialog2 = BrowserInstallDialog(install_fn=lambda cb: 1)
    dialog2._finished(1)
    assert dialog2.install_button.isEnabled() is True  # can retry
    assert "failed" in dialog2.output.toPlainText().lower()
