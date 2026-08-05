"""Live Data Collection GUI (Milestone 5D): the window wiring and the fast-review
keyboard actions. Uses a temp dataset and a fake capture — no real browser."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent


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
    def __init__(self, worlds):
        self._w = worlds

    def list(self):
        return self._w


def _img(seed):
    return np.random.RandomState(seed).randint(0, 255, (1080, 1920, 3), np.uint8)


def test_collection_window_captures_across_worlds(qapp, dataset_env):
    from bap.gui.forge_collection import ForgeCollectionWindow

    imgs = {"H": _img(1), "F": _img(2)}
    win = ForgeCollectionWindow(
        world_store=_Store([_World("H"), _World("F")]),
        browser_mode="external_chromium",
        capture_fn=lambda w: imgs[w.alias])
    assert set(win._world_checks) == {"H", "F"}

    win._start_session()
    assert win._session is not None
    win._capture(selected_only=False)
    assert win.table.rowCount() == 2                 # one per World
    # duplicate capture adds nothing new
    win._capture(selected_only=False)
    assert win.table.rowCount() == 2
    assert win._session.duplicates_skipped == 2

    # filter to unreviewed keeps both; reviewed shows none
    win.filter_combo.setCurrentIndex(1)  # Unreviewed
    win.refresh()
    assert win.table.rowCount() == 2
    win.filter_combo.setCurrentIndex(2)  # Reviewed
    win.refresh()
    assert win.table.rowCount() == 0
    # stats render without error
    assert "Per class" in win.stats.toPlainText()


# --- fast-review keyboard actions ---------------------------------------------

def _review_win(qapp, dataset_env):
    from bap.forge.collection import session as S
    from bap.forge.collection.capture import capture_frame
    from bap.forge.detection.calibration import WeakeningCalibration
    from bap.forge.dataset_store import dataset_review_paths
    from bap.forge.labeling.session import LabelSession
    from bap.gui.forge_review import ForgeReviewWindow

    s = S.start_session(["H"])
    capture_frame(_img(3), world=_World("H"), session=s)
    capture_frame(_img(4), world=_World("H"), session=s)
    frames_dir, labels_path, calib_path = dataset_review_paths()
    session = LabelSession.open(frames_dir, labels_path)
    win = ForgeReviewWindow(session, frames_dir, WeakeningCalibration.load(calib_path))
    return win, session, frames_dir, labels_path


def _key(win, key, *, ctrl=False):
    mod = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, mod))


def test_key_n_marks_reviewed_negative(qapp, dataset_env):
    win, session, _fd, _lp = _review_win(qapp, dataset_env)
    try:
        session.goto(0)
        _key(win, Qt.Key.Key_N)
        assert session.current().reviewed is True
        assert len(session.current().badges) == 0     # negative
    finally:
        win._dirty = False
        win.close()


def test_key_r_toggles_reviewed(qapp, dataset_env):
    win, session, _fd, _lp = _review_win(qapp, dataset_env)
    try:
        session.goto(0)
        assert session.current().reviewed is False
        _key(win, Qt.Key.Key_R)
        assert session.current().reviewed is True
        _key(win, Qt.Key.Key_R)
        assert session.current().reviewed is False
    finally:
        win._dirty = False
        win.close()


def test_enter_saves_and_advances_and_persists(qapp, dataset_env):
    from bap.forge.labeling.model import LabelStore

    win, session, frames_dir, labels_path = _review_win(qapp, dataset_env)
    try:
        session.goto(0)
        first = session.current_file()
        _key(win, Qt.Key.Key_N)               # make frame 0 a reviewed negative
        _key(win, Qt.Key.Key_Return)          # Save and Next
        assert session.current_file() != first     # advanced
        # persisted: reopening the store restores the reviewed negative
        reopened = LabelStore.load(labels_path)
        assert reopened.get(first).reviewed is True
        assert reopened.get(first).badges == []
    finally:
        win._dirty = False
        win.close()


def test_ctrl_s_saves(qapp, dataset_env):
    from bap.forge.labeling.model import LabelStore

    win, session, _fd, labels_path = _review_win(qapp, dataset_env)
    try:
        session.goto(0)
        name = session.current_file()
        _key(win, Qt.Key.Key_R)               # mark reviewed
        _key(win, Qt.Key.Key_S, ctrl=True)    # Ctrl+S
        assert LabelStore.load(labels_path).get(name).reviewed is True
    finally:
        win._dirty = False
        win.close()
