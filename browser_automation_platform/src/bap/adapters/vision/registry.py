"""Registry wiring config analyzer-type strings to production analyzers.

Mirrors playwright_action_registry: the composition root injects this in
place of the stub analyzer registry to run real vision. Analyzer instances
are stateless, so the factories simply construct one per use; per-target
settings still flow through AnalyzerContext at analyze time.
"""

from __future__ import annotations

from bap.adapters.vision.ocr_tesseract import OcrAnalyzer
from bap.adapters.vision.template_match_opencv import TemplateMatchAnalyzer
from bap.app.registries import AnalyzerRegistry


def production_analyzer_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    registry.register("ocr", lambda: OcrAnalyzer("ocr"))
    registry.register("template_match", lambda: TemplateMatchAnalyzer("template_match"))
    return registry


__all__ = ["production_analyzer_registry"]
