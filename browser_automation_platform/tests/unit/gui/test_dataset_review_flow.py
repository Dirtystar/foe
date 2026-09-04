"""The unified Dataset / Snapshot / Review workflow (Milestone 4.15) — offscreen.

Proves the core guarantee: there is exactly one editable Reviewed Dataset, and
every Review entry point edits *that exact* dataset. Reviewing a snapshot imports
it into the canonical dataset and reviews the imported copy — the snapshot island
is never the review target.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
cv2 = pytest.importorskip("cv2")

from PySide6.QtWidgets import QWidget

from bap.forge import dataset_store, snapshots
from bap.forge.detection.scan import build_scan


@pytest.fixture
def canonical(tmp_path, monkeypatch):
    monkeypatch.setenv("BAP_DATASET_DIR", str(tmp_path / "dataset"))
    return tmp_path / "dataset"


def _snapshot(tmp_path, v=30):
    img = np.full((200, 300, 3), v, np.uint8)
    scan = build_scan(img)
    return snapshots.write_snapshot(img, scan, root=tmp_path / "snaproot"), img


def test_reviewing_a_snapshot_edits_the_canonical_dataset(qapp, tmp_path, canonical):
    from bap.gui.snapshot_actions import open_snapshot_in_review

    snap, _ = _snapshot(tmp_path)
    parent = QWidget()
    try:
        open_snapshot_in_review(parent, snap)
        # The snapshot was imported into THE canonical dataset...
        frames = list((canonical / "frames").glob("*.png"))
        assert len(frames) == 1
        # ...and Review Mode opened on that exact dataset (its labels.json).
        win = parent._dataset_review_window
        assert str(canonical / "labels.json") in win.labels_path_lbl.text()
        # The session is positioned on the imported frame.
        assert win._session.current_file() == frames[0].name
    finally:
        w = getattr(parent, "_dataset_review_window", None)
        if w is not None:
            w._dirty = False
            w.close()
        parent.deleteLater()


def test_import_dialog_targets_the_one_dataset_without_a_picker(qapp, tmp_path, canonical, monkeypatch):
    # import_snapshot_dialog must not open a directory picker — there is only one
    # dataset, so the destination is never ambiguous.
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from bap.gui.snapshot_actions import import_snapshot_dialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: pytest.fail("no picker: one dataset only")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    snap, _ = _snapshot(tmp_path)
    parent = QWidget()
    try:
        import_snapshot_dialog(parent, snap)
        assert len(list((canonical / "frames").glob("*.png"))) == 1
    finally:
        parent.deleteLater()


def test_open_dataset_in_review_reports_empty_when_nothing_captured(qapp, canonical, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from bap.gui.snapshot_actions import open_dataset_in_review

    seen = {}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: seen.setdefault("info", a)))
    parent = QWidget()
    try:
        opened = open_dataset_in_review(parent)
        assert opened is False               # empty dataset -> no window, a clear message
        assert "info" in seen
        assert getattr(parent, "_dataset_review_window", None) is None
    finally:
        parent.deleteLater()
