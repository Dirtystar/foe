"""Shared domain models.

These types cross port boundaries (BrowserPort produces a TabHandle,
CapturePort consumes it, VisionAnalyzerPort consumes ImageData, ...), so they
live here rather than inside any single port module. This module must never
import from adapters or from third-party frameworks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from bap.core.domain.enums import ObservationKind

TabId = str

AttributeValue = str | int | float | bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ViewportSize:
    width: int = 1920
    height: int = 1080


@dataclass(frozen=True)
class TabProfile:
    id: TabId
    start_url: str | None = None
    viewport: ViewportSize = field(default_factory=ViewportSize)


@dataclass(frozen=True)
class TabHandle:
    """Opaque reference to an open tab.

    `native` carries the underlying engine object (a Playwright Page today).
    Only adapters may unwrap it; core code treats the handle as opaque.
    """

    tab_id: TabId
    native: Any


@dataclass(frozen=True)
class Rect:
    """Pixel-space rectangle in page coordinates."""

    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Selector:
    """A CSS selector identifying one element on the page."""

    css: str


@dataclass(frozen=True)
class ImageData:
    """A captured image, decoupled from how it was produced.

    `data` holds the encoded image bytes (PNG unless `format` says otherwise).
    `region` / `selector` record what part of the page was captured so vision
    analyzers can map their observations back to page coordinates; both are
    None for a full-page capture.
    """

    data: bytes
    width: int
    height: int
    tab_id: TabId
    captured_at: datetime
    format: str = "png"
    region: Rect | None = None
    selector: str | None = None


@dataclass(frozen=True)
class Observation:
    """One fact a vision analyzer extracted from a captured image.

    `name` is the logical field the aggregator keys PageState by (e.g.
    "header_region.text"). `value` carries the payload: recognized text for
    TEXT, template/object identifier for TEMPLATE_MATCH/OBJECT. `region` is
    in the coordinate space of the analyzed image; combine with
    ImageData.region to map back to page coordinates. Analyzer-specific
    extras go in `attributes` (exposed read-only).
    """

    name: str
    kind: ObservationKind
    analyzer: str
    value: AttributeValue | None = None
    confidence: float = 1.0
    region: Rect | None = None
    attributes: Mapping[str, AttributeValue] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Observation.name must be a non-empty string.")
        if not self.analyzer:
            raise ValueError("Observation.analyzer must identify the source analyzer.")
        if not isinstance(self.kind, ObservationKind):
            raise ValueError(f"Observation.kind must be an ObservationKind, got {self.kind!r}.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Observation.confidence must be in [0.0, 1.0], got {self.confidence}.")
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True)
class PageState:
    """Aggregated visual snapshot of one tab — the RuleEngine's sole input.

    One Observation per logical field name, chosen by the Aggregator when
    analyzers disagree. Immutable: a rule evaluation always sees a single
    consistent snapshot, never a half-updated one.
    """

    profile_id: str
    fields: Mapping[str, Observation] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("PageState.profile_id must be non-empty.")
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def has(self, name: str) -> bool:
        return name in self.fields

    def get(self, name: str) -> Observation | None:
        return self.fields.get(name)

    def value_of(self, name: str) -> AttributeValue | None:
        obs = self.fields.get(name)
        return None if obs is None else obs.value
