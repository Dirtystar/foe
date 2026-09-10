from datetime import datetime, timezone

import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")

import cv2
import numpy as np

from bap.adapters.vision.template_match_opencv import TemplateMatchAnalyzer
from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ImageData
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerError
from bap.core.vision.pipeline import AnalyzerBinding, VisionPipeline


def scene_with_patch(patch: np.ndarray, at: tuple[int, int], size=(200, 120)) -> np.ndarray:
    """Grey canvas with `patch` pasted at (x, y)."""
    canvas = np.full((size[1], size[0]), 127, dtype=np.uint8)
    x, y = at
    ph, pw = patch.shape[:2]
    canvas[y : y + ph, x : x + pw] = patch
    return canvas


def distinctive_patch(seed: int, size=(30, 20)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(size[1], size[0]), dtype=np.uint8)


def to_image(gray: np.ndarray) -> ImageData:
    ok, buf = cv2.imencode(".png", gray)
    assert ok
    data = buf.tobytes()
    return ImageData(
        data=data,
        width=gray.shape[1],
        height=gray.shape[0],
        tab_id="t1",
        captured_at=datetime.now(timezone.utc),
    )


def ctx(**settings) -> AnalyzerContext:
    return AnalyzerContext(profile_id="p1", target_name="panel", settings=settings)


@pytest.fixture
def template_file(tmp_path):
    def write(patch: np.ndarray, name="button.png") -> str:
        path = tmp_path / name
        assert cv2.imwrite(str(path), patch)
        return str(path)

    return write


async def test_template_found_reports_position_and_confidence(template_file):
    patch = distinctive_patch(1)
    path = template_file(patch, "button.png")
    scene = scene_with_patch(patch, at=(40, 25))

    obs = await TemplateMatchAnalyzer().analyze(to_image(scene), ctx(template=path, threshold=0.8))

    assert len(obs) == 1
    assert obs[0].name == "panel.button"
    assert obs[0].value == "button"
    assert obs[0].kind is ObservationKind.TEMPLATE_MATCH
    assert obs[0].confidence > 0.95
    assert (obs[0].region.x, obs[0].region.y) == (40, 25)
    assert (obs[0].region.w, obs[0].region.h) == (30, 20)


async def test_no_match_below_threshold_returns_empty(template_file):
    path = template_file(distinctive_patch(1), "button.png")
    scene = scene_with_patch(distinctive_patch(999), at=(10, 10))  # a different patch

    obs = await TemplateMatchAnalyzer().analyze(to_image(scene), ctx(template=path, threshold=0.9))

    assert obs == []


async def test_multiple_templates_each_reported(template_file):
    patch_a, patch_b = distinctive_patch(1), distinctive_patch(2)
    path_a = template_file(patch_a, "a.png")
    path_b = template_file(patch_b, "b.png")
    scene = scene_with_patch(patch_a, at=(10, 10))
    scene[60:80, 120:150] = patch_b  # paste b too

    obs = await TemplateMatchAnalyzer().analyze(
        to_image(scene), ctx(templates={"a": path_a, "b": path_b}, threshold=0.8)
    )

    names = sorted(o.name for o in obs)
    assert names == ["panel.a", "panel.b"]


async def test_missing_template_path_raises_vision_error(template_file):
    scene = scene_with_patch(distinctive_patch(1), at=(0, 0))

    with pytest.raises(VisionAnalyzerError, match="cannot read image"):
        await TemplateMatchAnalyzer().analyze(
            to_image(scene), ctx(template="/no/such/template.png")
        )


async def test_no_template_configured_raises_vision_error():
    scene = scene_with_patch(distinctive_patch(1), at=(0, 0))

    with pytest.raises(VisionAnalyzerError, match="requires a 'template'"):
        await TemplateMatchAnalyzer().analyze(to_image(scene), ctx())


async def test_template_larger_than_scene_raises_vision_error(template_file):
    big = distinctive_patch(1, size=(400, 400))
    path = template_file(big, "big.png")
    small_scene = scene_with_patch(distinctive_patch(2), at=(0, 0), size=(50, 50))

    with pytest.raises(VisionAnalyzerError, match="larger than the scene"):
        await TemplateMatchAnalyzer().analyze(to_image(small_scene), ctx(template=path))


async def test_undecodable_scene_raises_vision_error(template_file):
    path = template_file(distinctive_patch(1))
    bad = ImageData(
        data=b"not-a-png", width=1, height=1, tab_id="t", captured_at=datetime.now(timezone.utc)
    )

    with pytest.raises(VisionAnalyzerError, match="could not decode"):
        await TemplateMatchAnalyzer().analyze(bad, ctx(template=path))


async def test_analyzer_failure_is_contained_by_the_pipeline(template_file):
    """End-to-end: a raising analyzer becomes a recorded failure, not a crash."""
    scene = scene_with_patch(distinctive_patch(1), at=(0, 0))
    binding = AnalyzerBinding(
        analyzer=TemplateMatchAnalyzer(),
        context=ctx(template="/no/such/file.png"),
    )

    result = await VisionPipeline([binding]).run(to_image(scene))

    assert result.observations == ()
    assert len(result.failures) == 1
    assert result.failures[0].analyzer == "template_match"
    assert isinstance(result.failures[0].error, VisionAnalyzerError)
