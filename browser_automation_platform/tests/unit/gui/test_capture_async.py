"""Async Capture-All GUI wiring (Milestone 5D P0): the window must return control
to the Qt event loop immediately and stay responsive while a batch runs off-thread.
Uses a fake capture + a deliberately slow fake analyzer (no browser, no detector).
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")

from PySide6.QtCore import QElapsedTimer, QTimer


@pytest.fixture()
def dataset_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BAP_DATASET_DIR", str(tmp_path))
    return tmp_path


class _World:
    def __init__(self, alias):
        self.alias = alias
        self.hostname = "cz8.forgeofempires.com"
        self.last_url = ""


class _Store:
    def __init__(self, w):
        self._w = w

    def list(self):
        return self._w


class _Res:
    def __init__(self):
        self.frame = "f.png"
        self.is_new = True
        self.detected = 3
        self.classified = 1
        self.unknown = 2


def _img(s):
    return np.random.RandomState(s).randint(0, 255, (1080, 1920, 3), np.uint8)


def _slow_analyze(image, *, world=None, session=None, dataset_dir=None):
    time.sleep(0.25)   # simulate CPU work; sleep releases the GIL like cv2 does
    return _Res()


def _win(qapp, worlds, **kw):
    from bap.gui.forge_collection import ForgeCollectionWindow
    return ForgeCollectionWindow(world_store=_Store([_World(a) for a in worlds]),
                                 capture_fn=lambda w: (_img(1), None) if False else _img(1),
                                 **kw)


def _drain(qapp, win, timeout_s=30):
    end = time.time() + timeout_s
    while win._job_running and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()


def test_capture_all_returns_immediately_and_runs_off_thread(qapp, dataset_env):
    win = _win(qapp, ["H", "F", "D"], analyze_fn=_slow_analyze)
    win._start_session()
    t = time.perf_counter()
    win._capture(selected_only=False)
    elapsed_ms = (time.perf_counter() - t) * 1000
    assert win._job_running                     # a background batch is running
    assert elapsed_ms < 100                     # control returned to the caller at once
    _drain(qapp, win)
    assert not win._job_running                 # cleaned up when done


def test_event_loop_keeps_ticking_during_capture(qapp, dataset_env):
    win = _win(qapp, ["H", "F", "D", "B"], analyze_fn=_slow_analyze)
    win._start_session()
    gaps = []
    el = QElapsedTimer(); el.start(); last = [0]
    timer = QTimer(); timer.setInterval(10)
    timer.timeout.connect(lambda: (gaps.append(el.elapsed() - last[0]),
                                    last.__setitem__(0, el.elapsed())))
    timer.start()
    win._capture(selected_only=False)
    _drain(qapp, win)
    timer.stop()
    real = gaps[3:]
    # the GUI thread never stalls: no tick gap anywhere near a blocked window
    assert max(real) < 400, f"event loop stalled {max(real)}ms"


def test_repeated_capture_all_cannot_overlap(qapp, dataset_env):
    win = _win(qapp, ["H", "F"], analyze_fn=_slow_analyze)
    win._start_session()
    win._capture(selected_only=False)
    first_thread = win._job_thread
    win._capture(selected_only=False)           # second click while running
    assert win._job_thread is first_thread      # no second overlapping job
    assert "already running" in win.log.toPlainText()
    _drain(qapp, win)


def test_cancel_stops_future_worlds(qapp, dataset_env):
    win = _win(qapp, ["H", "F", "D", "B", "G"], analyze_fn=_slow_analyze)
    win._start_session()
    win._capture(selected_only=False)
    qapp.processEvents()
    time.sleep(0.3)
    win._cancel_capture()                        # cooperative cancel
    _drain(qapp, win)
    assert not win._job_running
    assert win._session.batch["cancelled"] is True
    assert len(win._session.unfinished_worlds()) >= 1   # some Worlds were spared


def test_close_during_capture_honours_choice(qapp, dataset_env):
    win = _win(qapp, ["H", "F", "D"], analyze_fn=_slow_analyze)
    win._start_session()
    win._capture(selected_only=False)

    from PySide6.QtGui import QCloseEvent
    win._prompt_running_close = lambda: "stay"    # choose "Stay open"
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert not ev.isAccepted()                    # close was blocked

    win._prompt_running_close = lambda: "cancel"  # choose "Cancel and close"
    ev2 = QCloseEvent()
    win.closeEvent(ev2)
    assert win._job is None or win._job.cancelled
    _drain(qapp, win)


def test_worker_touches_no_gui_object(qapp, dataset_env):
    from bap.gui.forge_collection import _CaptureWorker
    from bap.forge.collection.capture_job import CaptureJob

    job = CaptureJob([("H", _World("H"))], capture_fn=lambda w: (_img(1), None),
                     analyze_fn=_slow_analyze)
    worker = _CaptureWorker(job)
    from PySide6.QtWidgets import QWidget
    # the worker references the job only — never a widget/window
    assert worker._job is job
    widget_refs = [k for k, v in vars(worker).items() if isinstance(v, QWidget)]
    assert not widget_refs, f"worker must not hold GUI widget refs: {widget_refs}"


def test_session_recovery_resumes_only_unfinished(qapp, dataset_env):
    win = _win(qapp, ["H", "F", "D", "B"], analyze_fn=_slow_analyze)
    win._start_session()
    win._capture(selected_only=False)
    qapp.processEvents()
    time.sleep(0.3)
    win._cancel_capture()
    _drain(qapp, win)
    unfinished = list(win._session.unfinished_worlds())
    assert unfinished
    # Resume only captures the unfinished Worlds.
    win._resume_unfinished()
    assert win._job_running
    _drain(qapp, win)
    assert win._session.unfinished_worlds() == []   # all done after resume
