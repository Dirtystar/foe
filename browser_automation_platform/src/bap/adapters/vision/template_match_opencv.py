"""OpenCV template-matching analyzer (VisionAnalyzerPort).

Loads reference images named in AnalyzerContext.settings and reports where
each one appears in the captured image, using the existing Observation shape
(value = template id, confidence = match score, region = matched rectangle
in the analyzed image's coordinate space).

Settings:
  template:   path to one reference image, OR
  templates:  {id: path} for several
  threshold:  minimum normalized score to report a match (default 0.8)

Only matches at or above the threshold are emitted; a scene with no match
returns [] (nothing found). Undecodable images or unreadable/oversized
templates raise VisionAnalyzerError so the pipeline contains them.
"""

from __future__ import annotations

from pathlib import Path

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ImageData, Observation, Rect
from bap.core.ports.vision_analyzer_port import (
    AnalyzerContext,
    VisionAnalyzerError,
    VisionAnalyzerPort,
)


class TemplateMatchAnalyzer(VisionAnalyzerPort):
    def __init__(self, name: str = "template_match") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def analyze(self, image: ImageData, context: AnalyzerContext) -> list[Observation]:
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise VisionAnalyzerError(f"template matching requires the 'vision' extra: {exc}") from exc

        settings = context.settings
        templates = self._resolve_templates(settings)
        threshold = float(settings.get("threshold", 0.8))

        scene = cv2.imdecode(np.frombuffer(image.data, np.uint8), cv2.IMREAD_GRAYSCALE)
        if scene is None:
            raise VisionAnalyzerError("template matching could not decode the captured image")

        prefix = context.target_name or self._name
        observations: list[Observation] = []
        for template_id, path in templates.items():
            tmpl = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if tmpl is None:
                raise VisionAnalyzerError(f"template '{template_id}': cannot read image '{path}'")
            th, tw = tmpl.shape[:2]
            sh, sw = scene.shape[:2]
            if th > sh or tw > sw:
                raise VisionAnalyzerError(
                    f"template '{template_id}' ({tw}x{th}) is larger than the scene ({sw}x{sh})"
                )
            result = cv2.matchTemplate(scene, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val < threshold:
                continue
            observations.append(
                Observation(
                    name=f"{prefix}.{template_id}",
                    kind=ObservationKind.TEMPLATE_MATCH,
                    analyzer=self._name,
                    value=template_id,
                    confidence=max(0.0, min(1.0, float(max_val))),
                    region=Rect(x=int(max_loc[0]), y=int(max_loc[1]), w=int(tw), h=int(th)),
                )
            )
        return observations

    @staticmethod
    def _resolve_templates(settings) -> dict[str, str]:
        templates = settings.get("templates")
        if isinstance(templates, dict) and templates:
            return {str(k): str(v) for k, v in templates.items()}
        single = settings.get("template")
        if single:
            return {Path(str(single)).stem: str(single)}
        raise VisionAnalyzerError(
            "template matching requires a 'template' path or a 'templates' mapping"
        )


__all__ = ["TemplateMatchAnalyzer"]
