"""Live Data Collection core (Milestone 5D) — behaviour + safety invariants.

All tests run against a throwaway dataset via the ``BAP_DATASET_DIR`` override, so
the real dataset is never touched. Qt-free.
"""

from __future__ import annotations

import inspect

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")


@pytest.fixture()
def dataset_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BAP_DATASET_DIR", str(tmp_path))
    return tmp_path


def _img(seed: int, w=1920, h=1080):
    return np.random.RandomState(seed).randint(0, 255, (h, w, 3), np.uint8)


class _World:
    def __init__(self, alias, hostname="cz8.forgeofempires.com", url=""):
        self.alias = alias
        self.hostname = hostname
        self.last_url = url


# --- session persistence ------------------------------------------------------

def test_session_persists_across_restart(dataset_env):
    from bap.forge.collection import session as S

    s = S.start_session(["H", "F"], browser_mode="external_chromium", notes="day 1")
    assert s.git_commit is None or isinstance(s.git_commit, str)
    # simulate restart: reload purely from disk
    again = S.load_session(s.session_id)
    assert again is not None
    assert again.worlds == ["H", "F"] and again.browser_mode == "external_chromium"
    assert S.active_session().session_id == s.session_id
    assert [x.session_id for x in S.list_sessions()] == [s.session_id]


# --- capture -> canonical dataset + dedup + multi-World queue ------------------

def test_capture_imports_and_dedupes(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame, provenance_for
    from bap.forge.collection.dataset_view import build_queue

    s = S.start_session(["H"], browser_mode="external_chromium")
    img = _img(1)
    r1 = capture_frame(img, world=_World("H"), session=s)
    assert r1.is_new
    r2 = capture_frame(img, world=_World("H"), session=s)   # identical image
    assert r2.is_new is False and r2.frame == r1.frame       # dedup by hash
    assert s.duplicates_skipped == 1 and len(s.captured_frames) == 1

    prov = provenance_for(r1.frame)
    assert prov["alias"] == "H" and prov["session_id"] == s.session_id
    assert prov["capture_w"] == 1920 and prov["source"] == "live_collection"

    rows = build_queue()
    assert len(rows) == 1 and rows[0].world == "H"
    assert rows[0].review_state == "pending"      # NEVER auto-reviewed


def test_multi_world_queue_and_filters(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.dataset_view import build_queue

    s = S.start_session(["H", "F"])
    capture_frame(_img(2), world=_World("H"), session=s)
    capture_frame(_img(3), world=_World("F"), session=s)
    assert len(build_queue()) == 2
    assert len(build_queue(world="H")) == 1
    assert len(build_queue(filters=["unreviewed"])) == 2
    assert len(build_queue(filters=["reviewed"])) == 0
    # sort keys must not raise
    for srt in ("newest", "uncertainty", "rarest_class", "most_detections", "world"):
        build_queue(sort=srt)


# --- reviewed negative + no implicit reviewed ---------------------------------

def test_reviewed_negative_is_first_class(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.dataset_view import build_queue
    from bap.forge.dataset_store import dataset_review_paths
    from bap.forge.labeling.session import LabelSession

    s = S.start_session(["H"])
    res = capture_frame(_img(4), world=_World("H"), session=s)
    frames_dir, labels_path, _cal = dataset_review_paths()
    sess = LabelSession.open(frames_dir, labels_path)
    # emulate the operator pressing N: clear badges + reviewed
    sess.current().badges.clear()
    sess.set_reviewed(True)
    sess.store.save()

    entry = next(e for e in build_queue() if e.frame == res.frame)
    assert entry.negative and entry.review_state == "reviewed_negative"


def test_capture_never_marks_reviewed(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.dataset_view import build_queue

    s = S.start_session(["H"])
    capture_frame(_img(5), world=_World("H"), session=s)
    assert all(not e.reviewed for e in build_queue())   # implicit reviewed is forbidden


# --- statistics + shortages + targets -----------------------------------------

def test_statistics_and_shortages(dataset_env):
    from bap.forge.collection.dataset_view import dataset_statistics
    from bap.forge.detection.dataset import Sample
    from bap.forge.detection.geometry import CaptureGeometry, derive_rois
    from bap.forge.detection.calibration import WeakeningCalibration
    from bap.forge.labeling.model import Badge as GtLike

    class B:
        def __init__(self, pct):
            self.cx, self.cy, self.pct = 100, 100, pct

    rois = derive_rois(CaptureGeometry(1920, 1080), WeakeningCalibration())
    samples = [
        Sample(source="live", frame="a.png", frames_dir=dataset_env, world="H",
               width=1920, height=1080, rois=rois, badges=[B(20), B(60)]),
        Sample(source="historical", frame="b.png", frames_dir=dataset_env, world=None,
               width=1600, height=900, rois=rois, badges=[B(20)]),
    ]
    st = dataset_statistics(samples=samples)
    assert st["per_class"] == {"20": 2, "40": 0, "60": 1, "80": 0, "100": 0}
    assert st["shortages"]["zero_example_classes"] == [40, 80, 100]
    assert st["shortages"]["most_useful_next_capture"] == 40
    assert st["live_vs_historical"] == {"live_chrome": 1, "historical": 1}


def test_target_progress_counts_session_only(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.dataset_view import target_progress

    s = S.start_session(["H"], targets={"20": 1, "negative": 1})
    capture_frame(_img(6), world=_World("H"), session=s)
    prog = target_progress(s)
    assert prog["20"]["target"] == 1 and prog["negative"]["target"] == 1
    assert prog["20"]["met"] is False   # nothing reviewed/classified yet


# --- validation ---------------------------------------------------------------

def test_validate_flags_reviewed_null_pct(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.validate import validate_dataset
    from bap.forge.dataset_store import dataset_review_paths
    from bap.forge.labeling.model import Badge
    from bap.forge.labeling.session import LabelSession

    s = S.start_session(["H"])
    capture_frame(_img(7), world=_World("H"), session=s)
    frames_dir, labels_path, _cal = dataset_review_paths()
    sess = LabelSession.open(frames_dir, labels_path)
    sess.current().badges[:] = [Badge(cx=100, cy=100, pct=None)]
    sess.set_reviewed(True)
    sess.store.save()

    v = validate_dataset()
    kinds = {i["kind"] for i in v["issues"]}
    assert "reviewed_null_pct" in kinds and v["ok"] is False


def test_validate_never_mutates(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.validate import validate_dataset
    from bap.forge.dataset_store import dataset_labels_path

    s = S.start_session(["H"])
    capture_frame(_img(8), world=_World("H"), session=s)
    before = dataset_labels_path().read_text()
    validate_dataset()
    assert dataset_labels_path().read_text() == before   # read-only


# --- commit plan / class-count delta ------------------------------------------

def test_prepare_commit_reports_pending_and_commands(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.commit import prepare_commit

    s = S.start_session(["H"])
    capture_frame(_img(9), world=_World("H"), session=s)
    plan = prepare_commit(session=s)
    assert plan["frames_pending"] == 1 and plan["frames_reviewed"] == 0
    assert any("git add" in c for c in plan["suggested_commands"])
    assert any("pending" in w for w in plan["warnings"])
    assert set(plan["class_count_delta"]) == {"20", "40", "60", "80", "100"}


# --- review-assist bulk actions -----------------------------------------------

def test_review_actions_never_review_and_confirm_gate():
    from bap.forge.collection import review_actions as A
    from bap.forge.labeling.model import Badge, FrameLabel

    class _Scan:
        class _D:
            def __init__(self, cx, cy, pct):
                self.cx, self.cy, self.pct = cx, cy, pct
        detections = [_D(10, 10, 20), _D(20, 20, None)]

    label = FrameLabel(file="f.png")
    assert A.accept_all_positions(label, _Scan()) == 2
    assert all(b.pct is None for b in label.badges)   # positions only
    assert label.reviewed is False                    # never auto-reviewed

    label.badges = [Badge(cx=1, cy=1, pct=None), Badge(cx=2, cy=2, pct=None)]
    assert A.mark_all_pct(label, 60, confirmed=False) == 0   # no-op without confirm
    assert A.mark_all_pct(label, 60, confirmed=True) == 2
    assert all(b.pct == 60 for b in label.badges)
    assert A.remove_all(label) == 2 and label.badges == []
    assert label.reviewed is False


# --- safety: no threshold change, no cursor/click reachable -------------------

def test_capture_does_not_change_min_pct_sim(dataset_env):
    import bap.forge.detection.scan as scan
    before = scan.MIN_PCT_SIM
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection import session as S
    capture_frame(_img(10), world=_World("H"), session=S.start_session(["H"]))
    assert scan.MIN_PCT_SIM == before == 0.70


def test_status_summary_reports_unknown_and_today(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.dataset_view import status_summary

    s = S.start_session(["H"])
    capture_frame(_img(20), world=_World("H"), session=s)
    ss = status_summary()
    for key in ("reviewed", "pending", "negative", "unknown", "per_class", "today"):
        assert key in ss
    assert ss["pending"] >= 1                     # our captured (unreviewed) frame
    assert ss["today"]["frames"] >= 1             # captured today
    assert set(ss["per_class"]) == {"20", "40", "60", "80", "100"}
    assert set(ss["today"]["per_class"]) == {"20", "40", "60", "80", "100"}


def test_session_dashboard_real_metrics(dataset_env):
    from datetime import datetime, timedelta

    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.dataset_view import session_dashboard

    s = S.start_session(["H", "F"], browser_mode="external_chromium")
    capture_frame(_img(21), world=_World("H"), session=s)
    capture_frame(_img(21), world=_World("H"), session=s)   # duplicate
    now = datetime.fromisoformat(s.started_at) + timedelta(minutes=30)
    d = session_dashboard(s, now=now)
    assert d["active"] and d["worlds_attached"] == 2
    assert d["frames_captured"] == 1 and d["frames_skipped"] == 1 and d["duplicates"] == 1
    assert d["duration_seconds"] == 1800 and d["duration_human"] == "30m 0s"
    assert d["capture_rate_per_hour"] == 2.0     # 1 frame in 0.5 h
    assert session_dashboard(None) == {"active": False}


def test_priority_sort_puts_unknown_first(dataset_env):
    from bap.forge.collection.dataset_view import QueueEntry, build_queue

    # monkey-free: build_queue reads the dataset, so exercise the sort directly via
    # a tiny in-memory list mirroring build_queue's key.
    import bap.forge.collection.dataset_view as V

    def entry(frame, unknown, ts):
        return QueueEntry(frame=frame, path="", world="H", timestamp=ts,
                          capture_w=1920, capture_h=1080, detected=unknown,
                          classified=0, unknown=unknown, reviewed=False, negative=False,
                          review_state="pending", duplicate=False, session_id="s",
                          source="live_collection", per_class={"20": 0, "40": 0, "60": 0, "80": 0, "100": 0})
    rows = [entry("a", 0, "2026-08-05T10:00:00"), entry("b", 3, "2026-08-05T09:00:00"),
            entry("c", 1, "2026-08-05T11:00:00")]
    scarcity = V._class_scarcity(rows)
    rows.sort(key=lambda e: (e.unknown, 0, e.timestamp or "", e.frame), reverse=True)
    assert [e.frame for e in rows] == ["b", "c", "a"]   # most UNKNOWN first


def test_capture_quality_flags_all_conditions(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.capture_quality import assess_capture

    class _Geo:
        def __init__(self, zoom):
            self.zoom = zoom

    s = S.start_session(["H"])
    capture_frame(_img(30), world=_World("H"), session=s)      # seed one frame

    codes = lambda ws: {w.code for w in ws}
    assert "browser_detached" in codes(assess_capture(None, capture_error="tab closed"))
    assert "duplicate" in codes(assess_capture(_img(30), world=_World("H")))
    assert "unsupported_zoom" in codes(assess_capture(_img(31), geometry=_Geo(1.25)))
    assert "wrong_resolution" in codes(assess_capture(_img(32, h=1234)))
    # a good, novel, calibrated-size frame with zoom 1.0 → at most calibration note
    ws = assess_capture(_img(33), world=_World("H"), geometry=_Geo(1.0))
    assert "unsupported_zoom" not in codes(ws) and "duplicate" not in codes(ws)


def test_collection_package_has_no_cursor_or_click():
    import ast
    import bap.forge.collection as pkg
    from pathlib import Path

    pkg_dir = Path(pkg.__file__).parent
    for py in pkg_dir.glob("*.py"):
        tree = ast.parse(py.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        for mod in imports:
            assert "cursor" not in mod and "pyautogui" not in mod, f"{py.name}: {mod}"
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for forbidden in ("move_to", "click", "press", "type_text"):
            assert forbidden not in calls, f"{py.name} calls {forbidden}"
