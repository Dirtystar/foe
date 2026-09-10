import pytest

from bap.forge.labeling.model import LabelStore
from bap.forge.labeling.session import LabelSession

FRAMES = ["f1.png", "f2.png", "f3.png"]


def _session(tmp_path):
    return LabelSession(FRAMES, LabelStore(tmp_path / "labels.json"))


def test_add_badge_uses_armed_pct_and_autosaves(tmp_path):
    s = _session(tmp_path)
    s.arm_pct(60)
    b = s.add_badge(800, 430)
    assert (b.cx, b.cy, b.pct) == (800, 430, 60)
    # autosaved: a fresh load sees it
    reloaded = LabelStore.load(tmp_path / "labels.json")
    assert reloaded.get("f1.png").badges[0].pct == 60


def test_click_then_key_sets_active_badge_pct(tmp_path):
    s = _session(tmp_path)
    s.add_badge(100, 100)  # no armed pct yet -> None, becomes active
    assert s.badges()[0].pct is None
    s.arm_pct(40)  # applies to the active badge
    assert s.badges()[0].pct == 40


def test_multiple_badges_per_frame(tmp_path):
    s = _session(tmp_path)
    s.arm_pct(20)
    s.add_badge(10, 10)
    s.add_badge(20, 20)
    s.add_badge(30, 30)
    assert len(s.badges()) == 3


def test_select_and_remove_nearest(tmp_path):
    s = _session(tmp_path)
    s.arm_pct(20)
    s.add_badge(100, 100)
    s.add_badge(500, 500)
    assert s.select_nearest(105, 98, radius=20) == 0
    assert s.remove_nearest(498, 503, radius=20) is True
    assert [(b.cx, b.cy) for b in s.badges()] == [(100, 100)]


def test_select_nearest_out_of_radius_returns_none(tmp_path):
    s = _session(tmp_path)
    s.add_badge(100, 100)
    assert s.select_nearest(400, 400, radius=20) is None


def test_negative_frame_reviewed_with_no_badges(tmp_path):
    s = _session(tmp_path)
    s.set_reviewed(True)
    assert s.current().reviewed and s.badges() == []


def test_resume_starts_at_first_unreviewed(tmp_path):
    store = LabelStore(tmp_path / "labels.json")
    store.ensure("f1.png").reviewed = True
    store.save()
    s = LabelSession(FRAMES, store)
    assert s.current_file() == "f2.png"  # f1 already reviewed


def test_navigation_clamps(tmp_path):
    s = _session(tmp_path)
    s.prev()
    assert s.index == 0
    s.goto(99)
    assert s.index == s.total - 1


def test_accept_suggestions_dedupes(tmp_path):
    s = _session(tmp_path)
    s.arm_pct(20)
    s.add_badge(100, 100)
    added = s.accept_suggestions([(105, 102), (900, 700)])  # first ~ existing
    assert added == 1
    assert len(s.badges()) == 2
    # accepted suggestion has no pct yet
    assert any(b.pct is None for b in s.badges())


def test_unclassified_count(tmp_path):
    s = _session(tmp_path)
    s.arm_pct(20)
    s.add_badge(1, 1)
    s.arm_pct(None)
    s.add_badge(2, 2)  # armed None -> unclassified
    assert s.unclassified() == 1


def test_arm_pct_rejects_invalid(tmp_path):
    s = _session(tmp_path)
    with pytest.raises(ValueError):
        s.arm_pct(33)


def test_empty_frames_rejected(tmp_path):
    with pytest.raises(ValueError):
        LabelSession([], LabelStore(tmp_path / "l.json"))
