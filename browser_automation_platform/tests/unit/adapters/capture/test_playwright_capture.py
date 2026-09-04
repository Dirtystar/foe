from unittest.mock import AsyncMock

import pytest

from bap.adapters.capture.playwright_capture import PlaywrightCaptureAdapter
from bap.core.domain.models import Rect, Selector, TabHandle
from bap.core.ports.capture_port import (
    CaptureError,
    ElementNotFoundError,
    InvalidRegionError,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def fake_png(width: int, height: int) -> bytes:
    """Minimal byte string that parses as a PNG header with the given size."""
    return (
        PNG_SIGNATURE
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


@pytest.fixture
def page():
    page = AsyncMock(name="page")
    page.screenshot = AsyncMock(return_value=fake_png(1920, 1080))
    return page


@pytest.fixture
def tab(page):
    return TabHandle(tab_id="tab1", native=page)


@pytest.fixture
def adapter():
    return PlaywrightCaptureAdapter()


async def test_full_page_capture(adapter, tab, page):
    image = await adapter.capture(tab)

    page.screenshot.assert_awaited_once_with(full_page=True)
    assert image.width == 1920
    assert image.height == 1080
    assert image.tab_id == "tab1"
    assert image.format == "png"
    assert image.region is None
    assert image.selector is None
    assert image.captured_at.tzinfo is not None


async def test_region_capture_passes_clip(adapter, tab, page):
    page.screenshot.return_value = fake_png(300, 120)
    region = Rect(x=10, y=20, w=300, h=120)

    image = await adapter.capture(tab, region)

    page.screenshot.assert_awaited_once_with(
        clip={"x": 10, "y": 20, "width": 300, "height": 120}
    )
    assert (image.width, image.height) == (300, 120)
    assert image.region == region
    assert image.selector is None


@pytest.mark.parametrize("bad", [Rect(0, 0, 0, 100), Rect(0, 0, 100, -5)])
async def test_region_with_non_positive_size_is_rejected(adapter, tab, page, bad):
    with pytest.raises(InvalidRegionError):
        await adapter.capture(tab, bad)

    page.screenshot.assert_not_awaited()


async def test_element_capture_uses_element_screenshot(adapter, tab, page):
    element = AsyncMock(name="element")
    element.screenshot = AsyncMock(return_value=fake_png(200, 50))
    page.query_selector = AsyncMock(return_value=element)

    image = await adapter.capture(tab, Selector(css="#main-panel"))

    page.query_selector.assert_awaited_once_with("#main-panel")
    element.screenshot.assert_awaited_once_with()
    page.screenshot.assert_not_awaited()
    assert (image.width, image.height) == (200, 50)
    assert image.selector == "#main-panel"
    assert image.region is None


async def test_element_capture_missing_element_raises(adapter, tab, page):
    page.query_selector = AsyncMock(return_value=None)

    with pytest.raises(ElementNotFoundError):
        await adapter.capture(tab, Selector(css="#nope"))


async def test_unsupported_target_type_raises(adapter, tab):
    with pytest.raises(TypeError):
        await adapter.capture(tab, "not-a-target")  # type: ignore[arg-type]


async def test_non_png_bytes_raise_capture_error(adapter, tab, page):
    page.screenshot.return_value = b"JFIF definitely not a png"

    with pytest.raises(CaptureError):
        await adapter.capture(tab)


async def test_truncated_png_raises_capture_error(adapter, tab, page):
    page.screenshot.return_value = PNG_SIGNATURE + b"\x00\x00"

    with pytest.raises(CaptureError):
        await adapter.capture(tab)
