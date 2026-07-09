"""Plugin discovery via Python entry points.

Third-party analyzers and action handlers are installed as normal Python
packages that declare entry points in two groups:

    [project.entry-points."bap.analyzers"]
    custom_ocr = "my_pkg:create_analyzer"

    [project.entry-points."bap.actions"]
    my_action = "my_pkg:create_handler"

The entry point NAME is the config type string; the loaded object is a
zero-argument factory returning a VisionAnalyzerPort / ActionHandlerPort —
the same factory contract the built-in registries use, so per-invocation
settings still flow through AnalyzerContext / ActionRequest.params and no
plugin-specific config schema exists in core.

Loading is explicit (a caller passes the discovered factories into a
registry) and testable (the entry-point iterable is injectable). Discovery
has no global mutable state: each call returns a fresh dict. Contract
violations raise PluginError (a CompositionError), so a bad plugin fails
cleanly during composition, never at runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from bap.app.errors import CompositionError
from bap.app.registries import (
    ActionHandlerFactory,
    ActionHandlerRegistry,
    AnalyzerFactory,
    AnalyzerRegistry,
)

ANALYZER_GROUP = "bap.analyzers"
ACTION_GROUP = "bap.actions"


class PluginError(CompositionError):
    """A plugin could not be loaded or violated the factory contract."""


@runtime_checkable
class _EntryPointLike(Protocol):
    name: str

    def load(self) -> object: ...


def _load_group(group: str, entry_points: Iterable[_EntryPointLike] | None) -> dict[str, object]:
    if entry_points is None:
        from importlib.metadata import entry_points as _entry_points

        entry_points = _entry_points(group=group)

    factories: dict[str, object] = {}
    for ep in entry_points:
        try:
            factory = ep.load()
        except Exception as exc:  # import error, missing attribute, etc.
            raise PluginError(
                f"plugin '{ep.name}' (group '{group}') failed to load: {exc}"
            ) from exc
        if not callable(factory):
            raise PluginError(
                f"plugin '{ep.name}' (group '{group}') entry point is not callable"
            )
        factories[ep.name] = factory
    return factories


def load_analyzer_plugins(
    entry_points: Iterable[_EntryPointLike] | None = None,
) -> dict[str, AnalyzerFactory]:
    return _load_group(ANALYZER_GROUP, entry_points)  # type: ignore[return-value]


def load_action_plugins(
    entry_points: Iterable[_EntryPointLike] | None = None,
) -> dict[str, ActionHandlerFactory]:
    return _load_group(ACTION_GROUP, entry_points)  # type: ignore[return-value]


def register_plugins(registry, factories: dict[str, object], *, allow_override: bool = False) -> None:
    """Merge discovered factories into a registry. By default a plugin whose
    name collides with an already-registered (built-in) type is a conflict
    error — a plugin cannot silently hijack a built-in type; pass
    allow_override=True to intentionally replace one."""
    for name, factory in factories.items():
        if registry.knows(name) and not allow_override:
            raise PluginError(
                f"plugin '{name}' conflicts with an existing type; "
                f"pass allow_override=True to replace it"
            )
        registry.register(name, factory)


def apply_analyzer_plugins(
    registry: AnalyzerRegistry,
    *,
    entry_points: Iterable[_EntryPointLike] | None = None,
    allow_override: bool = False,
) -> AnalyzerRegistry:
    register_plugins(registry, load_analyzer_plugins(entry_points), allow_override=allow_override)
    return registry


def apply_action_plugins(
    registry: ActionHandlerRegistry,
    *,
    entry_points: Iterable[_EntryPointLike] | None = None,
    allow_override: bool = False,
) -> ActionHandlerRegistry:
    register_plugins(registry, load_action_plugins(entry_points), allow_override=allow_override)
    return registry


__all__ = [
    "ACTION_GROUP",
    "ANALYZER_GROUP",
    "PluginError",
    "apply_action_plugins",
    "apply_analyzer_plugins",
    "load_action_plugins",
    "load_analyzer_plugins",
    "register_plugins",
]
