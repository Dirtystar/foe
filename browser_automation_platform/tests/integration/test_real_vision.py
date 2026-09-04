"""Optional integration test: real Tesseract OCR on a rendered image.

Skipped by default. Run with:  pytest -m integration
Skips gracefully if the tesseract binary is not installed.
"""

import io
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("PIL")
pytest.importorskip("pytesseract")

import pytesseract
from PIL import Image, ImageDraw, ImageFont

from bap.adapters.vision.ocr_tesseract import OcrAnalyzer
from bap.core.domain.models import ImageData
from bap.core.ports.vision_analyzer_port import AnalyzerContext


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def render_text(text: str, size=(320, 90)) -> bytes:
    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 15), text, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract binary not installed")
async def test_real_ocr_reads_rendered_digits():
    data = render_text("12345")
    image = ImageData(
        data=data, width=320, height=90, tab_id="t1", captured_at=datetime.now(timezone.utc)
    )

    obs = await OcrAnalyzer().analyze(
        image, AnalyzerContext(profile_id="p1", target_name="panel", settings={"numeric": True})
    )

    by_name = {o.name: o for o in obs}
    assert "panel.text" in by_name
    assert "12345" in str(by_name["panel.text"].value).replace(" ", "")
    assert by_name["panel.number"].value == 12345
    assert 0.0 < by_name["panel.text"].confidence <= 1.0
