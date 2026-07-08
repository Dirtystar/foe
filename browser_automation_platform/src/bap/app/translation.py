"""Pure translation: config models -> runtime objects.

This is where the two vocabularies meet, and the only place that imports
both. Every function is a pure mapping with no side effects — no browser, no
session, no I/O — so translation can (and does) run eagerly at assembly time,
making a bad mapping (unknown comparison op, unknown analyzer type) fail
before any runtime resource exists.

Runtime classes never appear in config, and config classes never appear in
core; this module bridges them and nothing else does.
"""

from __future__ import annotations

from bap.app.errors import CompositionError
from bap.app.registries import AnalyzerRegistry
from bap.config.config_models import (
    ActionConfig,
    CaptureBindingConfig,
    ConditionConfig,
    ProfileConfig,
    RuleConfig,
)
from bap.core.domain.models import ActionRequest, Rect, Selector, TabProfile, ViewportSize
from bap.core.engine.tab_session import CaptureBinding
from bap.core.ports.capture_port import CaptureTarget
from bap.core.ports.vision_analyzer_port import AnalyzerContext
from bap.core.rules.conditions import (
    AndCondition,
    ComparisonOp,
    ConfidenceThresholdCondition,
    ExistsCondition,
    NotCondition,
    OrCondition,
    StalenessCondition,
    ValueComparisonCondition,
)
from bap.core.rules.models import Condition, Rule
from bap.core.vision.pipeline import AnalyzerBinding, VisionPipeline


def build_condition(cfg: ConditionConfig) -> Condition:
    t = cfg.type
    if t == "exists":
        return ExistsCondition(field=cfg.field)
    if t == "compare":
        try:
            op = ComparisonOp(cfg.op)
        except ValueError:
            raise CompositionError(
                f"unknown comparison op '{cfg.op}' "
                f"(expected one of {[o.value for o in ComparisonOp]})"
            ) from None
        return ValueComparisonCondition(field=cfg.field, op=op, expected=cfg.value)
    if t == "confidence":
        return ConfidenceThresholdCondition(field=cfg.field, minimum=cfg.minimum)
    if t == "staleness":
        return StalenessCondition(field=cfg.field, max_age_ms=cfg.max_age_ms)
    if t == "all":
        return AndCondition(children=tuple(build_condition(c) for c in cfg.conditions))
    if t == "any":
        return OrCondition(children=tuple(build_condition(c) for c in cfg.conditions))
    if t == "not":
        return NotCondition(child=build_condition(cfg.condition))
    # config validation already restricts `type`; this guards drift between
    # the config vocabulary and this translator.
    raise CompositionError(f"no translation for condition type '{t}'")


def build_action(cfg: ActionConfig) -> ActionRequest:
    return ActionRequest(action_type=cfg.type, params=dict(cfg.params))


def build_rule(cfg: RuleConfig) -> Rule:
    return Rule(
        id=cfg.id,
        condition=build_condition(cfg.condition),
        actions=tuple(build_action(a) for a in cfg.actions),
        enabled=cfg.enabled,
        cooldown_ms=cfg.cooldown_ms,
    )


def build_capture_target(cfg: CaptureBindingConfig) -> CaptureTarget:
    if cfg.target == "region":
        r = cfg.region
        return Rect(x=r.x, y=r.y, w=r.w, h=r.h)
    if cfg.target == "selector":
        return Selector(css=cfg.selector)
    return None  # full_page


def build_capture_binding(
    profile_id: str, cfg: CaptureBindingConfig, analyzers: AnalyzerRegistry
) -> CaptureBinding:
    bindings = [
        AnalyzerBinding(
            analyzer=analyzers.create(a.type),
            context=AnalyzerContext(
                profile_id=profile_id, target_name=cfg.name, settings=dict(a.settings)
            ),
        )
        for a in cfg.analyzers
    ]
    return CaptureBinding(target=build_capture_target(cfg), pipeline=VisionPipeline(bindings))


def build_tab_profile(cfg: ProfileConfig) -> TabProfile:
    return TabProfile(
        id=cfg.id,
        start_url=cfg.start_url,
        viewport=ViewportSize(width=cfg.viewport.width, height=cfg.viewport.height),
    )


__all__ = [
    "build_action",
    "build_capture_binding",
    "build_capture_target",
    "build_condition",
    "build_rule",
    "build_tab_profile",
]
