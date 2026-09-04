import textwrap

import pytest

from bap.config.config_loader import (
    ConfigError,
    load_config,
    load_config_from_string,
)
from bap.config.config_models import ApplicationConfig

VALID = textwrap.dedent(
    """
    version: 1
    settings:
      max_sessions: 4
      headless: true
      browser_engine: chromium
    rule_packs:
      default:
        - id: click_when_low
          cooldown_ms: 2000
          condition:
            type: all
            conditions:
              - type: exists
                field: header.text
              - type: compare
                field: header.count
                op: less_than
                value: 100
          actions:
            - type: click
              params: { target: main_panel }
        - id: stop_on_error
          enabled: false
          condition:
            type: any
            conditions:
              - type: compare
                field: banner.template
                op: equals
                value: error_banner
          actions:
            - type: stop_session
    profiles:
      - id: profile_01
        start_url: "https://example.com/"
        session:
          interval_ms: 500
          jitter_ms: 100
        rule_pack: default
        capture_bindings:
          - name: header
            target: region
            region: { x: 0, y: 0, w: 800, h: 120 }
            analyzers:
              - type: ocr
                settings: { lang: eng }
          - name: banner
            target: selector
            selector: "#banner"
      - id: profile_02
        rule_pack: default
    """
)


def test_valid_yaml_loads_successfully():
    config = load_config_from_string(VALID)

    assert isinstance(config, ApplicationConfig)
    assert config.settings.max_sessions == 4
    assert config.settings.headless is True
    assert [p.id for p in config.profiles] == ["profile_01", "profile_02"]
    assert len(config.rule_packs["default"]) == 2


def test_multiple_profiles_and_bindings_parse():
    config = load_config_from_string(VALID)
    p1 = config.profiles[0]

    assert p1.session.interval_ms == 500
    assert p1.session.jitter_ms == 100
    assert [b.name for b in p1.capture_bindings] == ["header", "banner"]
    assert p1.capture_bindings[0].region.w == 800
    assert p1.capture_bindings[0].analyzers[0].settings == {"lang": "eng"}
    assert p1.capture_bindings[1].selector == "#banner"


def test_nested_rule_condition_and_actions_parse():
    config = load_config_from_string(VALID)
    rule = config.rule_packs["default"][0]

    assert rule.id == "click_when_low"
    assert rule.cooldown_ms == 2000
    assert rule.condition.type == "all"
    assert rule.condition.conditions[1].op == "less_than"
    assert rule.actions[0].type == "click"
    assert config.rule_packs["default"][1].enabled is False


def test_defaults_applied_for_optional_fields():
    config = load_config_from_string(
        textwrap.dedent(
            """
            rule_packs:
              p: []
            profiles:
              - id: only
                rule_pack: p
            """
        )
    )
    profile = config.profiles[0]

    assert config.settings.max_sessions == 8  # global default
    assert config.settings.browser_engine == "chromium"
    assert profile.viewport.width == 1920
    assert profile.session.interval_ms == 500
    assert profile.capture_bindings == []


# --- empty / minimal ----------------------------------------------------------


def test_empty_document_is_an_empty_configuration():
    for text in ("", "   ", "# just a comment\n"):
        config = load_config_from_string(text)
        assert config.profiles == []
        assert config.rule_packs == {}
        assert config.settings.max_sessions == 8


# --- invalid input ------------------------------------------------------------


def test_invalid_yaml_syntax_raises_config_error():
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config_from_string("profiles: [unclosed")


def test_non_mapping_top_level_raises_config_error():
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config_from_string("- just\n- a\n- list")


def test_missing_required_field_raises_config_error():
    # profile without the required rule_pack
    with pytest.raises(ConfigError) as exc:
        load_config_from_string(
            textwrap.dedent(
                """
                profiles:
                  - id: p1
                """
            )
        )
    assert "rule_pack" in str(exc.value)


def test_unknown_field_is_rejected():
    with pytest.raises(ConfigError) as exc:
        load_config_from_string(
            textwrap.dedent(
                """
                rule_packs: { p: [] }
                profiles:
                  - id: p1
                    rule_pack: p
                    intervall_ms: 500
                """
            )
        )
    assert "intervall_ms" in str(exc.value) or "Extra inputs" in str(exc.value)


def test_duplicate_profile_ids_rejected():
    with pytest.raises(ConfigError, match="duplicate profile ids"):
        load_config_from_string(
            textwrap.dedent(
                """
                rule_packs: { p: [] }
                profiles:
                  - id: dup
                    rule_pack: p
                  - id: dup
                    rule_pack: p
                """
            )
        )


def test_duplicate_rule_ids_within_pack_rejected():
    with pytest.raises(ConfigError, match="duplicate rule ids"):
        load_config_from_string(
            textwrap.dedent(
                """
                rule_packs:
                  p:
                    - id: r1
                      condition: { type: exists, field: x }
                      actions: [{ type: noop }]
                    - id: r1
                      condition: { type: exists, field: y }
                      actions: [{ type: noop }]
                profiles: []
                """
            )
        )


def test_unknown_rule_pack_reference_rejected():
    with pytest.raises(ConfigError, match="unknown rule pack"):
        load_config_from_string(
            textwrap.dedent(
                """
                rule_packs: { real: [] }
                profiles:
                  - id: p1
                    rule_pack: ghost
                """
            )
        )


def test_duplicate_binding_names_within_profile_rejected():
    with pytest.raises(ConfigError, match="duplicate capture binding names"):
        load_config_from_string(
            textwrap.dedent(
                """
                rule_packs: { p: [] }
                profiles:
                  - id: p1
                    rule_pack: p
                    capture_bindings:
                      - { name: same, target: full_page }
                      - { name: same, target: full_page }
                """
            )
        )


# --- nested validation --------------------------------------------------------


@pytest.mark.parametrize(
    "condition_yaml,message",
    [
        ("{ type: exists }", "requires a 'field'"),
        ("{ type: compare, field: x }", "requires 'op' and 'value'"),
        ("{ type: confidence, field: x }", "requires 'minimum'"),
        ("{ type: staleness, field: x }", "requires 'max_age_ms'"),
        ("{ type: all }", "non-empty 'conditions'"),
        ("{ type: not }", "requires a 'condition'"),
        ("{ type: bogus, field: x }", "unknown condition type"),
    ],
)
def test_condition_shape_validation(condition_yaml, message):
    with pytest.raises(ConfigError, match=message):
        load_config_from_string(
            textwrap.dedent(
                f"""
                rule_packs:
                  p:
                    - id: r1
                      condition: {condition_yaml}
                      actions: [{{ type: noop }}]
                profiles: []
                """
            )
        )


def test_rule_requires_at_least_one_action():
    with pytest.raises(ConfigError):
        load_config_from_string(
            textwrap.dedent(
                """
                rule_packs:
                  p:
                    - id: r1
                      condition: { type: exists, field: x }
                      actions: []
                profiles: []
                """
            )
        )


@pytest.mark.parametrize(
    "binding_yaml,message",
    [
        ("{ name: b, target: region }", "requires a 'region'"),
        ("{ name: b, target: selector }", "requires a 'selector'"),
        (
            "{ name: b, target: full_page, selector: '#x' }",
            "neither region nor selector",
        ),
    ],
)
def test_capture_binding_target_validation(binding_yaml, message):
    with pytest.raises(ConfigError, match=message):
        load_config_from_string(
            textwrap.dedent(
                f"""
                rule_packs: {{ p: [] }}
                profiles:
                  - id: p1
                    rule_pack: p
                    capture_bindings:
                      - {binding_yaml}
                """
            )
        )


def test_out_of_range_numeric_fields_rejected():
    with pytest.raises(ConfigError):
        load_config_from_string(
            textwrap.dedent(
                """
                settings: { max_sessions: 0 }
                profiles: []
                """
            )
        )


# --- immutability and equivalence ---------------------------------------------


def test_parsed_models_are_immutable():
    config = load_config_from_string(VALID)

    with pytest.raises(Exception):
        config.profiles[0].session.interval_ms = 999  # type: ignore[misc]


def test_loading_twice_produces_equivalent_objects():
    first = load_config_from_string(VALID)
    second = load_config_from_string(VALID)

    assert first == second
    assert first is not second


def test_loading_has_no_side_effects_on_input_text():
    text = VALID
    load_config_from_string(text)
    load_config_from_string(text)

    assert text == VALID  # input untouched


# --- no runtime objects -------------------------------------------------------


def test_no_runtime_objects_created_during_loading():
    """The config layer must not import or instantiate runtime execution
    types. Loading yields only config models."""
    import sys

    config = load_config_from_string(VALID)

    # The result graph is composed purely of config models / primitives.
    from bap.config import config_models as cm

    assert type(config) is cm.ApplicationConfig
    assert all(type(p) is cm.ProfileConfig for p in config.profiles)

    # Loading must not have pulled runtime engine modules into the process
    # merely by parsing config (they are only imported by the composition
    # root). We assert the loader module itself has no such import.
    import bap.config.config_loader as loader

    source_refs = dir(loader)
    for forbidden in ("RuleEngine", "ActionExecutor", "TabSession", "PlaywrightBrowserManager"):
        assert forbidden not in source_refs


# --- file loading -------------------------------------------------------------


def test_load_config_from_file(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text(VALID, encoding="utf-8")

    config = load_config(path)

    assert [p.id for p in config.profiles] == ["profile_01", "profile_02"]


def test_load_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_config(tmp_path / "does_not_exist.yaml")
