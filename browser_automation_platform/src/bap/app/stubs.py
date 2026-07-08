"""Development stubs behind the runtime ports.

These let the whole application be assembled and run without Playwright, OCR,
or any external service — useful for smoke-testing the wiring and for tests.
Each stub honours a real port contract, so swapping in the concrete adapters
later is a registry/constructor change, not a redesign. No Playwright/Selenium
logic lives here (or anywhere in core); these are inert placeholders.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bap.app.registries import ActionHandlerRegistry, AnalyzerRegistry
from bap.core.domain.models import (
    ActionRequest,
    ImageData,
    Observation,
    Rect,
    Selector,
    TabHandle,
    TabProfile,
)
from bap.core.ports.action_handler_port import (
    ActionContext,
    ActionHandlerPort,
    ActionResult,
    ActionStatus,
)
from bap.core.ports.capture_port import CapturePort, CaptureTarget
from bap.core.ports.browser_port import BrowserPort
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerPort

logger = logging.getLogger(__name__)

# A minimal but structurally valid PNG header (signature + IHDR for 1x1).
_STUB_PNG = (
    b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" +
    (1).to_bytes(4, "big") + (1).to_bytes(4, "big")
)


class StubBrowser(BrowserPort):
    """In-memory BrowserPort: tracks tabs, opens no real windows."""

    def __init__(self) -> None:
        self.started = False
        self._tabs: dict[str, TabHandle] = {}

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False
        self._tabs.clear()

    async def open_tab(self, profile: TabProfile) -> TabHandle:
        handle = TabHandle(tab_id=profile.id, native=None)
        self._tabs[profile.id] = handle
        return handle

    async def navigate(self, tab: TabHandle, url: str) -> None:
        pass

    async def close_tab(self, tab: TabHandle) -> None:
        self._tabs.pop(tab.tab_id, None)

    def list_tabs(self) -> list[str]:
        return list(self._tabs)


class StubCapturePort(CapturePort):
    """Returns a placeholder ImageData with size derived from the target."""

    async def capture(self, tab: TabHandle, target: CaptureTarget = None) -> ImageData:
        region = target if isinstance(target, Rect) else None
        selector = target.css if isinstance(target, Selector) else None
        width = region.w if region else 1920
        height = region.h if region else 1080
        return ImageData(
            data=_STUB_PNG,
            width=width,
            height=height,
            tab_id=tab.tab_id,
            captured_at=datetime.now(timezone.utc),
            region=region,
            selector=selector,
        )


class StubAnalyzer(VisionAnalyzerPort):
    """Reports nothing by default. If its settings carry an `emit` mapping of
    {suffix: value}, it emits those as observations named
    `<target>.<suffix>` — handy for exercising rules without real vision."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def analyze(self, image: ImageData, context: AnalyzerContext) -> list[Observation]:
        emit = context.settings.get("emit")
        if not isinstance(emit, dict):
            return []
        from bap.core.domain.enums import ObservationKind

        prefix = context.target_name or self._name
        return [
            Observation(
                name=f"{prefix}.{suffix}",
                kind=ObservationKind.CUSTOM,
                analyzer=self._name,
                value=value,
            )
            for suffix, value in emit.items()
        ]


class StubActionHandler(ActionHandlerPort):
    """Logs and succeeds. Stands in for click/type/navigate/... handlers."""

    def __init__(self, action_type: str) -> None:
        self._action_type = action_type

    @property
    def action_type(self) -> str:
        return self._action_type

    async def execute(self, request: ActionRequest, context: ActionContext) -> ActionResult:
        logger.info(
            "[stub] action '%s' on tab '%s' params=%s",
            request.action_type,
            context.tab.tab_id,
            dict(request.params),
        )
        return ActionResult(request=request, status=ActionStatus.SUCCEEDED, message="stub ok")


_DEFAULT_ANALYZER_TYPES = ("ocr", "template_match", "object_detect", "ai_vision")
_DEFAULT_ACTION_TYPES = (
    "click", "type", "press", "scroll", "navigate", "wait", "log", "stop_session", "noop",
)


def default_analyzer_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    for type_name in _DEFAULT_ANALYZER_TYPES:
        registry.register(type_name, lambda tn=type_name: StubAnalyzer(tn))
    return registry


def default_action_registry() -> ActionHandlerRegistry:
    registry = ActionHandlerRegistry()
    for action_type in _DEFAULT_ACTION_TYPES:
        registry.register(action_type, lambda at=action_type: StubActionHandler(at))
    return registry


__all__ = [
    "StubActionHandler",
    "StubAnalyzer",
    "StubBrowser",
    "StubCapturePort",
    "default_action_registry",
    "default_analyzer_registry",
]
