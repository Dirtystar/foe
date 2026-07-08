"""Playwright-backed ActionHandlerPort implementations.

Each handler unwraps the Page from the opaque TabHandle and performs one
input operation. Handlers translate, they do not decide: which action fires
is the rule engine's job; these only carry it out and report the outcome.

Failure discipline: every Playwright (or parameter) error is converted into
a FAILED ActionResult carrying an ActionHandlerError — a core type — so no
Playwright exception type ever crosses back into the core. Missing/invalid
parameters fail the same way, with a message naming the offending key.
"""

from __future__ import annotations

import asyncio
import logging

from bap.app.registries import ActionHandlerRegistry
from bap.core.domain.models import ActionRequest
from bap.core.ports.action_handler_port import (
    ActionContext,
    ActionHandlerError,
    ActionHandlerPort,
    ActionResult,
    ActionStatus,
)

logger = logging.getLogger(__name__)


def _require(request: ActionRequest, key: str) -> object:
    value = request.params.get(key)
    if value is None or value == "":
        raise ActionHandlerError(f"action '{request.action_type}' requires param '{key}'")
    return value


class _PlaywrightActionHandler(ActionHandlerPort):
    """Common shell: resolve the Page, run the operation, contain failures.

    Subclasses implement `_run(page, request, context)` and may raise
    ActionHandlerError for bad params; anything raised here becomes a FAILED
    result rather than propagating.
    """

    _ACTION_TYPE: str = ""

    @property
    def action_type(self) -> str:
        return self._ACTION_TYPE

    async def execute(self, request: ActionRequest, context: ActionContext) -> ActionResult:
        page = context.tab.native
        if page is None:
            err = ActionHandlerError(f"action '{self._ACTION_TYPE}': tab has no live page")
            return ActionResult(request=request, status=ActionStatus.FAILED,
                                message=str(err), error=err)
        try:
            return await self._run(page, request, context)
        except ActionHandlerError as err:
            return ActionResult(request=request, status=ActionStatus.FAILED,
                                message=str(err), error=err)
        except Exception as exc:  # Playwright error, timeout, etc. — never leak it
            err = ActionHandlerError(f"action '{self._ACTION_TYPE}' failed: {exc}")
            return ActionResult(request=request, status=ActionStatus.FAILED,
                                message=str(err), error=err)

    async def _run(self, page, request: ActionRequest, context: ActionContext) -> ActionResult:
        raise NotImplementedError

    @staticmethod
    def _ok(request: ActionRequest, message: str) -> ActionResult:
        return ActionResult(request=request, status=ActionStatus.SUCCEEDED, message=message)


class ClickHandler(_PlaywrightActionHandler):
    _ACTION_TYPE = "click"

    async def _run(self, page, request, context) -> ActionResult:
        selector = str(_require(request, "selector"))
        timeout = request.params.get("timeout_ms")
        if timeout:
            await page.click(selector, timeout=timeout)
        else:
            await page.click(selector)
        return self._ok(request, f"clicked '{selector}'")


class TypeHandler(_PlaywrightActionHandler):
    _ACTION_TYPE = "type"

    async def _run(self, page, request, context) -> ActionResult:
        selector = str(_require(request, "selector"))
        text = str(_require(request, "text"))
        await page.fill(selector, text)
        return self._ok(request, f"typed into '{selector}'")


class NavigateHandler(_PlaywrightActionHandler):
    _ACTION_TYPE = "navigate"

    async def _run(self, page, request, context) -> ActionResult:
        url = str(_require(request, "url"))
        await page.goto(url)
        return self._ok(request, f"navigated to '{url}'")


class WaitHandler(_PlaywrightActionHandler):
    _ACTION_TYPE = "wait"

    async def _run(self, page, request, context) -> ActionResult:
        selector = request.params.get("selector")
        if selector:
            timeout = request.params.get("timeout_ms", 5000)
            await page.wait_for_selector(str(selector), timeout=timeout)
            return self._ok(request, f"waited for '{selector}'")
        ms = request.params.get("ms", 0)
        await asyncio.sleep(float(ms) / 1000.0)
        return self._ok(request, f"waited {ms}ms")


def playwright_action_registry() -> ActionHandlerRegistry:
    """Registry wiring the config action-type strings to real handlers."""
    registry = ActionHandlerRegistry()
    for handler_cls in (ClickHandler, TypeHandler, NavigateHandler, WaitHandler):
        registry.register(handler_cls._ACTION_TYPE, handler_cls)
    return registry


__all__ = [
    "ClickHandler",
    "NavigateHandler",
    "TypeHandler",
    "WaitHandler",
    "playwright_action_registry",
]
