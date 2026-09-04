import pytest

from bap.adapters.vision.registry import production_analyzer_registry
from bap.app.plugins import (
    PluginError,
    apply_analyzer_plugins,
    load_analyzer_plugins,
    register_plugins,
)
from bap.app.registries import AnalyzerRegistry
from bap.core.ports.vision_analyzer_port import VisionAnalyzerPort


class FakeEP:
    """Minimal entry-point stand-in (name + load), for injectable discovery."""

    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


class GoodAnalyzer(VisionAnalyzerPort):
    @property
    def name(self):
        return "good"

    async def analyze(self, image, context):
        return []


def good_ep(name="custom"):
    return FakeEP(name, lambda: (lambda: GoodAnalyzer()))


# --- discovery ----------------------------------------------------------------


def test_builtins_available_without_plugins():
    registry = production_analyzer_registry(include_plugins=False)
    assert registry.knows("ocr")
    assert registry.knows("template_match")


def test_plugin_entry_point_is_discovered_and_loaded():
    factories = load_analyzer_plugins(entry_points=[good_ep("custom_ocr")])
    assert set(factories) == {"custom_ocr"}
    assert isinstance(factories["custom_ocr"](), GoodAnalyzer)


def test_plugins_merge_on_top_of_builtins():
    registry = production_analyzer_registry(
        include_plugins=True, entry_points=[good_ep("custom_ocr")]
    )
    assert registry.knows("ocr")  # built-in
    assert registry.knows("custom_ocr")  # plugin
    assert isinstance(registry.create("custom_ocr"), GoodAnalyzer)


# --- conflict behavior --------------------------------------------------------


def test_plugin_conflicting_with_builtin_is_rejected_by_default():
    with pytest.raises(PluginError, match="conflicts"):
        production_analyzer_registry(include_plugins=True, entry_points=[good_ep("ocr")])


def test_plugin_conflict_can_be_overridden_explicitly():
    registry = production_analyzer_registry(
        include_plugins=True, entry_points=[good_ep("ocr")], allow_override=True
    )
    assert isinstance(registry.create("ocr"), GoodAnalyzer)  # plugin replaced the built-in


# --- invalid plugins ----------------------------------------------------------


def test_non_callable_entry_point_is_rejected():
    bad = FakeEP("bad", lambda: "not-callable")
    with pytest.raises(PluginError, match="not callable"):
        load_analyzer_plugins(entry_points=[bad])


def test_failing_entry_point_load_is_rejected():
    def boom():
        raise ImportError("missing dependency")

    bad = FakeEP("bad", boom)
    with pytest.raises(PluginError, match="failed to load"):
        load_analyzer_plugins(entry_points=[bad])


# --- isolation / no global state ----------------------------------------------


def test_one_bad_plugin_does_not_corrupt_a_registry():
    registry = AnalyzerRegistry()
    registry.register("builtin", lambda: GoodAnalyzer())
    with pytest.raises(PluginError):
        apply_analyzer_plugins(registry, entry_points=[FakeEP("bad", lambda: 123)])
    # the pre-existing registration is intact; nothing half-registered
    assert registry.knows("builtin")
    assert not registry.knows("bad")


def test_registries_do_not_share_state_between_calls():
    a = production_analyzer_registry(include_plugins=True, entry_points=[good_ep("only_a")])
    b = production_analyzer_registry(include_plugins=False)
    assert a.knows("only_a")
    assert not b.knows("only_a")  # independent registry, no leakage


# --- real installed example plugin --------------------------------------------


def test_real_installed_plugin_is_discovered():
    pytest.importorskip("fake_plugin")
    factories = load_analyzer_plugins()  # real importlib.metadata discovery
    if "fake_ocr" not in factories:
        pytest.skip("bap-fake-plugin not installed")
    analyzer = factories["fake_ocr"]()
    assert isinstance(analyzer, VisionAnalyzerPort)
    assert analyzer.name == "fake_ocr"
