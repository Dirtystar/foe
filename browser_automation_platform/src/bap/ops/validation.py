"""Startup validation — fail fast, before the browser launches.

Complements the two existing gates (pydantic at config load, composition-time
type resolution) with operational checks that would otherwise only surface at
runtime: persistence path writability, capacity vs. max_sessions, and
resource-limit sanity. Raises OperationalError with an actionable message.
Type resolution (analyzer/action/plugin names) remains enforced by
create_application before app.start(); optionally re-checked here when
registries are supplied.
"""

from __future__ import annotations

import os
from pathlib import Path

from bap.config.config_models import ApplicationConfig

_MIN_SANE_MEMORY_MB = 128


class OperationalError(Exception):
    """A startup precondition failed. The message is meant to be actionable."""


def validate_startup(
    config: ApplicationConfig,
    *,
    store_path: str | None = None,
    analyzer_registry=None,
    action_registry=None,
) -> None:
    _check_capacity(config)
    _check_intervals(config)
    _check_resource_limits(config)
    _check_store_path(store_path)
    if analyzer_registry is not None or action_registry is not None:
        _check_types(config, analyzer_registry, action_registry)


def _check_capacity(config: ApplicationConfig) -> None:
    n = len(config.profiles)
    limit = config.settings.max_sessions
    if n > limit:
        raise OperationalError(
            f"{n} profiles configured but max_sessions={limit}; raise max_sessions "
            f"or remove {n - limit} profile(s)"
        )


def _check_intervals(config: ApplicationConfig) -> None:
    for profile in config.profiles:
        if profile.session.interval_ms <= 0:
            raise OperationalError(
                f"profile '{profile.id}': interval_ms must be > 0, got "
                f"{profile.session.interval_ms}"
            )


def _check_resource_limits(config: ApplicationConfig) -> None:
    rm = config.settings.resource_monitoring
    if not rm.enabled:
        return
    mem = rm.limits.max_memory_mb
    if mem is not None and mem < _MIN_SANE_MEMORY_MB:
        raise OperationalError(
            f"resource_monitoring.limits.max_memory_mb={mem} is implausibly low "
            f"(>= {_MIN_SANE_MEMORY_MB} expected); a real browser needs more"
        )


def _check_store_path(store_path: str | None) -> None:
    if not store_path:
        return
    path = Path(store_path)
    parent = path.parent if str(path.parent) else Path(".")
    if not parent.exists():
        raise OperationalError(f"persistence directory does not exist: '{parent}'")
    if not os.access(parent, os.W_OK):
        raise OperationalError(f"persistence directory is not writable: '{parent}'")
    if path.exists() and not os.access(path, os.W_OK):
        raise OperationalError(f"persistence file is not writable: '{path}'")


def _check_types(config: ApplicationConfig, analyzers, actions) -> None:
    if analyzers is not None:
        for profile in config.profiles:
            for binding in profile.capture_bindings:
                for analyzer in binding.analyzers:
                    if not analyzers.knows(analyzer.type):
                        raise OperationalError(
                            f"profile '{profile.id}', binding '{binding.name}': "
                            f"analyzer type '{analyzer.type}' is not registered "
                            f"(missing plugin?)"
                        )
    if actions is not None:
        for name, rules in config.rule_packs.items():
            for rule in rules:
                for action in rule.actions:
                    if not actions.knows(action.type):
                        raise OperationalError(
                            f"rule pack '{name}', rule '{rule.id}': action type "
                            f"'{action.type}' is not registered (missing plugin?)"
                        )


__all__ = ["OperationalError", "validate_startup"]
