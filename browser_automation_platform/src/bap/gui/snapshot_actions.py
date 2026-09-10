"""Shared GUI actions for the unified Dataset / Snapshot / Review workflow
(Milestone 4.15) — observe-only.

There is exactly **one** editable Reviewed Dataset (``dataset_store``), and every
"open Review from the UI" action edits *that exact* dataset. Snapshots are
immutable archives: to review one you import it into the canonical dataset and
review the imported copy — never the snapshot island. These functions only write
files and open the existing Review Mode; nothing here clicks, moves the cursor,
or types.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from bap.forge import dataset_store, snapshots


def open_dataset_in_review(parent, world=None, *, select_frame: str | None = None) -> bool:
    """Open THE canonical Reviewed Dataset in Review Mode (creating it if empty).

    This is the single Review entry point: everything the UI opens for review
    comes from ``dataset_store.dataset_review_paths()``, so edits always land in
    the one obvious place. When ``select_frame`` is given the session navigates to
    that frame. Returns True on success. Non-blocking; the window is parented so it
    stays alive."""
    from bap.forge.detection.calibration import WeakeningCalibration
    from bap.forge.detection.detector import BadgeDetector
    from bap.forge.labeling.session import LabelSession
    from bap.gui.forge_review import ForgeReviewWindow

    frames_dir, labels_path, calibration_path = dataset_store.dataset_review_paths(create=True)
    if not sorted(Path(frames_dir).glob("*.png")):
        QMessageBox.information(
            parent, "Reviewed Dataset",
            "The Reviewed Dataset is empty.\n\nCapture a scan and use "
            "“Label in Review Mode”, or import a snapshot, to add frames.")
        return False
    try:
        session = LabelSession.open(frames_dir, labels_path)
        if select_frame is not None:
            for i in range(session.total):
                session.goto(i)
                if session.current_file() == select_frame:
                    break
        cal = WeakeningCalibration.load(calibration_path)
        win = ForgeReviewWindow(session, frames_dir, cal, world=world, detector=BadgeDetector())
        win.resize(1360, 800)
        win.show()
        parent._dataset_review_window = win  # keep a reference alive
        return True
    except Exception as exc:  # never crash the caller over a review launch
        QMessageBox.warning(parent, "Open Dataset in Review",
                            f"Could not open the Reviewed Dataset in Review Mode:\n{exc}")
        return False


def open_snapshot_in_review(parent, snapshot_dir, world=None) -> None:
    """Review a snapshot by importing it into the canonical dataset and opening the
    imported copy — so the review edits the one Reviewed Dataset, not the immutable
    snapshot. Deduplicates by image hash, so re-reviewing an already-imported
    snapshot simply reopens its dataset frame."""
    try:
        result = snapshots.import_into_dataset(snapshot_dir)  # -> canonical dataset
    except Exception as exc:
        QMessageBox.warning(parent, "Open Snapshot in Review",
                            f"Could not import the snapshot into the dataset:\n{exc}")
        return
    dest = result.get("dest")
    frame_name = Path(dest).name if dest else None
    open_dataset_in_review(parent, world=world, select_frame=frame_name)


def import_snapshot_dialog(parent, snapshot_dir) -> None:
    """Import a snapshot into THE canonical Reviewed Dataset (dedup by hash). No
    directory picker — there is only one dataset, so the destination is never
    ambiguous."""
    try:
        result = snapshots.import_into_dataset(snapshot_dir)
    except Exception as exc:
        QMessageBox.warning(parent, "Import Snapshot", f"Could not import:\n{exc}")
        return
    where = dataset_store.reviewed_dataset_dir()
    if result["imported"]:
        QMessageBox.information(
            parent, "Import Snapshot",
            f"Imported into the Reviewed Dataset as:\n{Path(result['dest']).name}\n\n{where}")
    else:
        QMessageBox.information(
            parent, "Import Snapshot",
            f"Not imported: {result['reason']}."
            + (f"\nExisting: {Path(result['dest']).name}" if result.get("dest") else ""))


def save_snapshot_and_offer(parent, *, image, scan, world=None, classifier=None,
                            detector=None, validation_markdown=None, url=None) -> Path | None:
    """Write a snapshot and offer Open-in-Review / Import as follow-up actions.
    Returns the snapshot path (or None on failure)."""
    try:
        snapshot_dir = snapshots.write_snapshot(
            image, scan, world=world, classifier=classifier, detector=detector,
            validation_markdown=validation_markdown, url=url,
        )
    except Exception as exc:
        QMessageBox.warning(parent, "Save Snapshot", f"Could not save snapshot:\n{exc}")
        return None

    box = QMessageBox(parent)
    box.setWindowTitle("Snapshot saved")
    box.setText(f"Snapshot saved to:\n{snapshot_dir}")
    box.setInformativeText("It is a permanent, reproducible archive. What next?")
    review_btn = box.addButton("Import + Review", QMessageBox.ButtonRole.AcceptRole)
    import_btn = box.addButton("Import into Dataset", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Done", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is review_btn:
        open_snapshot_in_review(parent, snapshot_dir, world=world)
    elif clicked is import_btn:
        import_snapshot_dialog(parent, snapshot_dir)
    return snapshot_dir


__all__ = ["save_snapshot_and_offer", "open_dataset_in_review",
           "open_snapshot_in_review", "import_snapshot_dialog"]
