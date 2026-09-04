"""Async Capture-All pipeline core (Milestone 5D P0) — Qt-free behaviour + safety.

Fake captures + a deliberately slow fake analyzer prove sequencing, cancellation,
error containment, timeouts, bounded concurrency, and session recovery without any
browser, Qt, or real detector.
"""

from __future__ import annotations

import threading
import time

import pytest

np = pytest.importorskip("numpy")


@pytest.fixture()
def dataset_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BAP_DATASET_DIR", str(tmp_path))
    return tmp_path


def _worlds(n):
    return [(f"W{i}", object()) for i in range(n)]


class _Res:
    def __init__(self, is_new=True):
        self.frame = "f.png"
        self.is_new = is_new
        self.detected = 3
        self.classified = 1
        self.unknown = 2


def _ok_capture(w):
    return np.zeros((8, 8, 3), np.uint8), None


def _fast_analyze(image, *, world=None, session=None, dataset_dir=None):
    return _Res()


def test_progress_emits_per_world_in_order():
    from bap.forge.collection.capture_job import CaptureJob, Stage

    events = []
    job = CaptureJob(_worlds(4), capture_fn=_ok_capture, analyze_fn=_fast_analyze)
    summary = job.run(on_progress=lambda p: events.append((p.alias, p.stage)))
    # each World: CAPTURING → ANALYSING → COMPLETED, in World order
    aliases = [a for a, s in events if s is Stage.CAPTURING]
    assert aliases == ["W0", "W1", "W2", "W3"]
    assert summary.completed == 4 and summary.failed == 0
    assert [a for a, s in events if s is Stage.COMPLETED] == ["W0", "W1", "W2", "W3"]


def test_capture_is_sequential_never_concurrent():
    from bap.forge.collection.capture_job import CaptureJob

    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def cap(w):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.01)
        with lock:
            active["n"] -= 1
        return np.zeros((8, 8, 3), np.uint8), None

    CaptureJob(_worlds(5), capture_fn=cap, analyze_fn=_fast_analyze).run()
    assert active["max"] == 1   # concurrency bound of 1 — never overlaps


def test_cancel_stops_future_worlds_and_preserves_completed(dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture_job import CaptureJob, Stage

    sess = S.start_session([a for a, _ in _worlds(6)])
    job = None
    seen = []

    def cap(w):
        seen.append(w)
        if len(seen) == 2:
            job.cancel()          # cancel mid-batch
        return np.zeros((8, 8, 3), np.uint8), None

    job = CaptureJob(_worlds(6), capture_fn=cap, analyze_fn=_fast_analyze, session=sess)
    summary = job.run()
    assert summary.was_cancelled
    assert summary.completed == 2 and summary.cancelled == 4   # 2 kept, 4 not started
    assert "2 result(s) preserved" in summary.message()
    # session recovery: the 4 unfinished Worlds are resumable
    assert len(sess.unfinished_worlds()) == 4


def test_one_world_failure_does_not_abort_batch():
    from bap.forge.collection.capture_job import CaptureJob

    def cap(w):
        return (None, "tab closed") if w[0] == "W2" else (np.zeros((8, 8, 3), np.uint8), None)
    # capture_fn gets the world object, not the tuple; fail on the 3rd call instead
    calls = {"n": 0}

    def cap2(w):
        calls["n"] += 1
        if calls["n"] == 3:
            return None, "browser detached"
        return np.zeros((8, 8, 3), np.uint8), None

    summary = CaptureJob(_worlds(5), capture_fn=cap2, analyze_fn=_fast_analyze).run()
    assert summary.completed == 4 and summary.failed == 1
    failed = [r for r in summary.results if r.stage.value == "failed"][0]
    assert failed.error["stage"] == "capture" and "detached" in failed.error["reason"]


def test_analyze_exception_is_contained():
    from bap.forge.collection.capture_job import CaptureJob

    calls = {"n": 0}

    def analyze(image, *, world=None, session=None, dataset_dir=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("boom")
        return _Res()

    summary = CaptureJob(_worlds(3), capture_fn=_ok_capture, analyze_fn=analyze).run()
    assert summary.completed == 2 and summary.failed == 1
    failed = [r for r in summary.results if r.stage.value == "failed"][0]
    assert failed.error["stage"] == "analyze" and "ValueError" in failed.error["reason"]


def test_capture_timeout_is_reported():
    from bap.forge.collection.capture_job import CaptureJob

    def cap(w):
        raise TimeoutError("capture exceeded 20s")

    summary = CaptureJob(_worlds(2), capture_fn=cap, analyze_fn=_fast_analyze).run()
    assert summary.failed == 2
    err = summary.results[0].error
    assert err["type"] == "timeout" and "20s" in err["reason"]


def test_cv2_threads_are_bounded(monkeypatch):
    from bap.forge.collection.capture_job import CaptureJob
    import cv2

    seen = []
    monkeypatch.setattr(cv2, "setNumThreads", lambda n: seen.append(n))
    CaptureJob(_worlds(1), capture_fn=_ok_capture, analyze_fn=_fast_analyze,
               cv2_threads=1).run()
    assert seen and seen[0] == 1   # OpenCV thread count is capped, not left unbounded


def test_default_analyze_matches_capture_frame(dataset_env):
    # The async job's default analyze must produce the SAME dataset result as the
    # synchronous capture_frame (identical detector/classifier outputs).
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.collection.capture_job import CaptureJob

    img = np.random.RandomState(0).randint(0, 255, (1080, 1920, 3), np.uint8)

    class _W:
        alias = "H"
        hostname = "cz8.forgeofempires.com"
        last_url = ""

    # baseline: synchronous capture_frame in a fresh dataset
    s1 = S.start_session(["H"], session_id="sync")
    sync = capture_frame(img.copy(), world=_W(), session=s1)

    # same image again is a duplicate → identical dedup behaviour proves parity
    s2 = S.start_session(["H"], session_id="async")
    summary = CaptureJob([("H", _W())], capture_fn=lambda w: (img.copy(), None),
                         session=s2).run()
    r = summary.results[0]
    assert r.stage.value == "skipped"          # same bytes → deduped, like sync path
    assert r.frame == sync.frame
    assert r.detected == sync.detected and r.classified == sync.classified
