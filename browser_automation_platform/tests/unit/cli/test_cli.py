"""CLI behaviour: help, version, config validation, and dry-run guarantees."""

from __future__ import annotations

from pathlib import Path

import pytest

from bap import __version__
from bap.app.composition import Application
from bap.cli import main as bap_main
from bap.main import main as run_main
from bap.main import run

_DEV = "config/development.example.yaml"
_PROD = "config/production.example.yaml"


# --- help / version -----------------------------------------------------------


@pytest.mark.parametrize("argv", [["--help"], ["run", "--help"], ["validate-config", "--help"]])
def test_bap_help_exits_zero(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        bap_main(argv)
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("entry", [bap_main, run_main])
def test_version_prints_and_exits_zero(entry, capsys):
    with pytest.raises(SystemExit) as exc:
        entry(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


# --- validate-config ----------------------------------------------------------


def test_validate_config_ok_exits_zero():
    with pytest.raises(SystemExit) as exc:
        bap_main(["validate-config", _DEV])
    assert exc.value.code == 0


def test_validate_config_invalid_exits_two(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("profiles:\n  - id: p1\n    intervall_ms: 500\n")
    with pytest.raises(SystemExit) as exc:
        bap_main(["validate-config", str(bad)])
    assert exc.value.code == 2


def test_validate_config_missing_file_exits_two(tmp_path):
    with pytest.raises(SystemExit) as exc:
        bap_main(["validate-config", str(tmp_path / "nope.yaml")])
    assert exc.value.code == 2


def test_production_config_validates():
    # Stub registries know every referenced type; real ones are checked in the
    # --real path exercised elsewhere.
    with pytest.raises(SystemExit) as exc:
        bap_main(["validate-config", _PROD])
    assert exc.value.code == 0


# --- dry-run ------------------------------------------------------------------


async def test_dry_run_never_starts_browser_or_writes(monkeypatch, tmp_path):
    started: list[bool] = []
    original_start = Application.start

    async def spy_start(self):  # pragma: no cover - must never run in a dry run
        started.append(True)
        await original_start(self)

    monkeypatch.setattr(Application, "start", spy_start)

    store = tmp_path / "history.db"
    await run(
        Path(_DEV),
        seconds=None,
        real=False,
        real_vision=False,
        store_path=str(store),
        dry_run=True,
    )

    assert started == []              # the runtime was never started -> no browser
    assert not store.exists()         # and no persistence file was created


def test_run_dry_run_via_cli_exits_zero(tmp_path):
    store = tmp_path / "history.db"
    with pytest.raises(SystemExit) as exc:
        bap_main(["run", _DEV, "--dry-run", "--store", str(store)])
    assert exc.value.code == 0
    assert not store.exists()


def test_run_invalid_config_via_cli_exits_two(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("profiles:\n  - id: p1\n")  # missing rule_pack
    with pytest.raises(SystemExit) as exc:
        bap_main(["run", str(bad), "--dry-run"])
    assert exc.value.code == 2
