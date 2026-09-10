import pytest

pytest.importorskip("cv2")
pytest.importorskip("pytesseract")

from bap.adapters.vision.ocr_tesseract import OcrAnalyzer
from bap.adapters.vision.registry import production_analyzer_registry
from bap.adapters.vision.template_match_opencv import TemplateMatchAnalyzer
from bap.core.ports.vision_analyzer_port import VisionAnalyzerPort


def test_production_registry_provides_real_analyzers():
    # include_plugins=False to assert the built-in set in isolation (installed
    # plugins would otherwise merge in).
    registry = production_analyzer_registry(include_plugins=False)

    assert set(registry.types) == {"ocr", "template_match"}
    assert isinstance(registry.create("ocr"), OcrAnalyzer)
    assert isinstance(registry.create("template_match"), TemplateMatchAnalyzer)


def test_each_create_returns_a_fresh_instance():
    registry = production_analyzer_registry(include_plugins=False)

    assert registry.create("ocr") is not registry.create("ocr")


def test_registered_analyzer_can_be_replaced():
    class CustomAnalyzer(VisionAnalyzerPort):
        @property
        def name(self) -> str:
            return "custom"

        async def analyze(self, image, context):
            return []

    registry = production_analyzer_registry()
    registry.register("ocr", CustomAnalyzer)  # override the default

    assert isinstance(registry.create("ocr"), CustomAnalyzer)
    # the other analyzer is untouched
    assert isinstance(registry.create("template_match"), TemplateMatchAnalyzer)
