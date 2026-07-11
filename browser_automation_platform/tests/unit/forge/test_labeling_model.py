import json

import pytest

from bap.forge.labeling.model import Badge, FrameLabel, LabelError, LabelStore


def test_badge_validates_pct():
    assert Badge(10, 20).pct is None
    assert Badge(10, 20, 60).pct == 60
    with pytest.raises(LabelError):
        Badge(1, 1, 33)


def test_badge_coerces_coords_to_int():
    b = Badge(10.7, 20.2, 40)
    assert (b.cx, b.cy) == (10, 20)


def test_frame_fully_classified():
    f = FrameLabel("a.png", [Badge(1, 1, 20)], reviewed=True)
    assert f.fully_classified
    f2 = FrameLabel("b.png", [Badge(1, 1, None)], reviewed=True)
    assert not f2.fully_classified  # a dangling None
    f3 = FrameLabel("c.png", [Badge(1, 1, 20)], reviewed=False)
    assert not f3.fully_classified  # not reviewed


def test_ensure_creates_and_reuses():
    store = LabelStore()
    a = store.ensure("f.png")
    a.badges.append(Badge(1, 1, 20))
    assert store.ensure("f.png") is a  # same object, edits preserved


def test_ensure_all_preserves_order_and_existing():
    store = LabelStore()
    store.ensure("b.png").reviewed = True
    store.ensure_all(["a.png", "b.png", "c.png"])
    assert store.files() == ["b.png", "a.png", "c.png"]  # b first (pre-existing)
    assert store.get("b.png").reviewed is True


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "labels.json"
    store = LabelStore(path)
    f = store.ensure("frame.png")
    f.badges.extend([Badge(100, 200, 20), Badge(300, 400, 100)])
    f.reviewed = True
    store.save()

    reloaded = LabelStore.load(path)
    fr = reloaded.get("frame.png")
    assert fr.reviewed is True
    assert [(b.cx, b.cy, b.pct) for b in fr.badges] == [(100, 200, 20), (300, 400, 100)]


def test_save_is_atomic_no_temp_left(tmp_path):
    path = tmp_path / "labels.json"
    store = LabelStore(path)
    store.ensure("f.png")
    store.save()
    assert not path.with_suffix(".json.tmp").exists()


def test_load_missing_is_empty_bound(tmp_path):
    store = LabelStore.load(tmp_path / "nope.json")
    assert len(store) == 0 and store.path is not None


def test_load_skips_corrupt_records(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"version": 1, "frames": [
        {"file": "good.png", "badges": [{"cx": 1, "cy": 2, "pct": 20}], "reviewed": True},
        {"file": "bad.png", "badges": [{"cx": 1, "cy": 2, "pct": 33}]},  # invalid pct
    ]}), encoding="utf-8")
    store = LabelStore.load(path)
    assert store.files() == ["good.png"]


def test_reviewed_count(tmp_path):
    store = LabelStore()
    store.ensure("a.png").reviewed = True
    store.ensure("b.png")
    assert store.reviewed_count() == 1
