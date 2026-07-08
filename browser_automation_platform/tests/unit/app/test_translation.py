import pytest

from bap.app.errors import CompositionError
from bap.app.stubs import default_analyzer_registry
from bap.app.translation import (
    build_action,
    build_capture_binding,
    build_capture_target,
    build_condition,
    build_rule,
    build_tab_profile,
)
from bap.config.config_models import (
    ActionConfig,
    AnalyzerConfig,
    CaptureBindingConfig,
    ConditionConfig,
    ProfileConfig,
    RegionConfig,
    RuleConfig,
)
from bap.core.domain.models import ActionRequest, Rect, Selector
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


# --- conditions ---------------------------------------------------------------


def test_exists_condition_maps():
    c = build_condition(ConditionConfig(type="exists", field="f1"))
    assert isinstance(c, ExistsCondition) and c.field == "f1"


def test_compare_condition_maps_op_to_enum():
    c = build_condition(
        ConditionConfig(type="compare", field="f1", op="less_than", value=100)
    )
    assert isinstance(c, ValueComparisonCondition)
    assert c.op is ComparisonOp.LESS_THAN
    assert c.expected == 100


def test_unknown_compare_op_raises_composition_error():
    with pytest.raises(CompositionError, match="unknown comparison op"):
        build_condition(ConditionConfig(type="compare", field="f", op="approximately", value=1))


def test_confidence_and_staleness_map():
    conf = build_condition(ConditionConfig(type="confidence", field="f", minimum=0.8))
    stale = build_condition(ConditionConfig(type="staleness", field="f", max_age_ms=1000))
    assert isinstance(conf, ConfidenceThresholdCondition) and conf.minimum == 0.8
    assert isinstance(stale, StalenessCondition) and stale.max_age_ms == 1000


def test_composite_conditions_map_recursively():
    cfg = ConditionConfig(
        type="all",
        conditions=[
            ConditionConfig(type="exists", field="a"),
            ConditionConfig(
                type="any",
                conditions=[
                    ConditionConfig(type="compare", field="b", op="equals", value=1),
                    ConditionConfig(type="not", condition=ConditionConfig(type="exists", field="c")),
                ],
            ),
        ],
    )
    c = build_condition(cfg)

    assert isinstance(c, AndCondition)
    inner_any = c.children[1]
    assert isinstance(inner_any, OrCondition)
    assert isinstance(inner_any.children[0], ValueComparisonCondition)
    assert isinstance(inner_any.children[1], NotCondition)
    assert isinstance(inner_any.children[1].child, ExistsCondition)


# --- actions and rules ---------------------------------------------------------


def test_action_maps_to_action_request():
    req = build_action(ActionConfig(type="click", params={"target": "#btn"}))
    assert isinstance(req, ActionRequest)
    assert req.action_type == "click"
    assert req.params["target"] == "#btn"
    assert req.rule_id is None  # engine stamps this at match time


def test_rule_maps_with_condition_actions_and_flags():
    cfg = RuleConfig(
        id="r1",
        enabled=False,
        cooldown_ms=2000,
        condition=ConditionConfig(type="exists", field="f"),
        actions=[ActionConfig(type="click"), ActionConfig(type="log")],
    )
    rule = build_rule(cfg)

    assert rule.id == "r1"
    assert rule.enabled is False
    assert rule.cooldown_ms == 2000
    assert isinstance(rule.condition, ExistsCondition)
    assert [a.action_type for a in rule.actions] == ["click", "log"]


# --- capture ------------------------------------------------------------------


def test_capture_target_full_page_is_none():
    assert build_capture_target(CaptureBindingConfig(name="b", target="full_page")) is None


def test_capture_target_region_maps_to_rect():
    cfg = CaptureBindingConfig(name="b", target="region", region=RegionConfig(x=1, y=2, w=3, h=4))
    assert build_capture_target(cfg) == Rect(x=1, y=2, w=3, h=4)


def test_capture_target_selector_maps():
    cfg = CaptureBindingConfig(name="b", target="selector", selector="#x")
    assert build_capture_target(cfg) == Selector(css="#x")


def test_capture_binding_builds_pipeline_with_analyzer_context():
    cfg = CaptureBindingConfig(
        name="header",
        target="region",
        region=RegionConfig(x=0, y=0, w=100, h=20),
        analyzers=[
            AnalyzerConfig(type="ocr", settings={"lang": "eng"}),
            AnalyzerConfig(type="template_match"),
        ],
    )
    binding = build_capture_binding("profile_01", cfg, default_analyzer_registry())

    assert binding.target == Rect(x=0, y=0, w=100, h=20)
    assert binding.pipeline.analyzer_names == ("ocr", "template_match")


def test_capture_binding_unknown_analyzer_type_raises():
    cfg = CaptureBindingConfig(
        name="b", target="full_page", analyzers=[AnalyzerConfig(type="mystery")]
    )
    with pytest.raises(CompositionError, match="no analyzer registered"):
        build_capture_binding("p", cfg, default_analyzer_registry())


def test_tab_profile_maps_id_url_and_viewport():
    cfg = ProfileConfig(id="p1", start_url="https://e.com", rule_pack="rp")
    tp = build_tab_profile(cfg)

    assert tp.id == "p1"
    assert tp.start_url == "https://e.com"
    assert (tp.viewport.width, tp.viewport.height) == (1920, 1080)
