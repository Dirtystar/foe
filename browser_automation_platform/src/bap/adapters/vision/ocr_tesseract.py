"""Tesseract-backed OCR analyzer (VisionAnalyzerPort).

Decodes the captured image, runs Tesseract, and emits recognized text as
Observations in the existing shape. Library specifics (lang, page-seg mode,
character whitelist, min confidence, binary path) arrive through the opaque
AnalyzerContext.settings — none of them reach core config models.

Failures (missing binary, undecodable image) become VisionAnalyzerError, so
the pipeline records a contained failure instead of a raw library exception.
Successful analysis that finds no text returns [] — an empty result, not an
error.
"""

from __future__ import annotations

import io
import re

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ImageData, Observation
from bap.core.ports.vision_analyzer_port import (
    AnalyzerContext,
    VisionAnalyzerError,
    VisionAnalyzerPort,
)

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class OcrAnalyzer(VisionAnalyzerPort):
    def __init__(self, name: str = "ocr") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def analyze(self, image: ImageData, context: AnalyzerContext) -> list[Observation]:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:  # optional dependency not installed
            raise VisionAnalyzerError(f"OCR requires the 'vision' extra: {exc}") from exc

        settings = context.settings
        cmd = settings.get("tesseract_cmd")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = str(cmd)

        try:
            pil_image = Image.open(io.BytesIO(image.data))
            pil_image.load()
        except Exception as exc:
            raise VisionAnalyzerError(f"OCR could not decode image: {exc}") from exc

        config = self._build_config(settings)
        try:
            data = pytesseract.image_to_data(
                pil_image,
                lang=str(settings.get("lang", "eng")),
                config=config,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:  # TesseractNotFoundError, runtime errors, ...
            raise VisionAnalyzerError(f"OCR failed: {exc}") from exc

        text, confidence = self._collect_text(data, float(settings.get("min_confidence", 0.0)))
        if not text:
            return []

        prefix = context.target_name or self._name
        observations = [
            Observation(
                name=f"{prefix}.text",
                kind=ObservationKind.TEXT,
                analyzer=self._name,
                value=text,
                confidence=confidence,
            )
        ]
        if settings.get("numeric"):
            match = _NUMBER_RE.search(text)
            if match:
                raw = match.group()
                value: float | int = float(raw) if "." in raw else int(raw)
                observations.append(
                    Observation(
                        name=f"{prefix}.number",
                        kind=ObservationKind.TEXT,
                        analyzer=self._name,
                        value=value,
                        confidence=confidence,
                    )
                )
        return observations

    @staticmethod
    def _build_config(settings) -> str:
        parts: list[str] = []
        if "psm" in settings:
            parts.append(f"--psm {int(settings['psm'])}")
        whitelist = settings.get("whitelist")
        if whitelist:
            parts.append(f"-c tessedit_char_whitelist={whitelist}")
        return " ".join(parts)

    @staticmethod
    def _collect_text(data: dict, min_confidence: float) -> tuple[str, float]:
        """Join recognized words above the confidence floor; report the mean
        confidence of the kept words (normalized to 0..1)."""
        words: list[str] = []
        confs: list[float] = []
        for word, conf in zip(data.get("text", []), data.get("conf", [])):
            try:
                conf_value = float(conf)
            except (TypeError, ValueError):
                continue
            if conf_value < 0 or not word.strip():
                continue  # -1 marks a non-text box
            normalized = conf_value / 100.0
            if normalized < min_confidence:
                continue
            words.append(word.strip())
            confs.append(normalized)
        if not words:
            return "", 0.0
        return " ".join(words), sum(confs) / len(confs)


__all__ = ["OcrAnalyzer"]
