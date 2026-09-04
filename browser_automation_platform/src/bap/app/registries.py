"""Type-string -> runtime-implementation registries.

Configuration names analyzers and actions by string ("ocr", "click"). The
composition root resolves those strings to port implementations through
these registries. They are the seam a future plugin system extends: a
plugin registers its analyzer/handler factory here and config can reference
it by name, with no core change. Registries hold factories (not instances)
so each session can get its own handler set.
"""

from __future__ import annotations

from collections.abc import Callable

from bap.app.errors import CompositionError
from bap.core.ports.action_handler_port import ActionHandlerPort
from bap.core.ports.vision_analyzer_port import VisionAnalyzerPort

AnalyzerFactory = Callable[[], VisionAnalyzerPort]
ActionHandlerFactory = Callable[[], ActionHandlerPort]


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AnalyzerFactory] = {}

    def register(self, type_name: str, factory: AnalyzerFactory) -> None:
        self._factories[type_name] = factory

    def knows(self, type_name: str) -> bool:
        return type_name in self._factories

    def create(self, type_name: str) -> VisionAnalyzerPort:
        try:
            factory = self._factories[type_name]
        except KeyError:
            raise CompositionError(f"no analyzer registered for type '{type_name}'") from None
        return factory()

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(self._factories)


class ActionHandlerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ActionHandlerFactory] = {}

    def register(self, action_type: str, factory: ActionHandlerFactory) -> None:
        self._factories[action_type] = factory

    def knows(self, action_type: str) -> bool:
        return action_type in self._factories

    def create_all(self) -> list[ActionHandlerPort]:
        """One fresh handler per registered action type — the exact set an
        ActionExecutor needs (unique per type, which it requires)."""
        return [factory() for factory in self._factories.values()]

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(self._factories)


__all__ = [
    "ActionHandlerFactory",
    "ActionHandlerRegistry",
    "AnalyzerFactory",
    "AnalyzerRegistry",
]
