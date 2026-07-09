"""User-facing configuration schema (Pydantic).

These models describe *intent*, not runtime objects. They are deliberately
separate from the runtime domain models (TabProfile, Rule, ActionRequest,
CaptureBinding): configuration is validated user input with its own shape
and vocabulary, and the composition root translates it into runtime objects
later. Nothing here imports a runtime layer, and constructing these models
has no side effects — no browser, no session, no engine is created.

Policy on unknown fields: REJECTED. Every model sets extra="forbid" so a
typo ("intervall_ms") fails loudly at load time instead of being silently
ignored and leaving a profile behaving unexpectedly.

Models are frozen, so a parsed configuration is immutable and two loads of
the same file compare equal.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- capture ------------------------------------------------------------------


class RegionConfig(_Base):
    x: Annotated[int, Field(ge=0)]
    y: Annotated[int, Field(ge=0)]
    w: Annotated[int, Field(gt=0)]
    h: Annotated[int, Field(gt=0)]


class AnalyzerConfig(_Base):
    """One analyzer to run against a capture target. `type` selects the
    implementation in the composition root; `settings` is its opaque config
    block (thresholds, language, template path, plugin options)."""

    type: Annotated[str, Field(min_length=1)]
    settings: dict[str, object] = Field(default_factory=dict)


class CaptureBindingConfig(_Base):
    """A named thing to look at on the page, and the analyzers to run on it.

    `target` chooses what is captured; the matching parameter must be present:
      - full_page: neither region nor selector
      - region:    region required
      - selector:  selector required
    """

    name: Annotated[str, Field(min_length=1)]
    target: Literal["full_page", "region", "selector"] = "full_page"
    region: RegionConfig | None = None
    selector: str | None = None
    analyzers: list[AnalyzerConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_target_params(self) -> "CaptureBindingConfig":
        if self.target == "region" and self.region is None:
            raise ValueError(f"binding '{self.name}': target 'region' requires a 'region' block")
        if self.target == "selector" and not self.selector:
            raise ValueError(f"binding '{self.name}': target 'selector' requires a 'selector'")
        if self.target == "full_page" and (self.region or self.selector):
            raise ValueError(
                f"binding '{self.name}': target 'full_page' takes neither region nor selector"
            )
        return self


# --- rules --------------------------------------------------------------------


_LEAF_TYPES = {"exists", "compare", "confidence", "staleness"}
_COMPOSITE_TYPES = {"all", "any", "not"}


class ConditionConfig(_Base):
    """A recursive condition description.

    Leaf types read a field:
      - exists:     field
      - compare:    field, op, value
      - confidence: field, minimum
      - staleness:  field, max_age_ms
    Composites nest other conditions:
      - all / any:  conditions (list)
      - not:        condition (single)

    This is a config vocabulary, not the runtime Condition classes; the
    composition root maps each type to a concrete Condition.
    """

    type: str
    field: str | None = None
    op: str | None = None
    value: object | None = None
    minimum: float | None = None
    max_age_ms: int | None = None
    conditions: list["ConditionConfig"] | None = None
    condition: "ConditionConfig | None" = None

    @model_validator(mode="after")
    def _check_shape(self) -> "ConditionConfig":
        t = self.type
        if t not in _LEAF_TYPES and t not in _COMPOSITE_TYPES:
            raise ValueError(
                f"unknown condition type '{t}' "
                f"(expected one of {sorted(_LEAF_TYPES | _COMPOSITE_TYPES)})"
            )
        if t in _LEAF_TYPES and not self.field:
            raise ValueError(f"condition '{t}' requires a 'field'")
        if t == "compare" and (self.op is None or self.value is None):
            raise ValueError("condition 'compare' requires 'op' and 'value'")
        if t == "confidence" and self.minimum is None:
            raise ValueError("condition 'confidence' requires 'minimum'")
        if t == "staleness" and self.max_age_ms is None:
            raise ValueError("condition 'staleness' requires 'max_age_ms'")
        if t in {"all", "any"} and not self.conditions:
            raise ValueError(f"condition '{t}' requires a non-empty 'conditions' list")
        if t == "not" and self.condition is None:
            raise ValueError("condition 'not' requires a 'condition'")
        return self


class ActionConfig(_Base):
    """One action to emit when a rule matches. `type` selects the handler in
    the composition root; `params` is its opaque parameter block."""

    type: Annotated[str, Field(min_length=1)]
    params: dict[str, object] = Field(default_factory=dict)


class RuleConfig(_Base):
    id: Annotated[str, Field(min_length=1)]
    enabled: bool = True
    cooldown_ms: Annotated[int, Field(ge=0)] = 0
    condition: ConditionConfig
    actions: Annotated[list[ActionConfig], Field(min_length=1)]


# --- profiles and application -------------------------------------------------


class ViewportConfig(_Base):
    width: Annotated[int, Field(gt=0)] = 1920
    height: Annotated[int, Field(gt=0)] = 1080


class SessionConfig(_Base):
    interval_ms: Annotated[int, Field(gt=0)] = 500
    jitter_ms: Annotated[int, Field(ge=0)] = 0


class ProfileConfig(_Base):
    id: Annotated[str, Field(min_length=1)]
    start_url: str | None = None
    viewport: ViewportConfig = Field(default_factory=ViewportConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    rule_pack: Annotated[str, Field(min_length=1)]
    capture_bindings: list[CaptureBindingConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_binding_names_unique(self) -> "ProfileConfig":
        names = [b.name for b in self.capture_bindings]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"profile '{self.id}': duplicate capture binding names {dupes}")
        return self


class BrowserLimitsConfig(_Base):
    """Observational safety limits. Exceeding one raises resource pressure —
    it never kills the browser directly."""

    max_memory_mb: Annotated[int, Field(gt=0)] | None = None
    max_pages: Annotated[int, Field(gt=0)] | None = None


class ResourceMonitoringConfig(_Base):
    enabled: bool = False
    collect_every_ticks: Annotated[int, Field(gt=0)] = 50
    limits: BrowserLimitsConfig = Field(default_factory=BrowserLimitsConfig)


class GlobalSettings(_Base):
    max_sessions: Annotated[int, Field(gt=0)] = 8
    headless: bool = False
    browser_engine: Literal["chromium", "firefox", "webkit"] = "chromium"
    isolate_contexts_per_tab: bool = True
    resource_monitoring: ResourceMonitoringConfig = Field(
        default_factory=ResourceMonitoringConfig
    )


class ApplicationConfig(_Base):
    version: int = 1
    settings: GlobalSettings = Field(default_factory=GlobalSettings)
    rule_packs: dict[str, list[RuleConfig]] = Field(default_factory=dict)
    profiles: list[ProfileConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cross_checks(self) -> "ApplicationConfig":
        # unique profile ids
        ids = [p.id for p in self.profiles]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate profile ids {dupes}")

        # unique rule ids within each pack
        for pack_name, rules in self.rule_packs.items():
            rule_ids = [r.id for r in rules]
            rdupes = sorted({i for i in rule_ids if rule_ids.count(i) > 1})
            if rdupes:
                raise ValueError(f"rule pack '{pack_name}': duplicate rule ids {rdupes}")

        # every referenced rule pack exists
        for profile in self.profiles:
            if profile.rule_pack not in self.rule_packs:
                raise ValueError(
                    f"profile '{profile.id}' references unknown rule pack "
                    f"'{profile.rule_pack}' (defined packs: {sorted(self.rule_packs)})"
                )
        return self


__all__ = [
    "ActionConfig",
    "AnalyzerConfig",
    "ApplicationConfig",
    "BrowserLimitsConfig",
    "CaptureBindingConfig",
    "ConditionConfig",
    "GlobalSettings",
    "ProfileConfig",
    "RegionConfig",
    "ResourceMonitoringConfig",
    "RuleConfig",
    "SessionConfig",
    "ViewportConfig",
]
