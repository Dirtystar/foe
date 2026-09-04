"""Loads and validates configuration from YAML into ApplicationConfig.

Read-only and side-effect-free: it parses text/files into validated data and
raises ConfigError on any problem, wrapping both YAML syntax errors and
Pydantic validation errors in one exception type so callers (composition
root / CLI) handle a single failure mode with a readable message.

Validation messages are operator-facing: each problem names the source file,
the exact field path (e.g. `profiles.0.session.interval_ms`), what was wrong,
and a suggested fix.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from bap.config.config_models import ApplicationConfig


class ConfigError(Exception):
    """Raised when configuration cannot be parsed or fails validation."""


# Suggested fixes keyed by Pydantic error `type`. Kept deliberately short and
# actionable; the field path and message carry the specifics.
_SUGGESTIONS = {
    "extra_forbidden": "remove this unknown field (check for a typo)",
    "missing": "add this required field",
    "literal_error": "use one of the allowed values shown above",
    "int_parsing": "use a whole number",
    "float_parsing": "use a number",
    "bool_parsing": "use true or false",
    "string_type": "use a text value",
    "greater_than": "use a larger value",
    "greater_than_equal": "use a value that is at least the minimum",
    "less_than": "use a smaller value",
    "less_than_equal": "use a value that is at most the maximum",
}


def _field_path(loc: tuple[object, ...]) -> str:
    return ".".join(str(part) for part in loc) if loc else "(root)"


def _format_validation_error(source: str, exc: ValidationError) -> str:
    lines = [f"{source}: configuration is invalid ({exc.error_count()} problem(s)):"]
    for err in exc.errors():
        path = _field_path(err["loc"])
        msg = err["msg"]
        suggestion = _SUGGESTIONS.get(err["type"])
        lines.append(f"  - at '{path}': {msg}")
        if suggestion:
            lines.append(f"      fix: {suggestion}")
    return "\n".join(lines)


def load_config_from_string(text: str, *, source: str = "<string>") -> ApplicationConfig:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        where = ""
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            where = f" (line {mark.line + 1}, column {mark.column + 1})"
        raise ConfigError(f"{source}: invalid YAML{where}: {exc}") from exc

    if raw is None:
        raw = {}  # an empty document is an empty (all-defaults) configuration
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{source}: top-level configuration must be a mapping, got {type(raw).__name__}"
        )

    try:
        return ApplicationConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(source, exc)) from exc


def load_config(path: str | Path) -> ApplicationConfig:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file '{path}': {exc}") from exc
    return load_config_from_string(text, source=str(path))


__all__ = ["ConfigError", "load_config", "load_config_from_string"]
