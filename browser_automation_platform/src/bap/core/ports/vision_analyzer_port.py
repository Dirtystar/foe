from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from bap.core.domain.models import ImageData, Observation


@dataclass(frozen=True)
class AnalyzerContext:
    """Everything an analyzer may know beyond the image itself.

    `target_name` is the logical name of the capture target that produced the
    image (analyzers prefix their Observation names with it). `settings` is
    the analyzer's configuration block from the profile (thresholds, language,
    template paths, plugin options) — the port stays generic by treating it
    as an opaque read-only mapping.
    """

    profile_id: str
    target_name: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("AnalyzerContext.profile_id must be non-empty.")
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))


class VisionAnalyzerError(Exception):
    """Base class for analyzer failures."""


class VisionAnalyzerPort(ABC):
    """Contract every vision analyzer (built-in or plugin) implements.

    Analyzers are pure functions over (image, context): no browser access, no
    side effects, no state between calls. CPU-heavy implementations must not
    block the event loop — they offload internally (run_in_executor); the
    async signature also fits I/O-bound analyzers such as a future AI vision
    backend. Returning an empty list means "nothing found" and is not an
    error; raise VisionAnalyzerError only when analysis itself failed.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier recorded on every Observation this analyzer emits."""

    @abstractmethod
    async def analyze(self, image: ImageData, context: AnalyzerContext) -> list[Observation]: ...


__all__ = [
    "AnalyzerContext",
    "VisionAnalyzerError",
    "VisionAnalyzerPort",
]
