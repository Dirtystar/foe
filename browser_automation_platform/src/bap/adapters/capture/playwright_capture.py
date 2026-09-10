from __future__ import annotations

import logging
from datetime import datetime, timezone

from bap.core.domain.models import ImageData, Rect, Selector, TabHandle
from bap.core.ports.capture_port import (
    CaptureError,
    CapturePort,
    CaptureTarget,
    ElementNotFoundError,
    InvalidRegionError,
)

logger = logging.getLogger(__name__)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width/height from a PNG's IHDR chunk without any imaging library.

    The IHDR chunk is required to be first, so width and height always sit at
    fixed byte offsets 16..24 (8 signature + 4 length + 4 chunk type).
    """
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        raise CaptureError("Screenshot bytes are not a valid PNG image.")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


class PlaywrightCaptureAdapter(CapturePort):
    """CapturePort implementation backed by Playwright's screenshot APIs.

    Stateless: all state lives in the Page carried by the TabHandle, so one
    adapter instance can serve every tab concurrently.
    """

    async def capture(self, tab: TabHandle, target: CaptureTarget = None) -> ImageData:
        page = tab.native

        region: Rect | None = None
        selector: str | None = None

        if target is None:
            data = await page.screenshot(full_page=True)
        elif isinstance(target, Rect):
            if target.w <= 0 or target.h <= 0:
                raise InvalidRegionError(
                    f"Region must have positive size, got w={target.w}, h={target.h}."
                )
            data = await page.screenshot(
                clip={"x": target.x, "y": target.y, "width": target.w, "height": target.h}
            )
            region = target
        elif isinstance(target, Selector):
            element = await page.query_selector(target.css)
            if element is None:
                raise ElementNotFoundError(f"No element matches selector '{target.css}'.")
            data = await element.screenshot()
            selector = target.css
        else:
            raise TypeError(f"Unsupported capture target: {type(target).__name__}")

        width, height = _png_dimensions(data)
        logger.debug(
            "Captured tab '%s' (%dx%d, target=%s)", tab.tab_id, width, height, target
        )
        return ImageData(
            data=data,
            width=width,
            height=height,
            tab_id=tab.tab_id,
            captured_at=datetime.now(timezone.utc),
            region=region,
            selector=selector,
        )


__all__ = ["PlaywrightCaptureAdapter"]
