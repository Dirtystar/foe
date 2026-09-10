import pytest

from bap.adapters.vision.registry import production_analyzer_registry
from bap.app.composition import create_application
from bap.app.errors import CompositionError
from bap.app.plugins import apply_analyzer_plugins
from bap.app.registries import AnalyzerRegistry
from bap.app.stubs import StubBrowser, default_action_registry, default_analyzer_registry
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import Observation
from bap.core.ports.vision_analyzer_port import VisionAnalyzerPort
from bap.core.rules.rule_engine import RuleStatus

CONFIG = """
rule_packs:
  pack:
    - id: act_on_plugin
      condition: { type: exists, field: screen.plugin_value }
      actions:
        - type: click
          params: { selector: "#x" }
profiles:
  - id: p
    rule_pack: pack
    session: { interval_ms: 10 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: custom_ocr
            settings: { value: hello }
"""


class FakeEP:
    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


class PluginAnalyzer(VisionAnalyzerPort):
    @property
    def name(self):
        return "custom_ocr"

    async def analyze(self, image, context):
        return [
            Observation(
                name=f"{context.target_name}.plugin_value",
                kind=ObservationKind.CUSTOM,
                analyzer=self.name,
                value=context.settings.get("value"),
            )
        ]


def plugin_analyzer_registry():
    registry = default_analyzer_registry()  # stub built-ins (ocr, etc.)
    apply_analyzer_plugins(registry, entry_points=[FakeEP("custom_ocr", lambda: PluginAnalyzer)])
    return registry


# --- composition --------------------------------------------------------------


def test_config_referencing_plugin_analyzer_composes():
    app = create_application(
        load_config_from_string(CONFIG),
        browser=StubBrowser(),
        analyzer_registry=plugin_analyzer_registry(),
    )
    assert app is not None


def test_unknown_type_still_fails_composition_without_the_plugin():
    with pytest.raises(CompositionError, match="no analyzer registered"):
        create_application(
            load_config_from_string(CONFIG),
            browser=StubBrowser(),
            analyzer_registry=default_analyzer_registry(),  # no custom_ocr
        )


def test_invalid_plugin_fails_before_browser_starts():
    class BadFactory:
        # a "plugin" whose factory returns a non-analyzer
        def __call__(self):
            return "not-an-analyzer"

    registry = default_analyzer_registry()
    registry.register("custom_ocr", BadFactory())
    browser = StubBrowser()

    with pytest.raises(CompositionError):
        create_application(
            load_config_from_string(CONFIG), browser=browser, analyzer_registry=registry
        )
    assert browser.started is False  # composition failed before any browser start


# --- runtime: full pipeline through a plugin analyzer -------------------------


async def test_plugin_analyzer_drives_the_full_pipeline():
    reports = []
    supervisor = Supervisor(monitor=HealthMonitor(), sink=reports.append)
    app = create_application(
        load_config_from_string(CONFIG),
        on_report=supervisor.on_report,
        browser=StubBrowser(),
        analyzer_registry=plugin_analyzer_registry(),
    )
    supervisor.session_manager = app.manager

    await app.create_sessions()
    try:
        await app.scheduler.run_once()
    finally:
        await app.stop()

    report = reports[-1]
    assert report.completed
    # plugin analyzer produced the field, the rule matched, the action ran
    assert report.page_state.value_of("screen.plugin_value") == "hello"
    assert report.evaluation.results[0].status is RuleStatus.MATCHED
    assert report.execution.fully_succeeded


def test_plugin_factory_receives_settings_via_context():
    # settings flow through AnalyzerContext (no plugin config schema in core):
    # the analyzer reads context.settings at analyze() time.
    from bap.app.translation import build_capture_binding
    from bap.config.config_models import AnalyzerConfig, CaptureBindingConfig

    registry = AnalyzerRegistry()
    registry.register("custom_ocr", lambda: PluginAnalyzer())
    cfg = CaptureBindingConfig(
        name="screen", target="full_page",
        analyzers=[AnalyzerConfig(type="custom_ocr", settings={"value": "abc"})],
    )
    binding = build_capture_binding("p", cfg, registry)
    ctx = binding.pipeline._bindings[0].context  # noqa: SLF001
    assert ctx.settings["value"] == "abc"
