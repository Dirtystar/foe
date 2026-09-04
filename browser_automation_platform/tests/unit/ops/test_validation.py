"""Startup validation: fail fast with actionable OperationalError messages."""

from __future__ import annotations

import os

import pytest

from bap.config.config_loader import load_config_from_string
from bap.ops.validation import OperationalError, validate_startup
from tests.loadkit import make_config


def _config(n_sessions: int = 1, **kw):
    return load_config_from_string(make_config(n_sessions, **kw))


def test_valid_config_passes() -> None:
    validate_startup(_config(2))  # 2 profiles, max_sessions=2


def test_capacity_exceeded_is_rejected() -> None:
    # Config models are frozen; model_copy rebuilds without re-validating.
    config = _config(2)
    config = config.model_copy(
        update={"settings": config.settings.model_copy(update={"max_sessions": 1})}
    )
    with pytest.raises(OperationalError, match="max_sessions"):
        validate_startup(config)


def test_non_positive_interval_is_rejected() -> None:
    # pydantic enforces interval_ms > 0 at load, so bypass it to reach the
    # defensive startup check (which guards programmatically-built configs).
    config = _config(1)
    profile = config.profiles[0]
    bad = profile.model_copy(
        update={"session": profile.session.model_copy(update={"interval_ms": 0})}
    )
    config = config.model_copy(update={"profiles": [bad]})
    with pytest.raises(OperationalError, match="interval_ms"):
        validate_startup(config)


def test_implausible_memory_limit_is_rejected() -> None:
    text = """
settings:
  max_sessions: 1
  resource_monitoring:
    enabled: true
    limits: { max_memory_mb: 16 }
rule_packs:
  pack:
    - id: r
      condition: { type: exists, field: screen.ready }
      actions: [ { type: click, params: { selector: "#x" } } ]
profiles:
  - id: s0
    rule_pack: pack
    session: { interval_ms: 10 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers: [ { type: ocr, settings: { emit: { ready: true } } } ]
"""
    with pytest.raises(OperationalError, match="max_memory_mb"):
        validate_startup(load_config_from_string(text))


def test_nonexistent_store_directory_is_rejected() -> None:
    with pytest.raises(OperationalError, match="directory does not exist"):
        validate_startup(_config(1), store_path="/no/such/dir/history.db")


def test_writable_store_path_passes(tmp_path) -> None:
    validate_startup(_config(1), store_path=str(tmp_path / "history.db"))


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses write permission bits")
def test_unwritable_store_directory_is_rejected(tmp_path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(OperationalError, match="not writable"):
            validate_startup(_config(1), store_path=str(ro / "history.db"))
    finally:
        ro.chmod(0o700)  # let pytest clean up


class _Registry:
    def __init__(self, known: set[str]) -> None:
        self._known = known

    def knows(self, name: str) -> bool:
        return name in self._known


def test_unknown_analyzer_type_is_rejected() -> None:
    with pytest.raises(OperationalError, match="analyzer type 'ocr'"):
        validate_startup(_config(1), analyzer_registry=_Registry(set()))


def test_unknown_action_type_is_rejected() -> None:
    with pytest.raises(OperationalError, match="action type 'click'"):
        validate_startup(_config(1), action_registry=_Registry(set()))


def test_known_types_pass() -> None:
    validate_startup(
        _config(1),
        analyzer_registry=_Registry({"ocr"}),
        action_registry=_Registry({"click"}),
    )
