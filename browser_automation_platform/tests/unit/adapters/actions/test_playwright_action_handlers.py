from unittest.mock import AsyncMock

import pytest

from bap.adapters.actions.playwright_action_handlers import (
    ClickHandler,
    NavigateHandler,
    TypeHandler,
    WaitHandler,
    playwright_action_registry,
)
from bap.core.domain.models import ActionRequest, TabHandle
from bap.core.ports.action_handler_port import (
    ActionContext,
    ActionHandlerError,
    ActionStatus,
)


def context_with(page) -> ActionContext:
    return ActionContext(tab=TabHandle(tab_id="tab1", native=page), profile_id="p1")


def req(action_type: str, **params) -> ActionRequest:
    return ActionRequest(action_type=action_type, params=params, rule_id="r1")


# --- registry -----------------------------------------------------------------


def test_registry_exposes_the_four_handlers():
    registry = playwright_action_registry()

    assert set(registry.types) == {"click", "type", "navigate", "wait"}
    handlers = {h.action_type: h for h in registry.create_all()}
    assert isinstance(handlers["click"], ClickHandler)
    assert isinstance(handlers["navigate"], NavigateHandler)


# --- happy paths --------------------------------------------------------------


async def test_click_calls_page_click_and_succeeds():
    page = AsyncMock()
    result = await ClickHandler().execute(req("click", selector="#go"), context_with(page))

    page.click.assert_awaited_once_with("#go")
    assert result.status is ActionStatus.SUCCEEDED
    assert "#go" in result.message
    assert result.request.rule_id == "r1"  # provenance preserved


async def test_click_forwards_timeout_when_given():
    page = AsyncMock()
    await ClickHandler().execute(req("click", selector="#go", timeout_ms=1000), context_with(page))

    page.click.assert_awaited_once_with("#go", timeout=1000)


async def test_type_fills_selector_with_text():
    page = AsyncMock()
    result = await TypeHandler().execute(
        req("type", selector="#name", text="hello"), context_with(page)
    )

    page.fill.assert_awaited_once_with("#name", "hello")
    assert result.status is ActionStatus.SUCCEEDED


async def test_navigate_calls_goto():
    page = AsyncMock()
    result = await NavigateHandler().execute(
        req("navigate", url="https://example.com"), context_with(page)
    )

    page.goto.assert_awaited_once_with("https://example.com")
    assert result.status is ActionStatus.SUCCEEDED


async def test_wait_for_selector_when_selector_given():
    page = AsyncMock()
    result = await WaitHandler().execute(
        req("wait", selector="#ready", timeout_ms=1234), context_with(page)
    )

    page.wait_for_selector.assert_awaited_once_with("#ready", timeout=1234)
    assert result.status is ActionStatus.SUCCEEDED


async def test_wait_sleeps_when_only_ms_given():
    page = AsyncMock()
    result = await WaitHandler().execute(req("wait", ms=0), context_with(page))

    assert result.status is ActionStatus.SUCCEEDED
    page.wait_for_selector.assert_not_awaited()


# --- failure containment ------------------------------------------------------


async def test_missing_required_param_is_a_failed_result_not_a_raise():
    page = AsyncMock()
    result = await ClickHandler().execute(req("click"), context_with(page))  # no selector

    assert result.status is ActionStatus.FAILED
    assert isinstance(result.error, ActionHandlerError)
    assert "selector" in result.message
    page.click.assert_not_awaited()


async def test_playwright_exception_is_converted_not_leaked():
    page = AsyncMock()

    class PlaywrightTimeoutError(Exception):
        """Stand-in for a real playwright error type."""

    page.click.side_effect = PlaywrightTimeoutError("Timeout 30000ms exceeded")
    result = await ClickHandler().execute(req("click", selector="#x"), context_with(page))

    assert result.status is ActionStatus.FAILED
    # The error surfaced to core is our type, never the Playwright exception.
    assert isinstance(result.error, ActionHandlerError)
    assert not isinstance(result.error, PlaywrightTimeoutError)
    assert "Timeout 30000ms" in result.message


async def test_missing_live_page_is_a_failed_result():
    result = await ClickHandler().execute(
        req("click", selector="#x"), ActionContext(tab=TabHandle("t", native=None), profile_id="p1")
    )

    assert result.status is ActionStatus.FAILED
    assert "no live page" in result.message
