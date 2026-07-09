"""Chromium install helper (detection + install command, no real download)."""

from __future__ import annotations

from pathlib import Path

from bap.ops import browser_install


def _make_chromium_build(root: Path, name: str = "chromium-1194") -> None:
    exe = root / name / "chrome-linux" / "chrome"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")


def test_is_chromium_installed_false_when_absent(tmp_path):
    assert browser_install.is_chromium_installed(tmp_path) is False


def test_is_chromium_installed_true_when_build_present(tmp_path):
    _make_chromium_build(tmp_path)
    assert browser_install.is_chromium_installed(tmp_path) is True


def test_browsers_dir_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "pw"))
    assert browser_install.browsers_dir() == tmp_path / "pw"


def test_browsers_dir_defaults_under_data(monkeypatch, tmp_path):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("BAP_HOME", str(tmp_path / "home"))
    assert browser_install.browsers_dir() == tmp_path / "home" / "data" / "ms-playwright"


def test_install_chromium_invokes_runner_with_download_env(tmp_path):
    seen: dict = {}

    def fake_runner(argv, env, progress):
        seen["argv"] = argv
        seen["env"] = env
        if progress:
            progress("downloading...")
        return 0

    lines: list[str] = []
    code = browser_install.install_chromium(
        progress=lines.append, target=tmp_path / "pw", runner=fake_runner
    )

    assert code == 0
    assert (tmp_path / "pw").is_dir()               # target created
    assert seen["argv"][-2:] == ["install", "chromium"]
    assert seen["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "pw")
    assert "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD" not in seen["env"]  # we DO want to download
    assert any("Done" in line for line in lines)


def test_install_chromium_reports_nonzero_exit(tmp_path):
    lines: list[str] = []
    code = browser_install.install_chromium(
        progress=lines.append, target=tmp_path / "pw", runner=lambda a, e, p: 3
    )
    assert code == 3
    assert any("code 3" in line for line in lines)
