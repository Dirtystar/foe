"""Shared domain models.

These types cross port boundaries (BrowserPort produces a TabHandle,
CapturePort consumes it, VisionAnalyzerPort consumes ImageData, ...), so they
live here rather than inside any single port module. This module must never
import from adapters or from third-party frameworks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

TabId = str


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
