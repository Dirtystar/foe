"""Clean-install surface: the packaging metadata that a fresh `pip install`
depends on — console scripts and optional-dependency extras — is present and
its entry-point targets import."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


@pytest.fixture(scope="module")
def project() -> dict:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]


def test_console_scripts_declared(project):
    scripts = project["scripts"]
    assert set(scripts) == {
        "bap", "bap-run", "bap-gui", "bap-forge-label", "bap-forge-review",
    }


@pytest.mark.parametrize(
    "name,target",
    [
        ("bap", "bap.cli:main"),
        ("bap-run", "bap.main:main"),
        ("bap-gui", "bap.gui.gui_main:main"),
        ("bap-forge-label", "bap.forge.labeling.__main__:main"),
        ("bap-forge-review", "bap.gui.forge_review:main"),
    ],
)
def test_console_script_targets_resolve(project, name, target):
    assert project["scripts"][name] == target
    module_name, _, attr = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # e.g. PySide6 not installed for bap-gui
        pytest.skip(f"optional dependency missing for {name}: {exc}")
    assert callable(getattr(module, attr))


def test_expected_extras_present(project):
    extras = project["optional-dependencies"]
    for group in ("vision", "gui", "monitoring", "plugins", "production", "dev"):
        assert group in extras, f"missing extra: {group}"


def test_production_extra_aggregates_the_others(project):
    production = project["optional-dependencies"]["production"]
    joined = " ".join(production)
    assert "vision" in joined and "monitoring" in joined and "plugins" in joined


def test_core_dependencies_declared(project):
    deps = " ".join(project["dependencies"])
    assert "playwright" in deps and "pydantic" in deps and "pyyaml" in deps


def test_version_matches_package(project):
    import bap

    assert project["version"] == bap.__version__
