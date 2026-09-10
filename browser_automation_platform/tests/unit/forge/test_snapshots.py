"""Reproducible snapshot workflow (Milestone 4.13) — observe-only.

Covers snapshot creation, reload, the review round-trip (only labels.json may
change), metadata preservation, and dataset import with content-hash dedup. Uses
a fast fake detector so no heavy pipeline runs.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from bap.core.domain.models import Rect
from bap.forge.detection.geometry import CaptureGeometry, ScanRois
from bap.forge.detection.scan import build_scan
from bap.forge.labeling.model import Badge, LabelStore
from bap.forge.worlds import World
from bap.forge import snapshots


class _FakeDetector:
    _offset = (16, 0)
    score_threshold = 0.62

    def scan(self, image, region=None):
        return SimpleNamespace(detections=[], candidates=[])

    def score_at(self, image, x, y):
        return 0.0


def _scan(image, **geom_meta):
    rois = ScanRois(battle_map=Rect(0, 8, image.shape[1], image.shape[0] - 8),
                    weakening=Rect(2, 2, 20, 12), weakening_calibrated=True)
    geom = CaptureGeometry.from_image(image, viewport_w=image.shape[1], viewport_h=image.shape[0],
                                     device_pixel_ratio=1.0, **geom_meta)
    return build_scan(image, world=None, detector=_FakeDetector(), classifier=None,
                      rois=rois, geometry=geom)


def _image(w=120, h=90):
    return np.full((h, w, 3), 30, dtype=np.uint8)


def _md5(path) -> str:
    from pathlib import Path

    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def test_write_snapshot_creates_all_files(tmp_path):
    img = _image()
    world = World(alias="D", hostname="cz2.forgeofempires.com")
    d = snapshots.write_snapshot(img, _scan(img), world=world, classifier=None,
                                 detector=_FakeDetector(), validation_markdown="# report",
                                 url="https://cz2.forgeofempires.com/game", root=tmp_path)
    for rel in ("frames/raw.png", "annotated.png", "scan.json", "world.json",
                "calibration.json", "labels.json", "metadata.json", "validation_report.md"):
        assert (d / rel).exists(), f"missing {rel}"
    assert d.name.endswith("_D")


def test_metadata_is_complete(tmp_path):
    img = _image()
    world = World(alias="H", hostname="cz8.forgeofempires.com")
    d = snapshots.write_snapshot(img, _scan(img), world=world, root=tmp_path,
                                 url="https://cz8.forgeofempires.com/game")
    meta = json.loads((d / "metadata.json").read_text())
    for key in ("world_alias", "url", "resolution", "device_pixel_ratio", "viewport",
                "timestamp", "detector_version", "classifier_version", "git_commit",
                "image_md5", "snapshot_schema"):
        assert key in meta, f"metadata missing {key}"
    assert meta["world_alias"] == "H"
    assert meta["resolution"] == [120, 90]
    assert meta["image_md5"] == _md5(d / "frames" / "raw.png")


def test_snapshot_records_external_chrome_provenance(tmp_path):
    img = _image()
    d = snapshots.write_snapshot(
        img, _scan(img, browser_mode="external_chrome", cdp_endpoint="http://127.0.0.1:9222"),
        root=tmp_path)
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["browser_mode"] == "external_chrome"
    assert meta["browser_name"] == "External Chrome (CDP)"
    assert meta["cdp_endpoint"] == "http://127.0.0.1:9222"


def test_snapshot_managed_provenance_defaults(tmp_path):
    img = _image()
    d = snapshots.write_snapshot(img, _scan(img, browser_mode="managed_chromium"), root=tmp_path)
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["browser_mode"] == "managed_chromium"
    assert meta["browser_name"] == "Managed Chromium"
    assert meta["cdp_endpoint"] is None


def test_older_snapshot_without_provenance_still_loads(tmp_path):
    # A snapshot whose metadata predates the browser-provenance keys must remain
    # loadable (additive schema, no migration).
    img = _image()
    d = snapshots.write_snapshot(img, _scan(img), root=tmp_path)
    meta_path = d / "metadata.json"
    meta = json.loads(meta_path.read_text())
    for key in ("browser_mode", "browser_name", "cdp_endpoint"):
        meta.pop(key, None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    info = snapshots.load_snapshot(d)
    assert info["metadata"]["resolution"] == [120, 90]
    assert "browser_mode" not in info["metadata"]


def test_reload_and_review_paths(tmp_path):
    img = _image()
    d = snapshots.write_snapshot(img, _scan(img), root=tmp_path)
    info = snapshots.load_snapshot(d)
    assert info["metadata"]["resolution"] == [120, 90]
    assert isinstance(info["labels"], LabelStore)
    frames_dir, labels_path, calibration_path = snapshots.review_paths(d)
    # The frames dir Review Mode reads must contain exactly the one raw frame.
    from pathlib import Path

    pngs = sorted(p.name for p in Path(frames_dir).glob("*.png"))
    assert pngs == ["raw.png"]
    assert Path(labels_path).exists() and Path(calibration_path).exists()


def test_review_roundtrip_only_touches_labels(tmp_path):
    img = _image()
    d = snapshots.write_snapshot(img, _scan(img), root=tmp_path)
    immutable = {rel: _md5(d / rel) for rel in ("frames/raw.png", "annotated.png", "scan.json")}

    # Simulate Review Mode editing labels and saving.
    store = LabelStore.load(d / "labels.json")
    label = store.ensure("raw.png")
    label.badges = [Badge(cx=15, cy=25, pct=60)]
    label.reviewed = True
    store.save()

    # Raw image, annotation and trace are byte-for-byte unchanged.
    assert {rel: _md5(d / rel) for rel in immutable} == immutable
    reloaded = LabelStore.load(d / "labels.json").get("raw.png")
    assert reloaded.reviewed is True
    assert [(b.cx, b.cy, b.pct) for b in reloaded.badges] == [(15, 25, 60)]


def test_import_into_dataset_dedup_and_preserve(tmp_path):
    img = _image()
    world = World(alias="D", hostname="cz2.forgeofempires.com")
    d = snapshots.write_snapshot(img, _scan(img), world=world, root=tmp_path)
    # Give the snapshot a reviewed label to preserve on import.
    store = LabelStore.load(d / "labels.json")
    lab = store.ensure("raw.png")
    lab.badges = [Badge(cx=40, cy=30, pct=20)]
    lab.reviewed = True
    lab.weakening = 5
    store.save()

    dataset = tmp_path / "dataset"
    r1 = snapshots.import_into_dataset(d, dataset)
    assert r1["imported"] is True
    from pathlib import Path

    dest = Path(r1["dest"])
    assert dest.exists() and dest.parent.name == "frames"

    # Label preserved (re-keyed to the destination filename).
    ds_labels = LabelStore.load(dataset / "labels.json").get(dest.name)
    assert ds_labels is not None and ds_labels.reviewed is True
    assert ds_labels.weakening == 5
    assert [(b.cx, b.cy, b.pct) for b in ds_labels.badges] == [(40, 30, 20)]
    # Metadata preserved alongside.
    assert (dataset / "imported_meta" / f"{dest.stem}.json").exists()

    # Re-importing the same image is deduplicated by content hash.
    r2 = snapshots.import_into_dataset(d, dataset)
    assert r2["imported"] is False and "duplicate" in r2["reason"]
    assert len(list((dataset / "frames").glob("*.png"))) == 1


def test_import_distinct_images_are_both_kept(tmp_path):
    d1 = snapshots.write_snapshot(_image(), _scan(_image()), root=tmp_path / "a")
    other = np.full((90, 120, 3), 90, dtype=np.uint8)  # different content
    d2 = snapshots.write_snapshot(other, _scan(other), root=tmp_path / "b")
    dataset = tmp_path / "dataset"
    assert snapshots.import_into_dataset(d1, dataset)["imported"] is True
    assert snapshots.import_into_dataset(d2, dataset)["imported"] is True
    from pathlib import Path

    assert len(list((dataset / "frames").glob("*.png"))) == 2
