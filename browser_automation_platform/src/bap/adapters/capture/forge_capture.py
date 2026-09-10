"""Read-only canvas capture for Forge.

Forge worlds are tabs in one persistent, user-driven Chromium window, and the
assistant must be able to look at them **without touching them**. Playwright's
`page.screenshot(full_page=True)` is not read-only enough for a live WebGL game:

  - `full_page` grows the emulated viewport to the full content size and back on
    every capture, which makes the game canvas relayout — a visible flicker.
  - Rendering a background tab for a screenshot can foreground it, so capturing
    world H while world F is visible switches the visible tab (more flicker), and
    the act of foregrounding a game tab under the mouse can deliver an incidental
    pointer event to the canvas — which is how a province opened with zero
    actions executed.

This adapter bypasses that wrapper and drives Chromium's DevTools protocol
directly: `Page.captureScreenshot` grabs the tab's compositor surface
(`fromSurface`) without foregrounding it, without resizing the viewport, and
without any input. Viewport-only (`captureBeyondViewport: false`) — the Forge
canvas fills the viewport, and there is deliberately no full-page path. The only
browser call this makes is the screenshot itself; it never clicks, types,
scrolls, focuses, evaluates, or brings a tab to front.

Chromium-only by construction (CDP), which Forge already is.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

from bap.core.domain.models import ImageData, Rect, Selector, TabHandle
from bap.core.ports.capture_port import CaptureError, CapturePort, CaptureTarget, InvalidRegionError

logger = logging.getLogger(__name__)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        raise CaptureError("Screenshot bytes are not a valid PNG image.")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class ForgeCanvasCaptureAdapter(CapturePort):
    """CapturePort that screenshots a tab via CDP without any side effects.

    A CDP session is created lazily per page and cached; if it goes stale (the
    page navigated or closed), it is dropped and recreated once. Stateless
    otherwise, so one adapter serves every world tab.
    """

    def __init__(self) -> None:
        # page -> CDP session. Playwright Page objects are hashable/stable for a
        # tab's lifetime; a closed page's session is pruned on first failure.
        self._sessions: dict[object, object] = {}

    async def _session(self, page):
        session = self._sessions.get(page)
        if session is None:
            session = await page.context.new_cdp_session(page)
            self._sessions[page] = session
        return session

    async def _capture_bytes(self, page, params: dict) -> bytes:
        try:
            session = await self._session(page)
            result = await session.send("Page.captureScreenshot", params)
        except Exception:
            # Stale session (navigation/close) or transient CDP error: drop the
            # cached session and try once more with a fresh one.
            self._sessions.pop(page, None)
            session = await self._session(page)
            result = await session.send("Page.captureScreenshot", params)
        return base64.b64decode(result["data"])

    async def capture(self, tab: TabHandle, target: CaptureTarget = None) -> ImageData:
        page = tab.native
        params: dict = {"format": "png", "fromSurface": True, "captureBeyondViewport": False}
        region: Rect | None = None

        if isinstance(target, Selector):
            # Forge is a canvas game — there are no DOM elements to screenshot,
            # and honouring a selector here would resurrect the placeholder-
            # selector bug. Refuse it explicitly.
            raise CaptureError("Forge capture is canvas-only; selector targets are not supported.")
        if isinstance(target, Rect):
            if target.w <= 0 or target.h <= 0:
                raise InvalidRegionError(
                    f"Region must have positive size, got w={target.w}, h={target.h}."
                )
            params["clip"] = {
                "x": target.x, "y": target.y, "width": target.w, "height": target.h, "scale": 1,
            }
            region = target

        data = await self._capture_bytes(page, params)
        width, height = _png_dimensions(data)
        logger.debug("Forge captured tab '%s' (%dx%d) read-only via CDP", tab.tab_id, width, height)
        return ImageData(
            data=data,
            width=width,
            height=height,
            tab_id=tab.tab_id,
            captured_at=datetime.now(timezone.utc),
            region=region,
            selector=None,
        )


__all__ = ["ForgeCanvasCaptureAdapter"]
