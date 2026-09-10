from __future__ import annotations

from abc import ABC, abstractmethod

from bap.core.domain.models import ImageData, Rect, Selector, TabHandle

CaptureTarget = Rect | Selector | None
"""What to capture: a pixel region, one element, or None for the full page."""


class CaptureError(Exception):
    """Base class for all CapturePort errors."""


class ElementNotFoundError(CaptureError):
    pass


class InvalidRegionError(CaptureError):
    pass


class CapturePort(ABC):
    """Screenshot contract for a browser engine adapter.

    Implementations produce a pure ImageData from a TabHandle. They must not
    analyze, decode beyond reading dimensions, or transform the image — that
    is the vision layer's job. Encoding is PNG unless stated otherwise in the
    returned ImageData.
    """

    @abstractmethod
    async def capture(self, tab: TabHandle, target: CaptureTarget = None) -> ImageData: ...
