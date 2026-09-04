"""Example plugin: a custom analyzer and a custom action handler.

Depends only on the public bap port contracts — never on bap internals.
"""

from __future__ import annotations

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ActionRequest, ImageData, Observation
from bap.core.ports.action_handler_port import (
    ActionContext,
    ActionHandlerPort,
    ActionResult,
    ActionStatus,
)
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerPort


class FakeAnalyzer(VisionAnalyzerPort):
    """Emits one observation whose value comes from the binding's settings, so
    a rule can react to it — proving plugin analyzers get their settings via
    AnalyzerContext, exactly like built-ins."""

    @property
    def name(self) -> str:
        return "fake_ocr"

    async def analyze(self, image: ImageData, context: AnalyzerContext) -> list[Observation]:
        value = context.settings.get("value", "plugin")
        prefix = context.target_name or self.name
        return [
            Observation(
                name=f"{prefix}.plugin_value",
                kind=ObservationKind.CUSTOM,
                analyzer=self.name,
                value=value,
            )
        ]


class FakeHandler(ActionHandlerPort):
    @property
    def action_type(self) -> str:
        return "fake_click"

    async def execute(self, request: ActionRequest, context: ActionContext) -> ActionResult:
        return ActionResult(request=request, status=ActionStatus.SUCCEEDED, message="plugin ok")


def create_analyzer() -> VisionAnalyzerPort:
    return FakeAnalyzer()


def create_handler() -> ActionHandlerPort:
    return FakeHandler()
