"""The one canonical Reviewed Dataset (Milestone 4.15) — Qt-free.

Pins the single-source-of-truth contract: one resolvable location, an override,
content-hash dedup on add, detection seeding as an UNREVIEWED starting point, ROI
persistence, and — crucially — that the training/eval loader discovers the *same*
dataset the UI edits (no more scattered review targets).
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from types import SimpleNamespace

from bap.core.domain.models import Rect
from bap.forge import dataset_store
from bap.forge.detection.geometry import ScanRois
from bap.forge.labeling.model import LabelStore


@pytest.fixture
def canonical(tmp_path, monkeypatch):
    """Point THE canonical dataset at an isolated temp dir for the test."""
    monkeypatch.setenv("BAP_DATASET_DIR", str(tmp_path / "dataset"))
    return tmp_path / "dataset"


def _img(w=1920, h=1080, v=30):
    return np.full((h, w, 3), v, np.uint8)


def test_env_override_wins_and_creates_layout(canonical):
    assert dataset_store.reviewed_dataset_dir() == canonical
    root = dataset_store.reviewed_dataset_dir(create=True)
    assert (root / "frames").is_dir()
    assert (root / "labels.json").exists()      # a valid, empty labels.json is seeded
    assert LabelStore.load(root / "labels.json").files() == []
    assert dataset_store.dataset_exists() is True


def test_repo_root_resolution_without_override(monkeypatch):
    monkeypatch.delenv("BAP_DATASET_DIR", raising=False)
    # From source, the canonical dataset is the repo-root dataset/ — the exact dir
    # the training + evaluation loader discovers (single source of truth).
    root = dataset_store.reviewed_dataset_dir()
    assert root.name == "dataset"
    assert (root.parent / "pyproject.toml").exists()


def test_review_paths_are_under_the_one_dataset(canonical):
    frames, labels, calib = dataset_store.dataset_review_paths(create=True)
    root = str(canonical)
    assert frames.startswith(root) and labels.startswith(root) and calib.startswith(root)
    assert labels.endswith("labels.json")


def test_add_frame_dedups_by_content_hash(canonical):
    img = _img()
    img[100:120, 200:260] = 200
    name1, new1 = dataset_store.add_frame(img, alias="H")
    name2, new2 = dataset_store.add_frame(img, alias="H")
    assert new1 is True and new2 is False
    assert name1 == name2                              # same image => same frame
    assert len(list((canonical / "frames").glob("*.png"))) == 1


def test_add_frame_seeds_detections_unreviewed_and_persists_rois(canonical):
    img = _img()
    scan = SimpleNamespace(
        detections=[SimpleNamespace(cx=900, cy=740, pct=60),
                    SimpleNamespace(cx=500, cy=300, pct=None)],
        weakening=SimpleNamespace(value=42),
        rois=ScanRois(battle_map=Rect(0, 8, 1920, 1072),
                      weakening=Rect(2, 2, 90, 28), weakening_calibrated=True),
    )
    name, is_new = dataset_store.add_frame(img, alias="H", scan=scan)
    assert is_new is True
    label = LabelStore.load(canonical / "labels.json").get(name)
    # Seeded from detections but NOT yet ground truth (operator must confirm).
    assert label.reviewed is False
    assert label.weakening == 42
    assert sorted((b.cx, b.cy, b.pct) for b in label.badges) == [(500, 300, None), (900, 740, 60)]
    # ROIs persisted into the dataset calibration so Review shows the same regions.
    from bap.forge.detection.calibration import WeakeningCalibration

    cal = WeakeningCalibration.load(canonical / "calibration.json")
    assert cal.get(1920, 1080) == Rect(2, 2, 90, 28)


def test_summary_counts_frames_and_reviewed(canonical):
    dataset_store.add_frame(_img(v=10), alias="a")
    n2, _ = dataset_store.add_frame(_img(v=20), alias="b")
    # Mark one reviewed via the store to prove reviewed_count is surfaced.
    store = LabelStore.load(canonical / "labels.json")
    store.get(n2).reviewed = True
    store.save()
    s = dataset_store.dataset_summary()
    assert s["frames"] == 2 and s["labelled"] == 2 and s["reviewed"] == 1
    assert s["dir"] == str(canonical)


def test_loader_discovers_the_same_dataset_the_ui_edits(canonical):
    """The classifier/eval loader and the UI must resolve to ONE dataset."""
    from bap.forge.detection.classify import default_snapshot_dataset_dir

    # Empty (no labels yet) => loader adds nothing rather than erroring.
    assert default_snapshot_dataset_dir() is None
    # Once a frame is added through the canonical API, the loader finds that exact dir.
    dataset_store.add_frame(_img(), alias="H")
    assert default_snapshot_dataset_dir() == dataset_store.reviewed_dataset_dir()
