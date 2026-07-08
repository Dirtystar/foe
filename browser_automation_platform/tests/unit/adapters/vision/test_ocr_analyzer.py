import io
from datetime import datetime, timezone

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pytesseract")

import pytesseract
from PIL import Image

from bap.adapters.vision.ocr_tesseract import OcrAnalyzer
from bap.core.domain.models import ImageData
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerError


def make_png(size=(60, 24), color=255) -> bytes:
    buf = io.BytesIO()
    Image.new("L", size, color).save(buf, format="PNG")
    return buf.getvalue()


def image(data: bytes | None = None) -> ImageData:
    return ImageData(
        data=data if data is not None else make_png(),
        width=60,
        height=24,
        tab_id="t1",
        captured_at=datetime.now(timezone.utc),
    )


def ctx(**settings) -> AnalyzerContext:
    return AnalyzerContext(profile_id="p1", target_name="header", settings=settings)


def fake_dict(words_confs):
    return {
        "text": [w for w, _ in words_confs],
        "conf": [c for _, c in words_confs],
    }


@pytest.fixture
def mock_ocr(monkeypatch):
    def install(words_confs=None, error: Exception | None = None):
        def fake_image_to_data(img, **kwargs):
            if error is not None:
                raise error
            return fake_dict(words_confs or [])

        monkeypatch.setattr(pytesseract, "image_to_data", fake_image_to_data)

    return install


async def test_recognized_text_becomes_observation_with_mean_confidence(mock_ocr):
    mock_ocr([("Count:", 90), ("42", 80)])

    obs = await OcrAnalyzer().analyze(image(), ctx())

    assert len(obs) == 1
    assert obs[0].name == "header.text"
    assert obs[0].value == "Count: 42"
    assert obs[0].analyzer == "ocr"
    assert obs[0].confidence == pytest.approx(0.85)


async def test_low_confidence_words_are_filtered_by_min_confidence(mock_ocr):
    mock_ocr([("good", 95), ("noise", 10)])

    obs = await OcrAnalyzer().analyze(image(), ctx(min_confidence=0.5))

    assert obs[0].value == "good"
    assert obs[0].confidence == pytest.approx(0.95)


async def test_non_text_boxes_with_negative_conf_are_ignored(mock_ocr):
    mock_ocr([("", -1), ("hello", 88), ("   ", -1)])

    obs = await OcrAnalyzer().analyze(image(), ctx())

    assert obs[0].value == "hello"


async def test_numeric_setting_emits_parsed_number_observation(mock_ocr):
    mock_ocr([("Count:", 90), ("42", 90)])

    obs = await OcrAnalyzer().analyze(image(), ctx(numeric=True))

    by_name = {o.name: o for o in obs}
    assert by_name["header.text"].value == "Count: 42"
    assert by_name["header.number"].value == 42
    assert isinstance(by_name["header.number"].value, int)


async def test_no_recognized_text_returns_empty_not_error(mock_ocr):
    mock_ocr([("", -1), ("  ", -1)])

    assert await OcrAnalyzer().analyze(image(), ctx()) == []


async def test_ocr_runtime_error_becomes_vision_analyzer_error(mock_ocr):
    mock_ocr(error=RuntimeError("tesseract exploded"))

    with pytest.raises(VisionAnalyzerError, match="OCR failed"):
        await OcrAnalyzer().analyze(image(), ctx())


async def test_undecodable_image_becomes_vision_analyzer_error(mock_ocr):
    mock_ocr([("ignored", 90)])

    with pytest.raises(VisionAnalyzerError, match="could not decode"):
        await OcrAnalyzer().analyze(image(data=b"not a real image"), ctx())


async def test_target_name_prefixes_observation_names(mock_ocr):
    mock_ocr([("x", 90)])

    obs = await OcrAnalyzer().analyze(
        image(), AnalyzerContext(profile_id="p1", target_name="footer", settings={})
    )

    assert obs[0].name == "footer.text"
