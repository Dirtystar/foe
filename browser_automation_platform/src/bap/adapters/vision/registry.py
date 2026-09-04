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


def production_analyzer_registry(
    *, include_plugins: bool = True, entry_points=None, allow_override: bool = False
) -> AnalyzerRegistry:
    """Built-in analyzers, then any installed plugins from the 'bap.analyzers'
    entry-point group merged on top. A plugin whose name collides with a
    built-in is a conflict error unless allow_override=True. `entry_points` is
    injectable for testing."""
    registry = AnalyzerRegistry()
    registry.register("ocr", lambda: OcrAnalyzer("ocr"))
    registry.register("template_match", lambda: TemplateMatchAnalyzer("template_match"))
    if include_plugins:
        from bap.app.plugins import apply_analyzer_plugins

        apply_analyzer_plugins(
            registry, entry_points=entry_points, allow_override=allow_override
        )
    return registry


__all__ = ["production_analyzer_registry"]
