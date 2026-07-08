"""Loads and validates configuration from YAML into ApplicationConfig.

Read-only and side-effect-free: it parses text/files into validated data and
raises ConfigError on any problem, wrapping both YAML syntax errors and
Pydantic validation errors in one exception type so callers (the future
composition root / CLI) handle a single failure mode with a readable message.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from bap.config.config_models import ApplicationConfig


class ConfigError(Exception):
    """Raised when configuration cannot be parsed or fails validation."""


def load_config_from_string(text: str, *, source: str = "<string>") -> ApplicationConfig:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: invalid YAML: {exc}") from exc

    if raw is None:
        raw = {}  # an empty document is an empty (all-defaults) configuration
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{source}: top-level configuration must be a mapping, got {type(raw).__name__}"
        )

    try:
        return ApplicationConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{source}: configuration is invalid:\n{exc}") from exc


def load_config(path: str | Path) -> ApplicationConfig:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file '{path}': {exc}") from exc
    return load_config_from_string(text, source=str(path))


__all__ = ["ConfigError", "load_config", "load_config_from_string"]
