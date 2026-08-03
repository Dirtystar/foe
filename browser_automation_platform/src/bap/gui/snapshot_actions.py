"""Shared GUI actions for reproducible snapshots (Milestone 4.13) — observe-only.

Save Snapshot, Open Snapshot in Review (zero-copy), and Import Snapshot into a
Dataset — reused by the Vision Debugger (Test Scan) and the Vision Validation
page so both freeze scans the same way. These only write files and open the
existing Review Mode; nothing here clicks, moves the cursor, or types.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from bap.forge import snapshots


def open_snapshot_in_review(parent, snapshot_dir, world=None) -> None:
    """Open a snapshot's raw frame in Review Mode. Review Mode reads the snapshot's
    ``frames/`` dir and rewrites only ``labels.json`` — raw/annotated/scan stay
    immutable. Non-blocking; the window is parented so it stays alive."""
    from bap.forge.detection.calibration import WeakeningCalibration
    from bap.forge.detection.detector import BadgeDetector
    from bap.forge.labeling.session import LabelSession
    from bap.gui.forge_review import ForgeReviewWindow

    frames_dir, labels_path, calibration_path = snapshots.review_paths(snapshot_dir)
    try:
        session = LabelSession.open(frames_dir, labels_path)
        cal = WeakeningCalibration.load(calibration_path)
        win = ForgeReviewWindow(session, frames_dir, cal, world=world, detector=BadgeDetector())
        win.resize(1360, 800)
        win.show()
        # Keep a reference so the window is not garbage-collected.
        parent._snapshot_review_window = win
    except Exception as exc:  # never crash the caller over a review launch
        QMessageBox.warning(parent, "Open Snapshot in Review",
                            f"Could not open the snapshot in Review Mode:\n{exc}")


def import_snapshot_dialog(parent, snapshot_dir) -> None:
    """Ask for a dataset directory and import the snapshot into it (dedup by hash)."""
    dataset = QFileDialog.getExistingDirectory(parent, "Import snapshot into dataset (pick dataset dir)")
    if not dataset:
        return
    try:
        result = snapshots.import_into_dataset(snapshot_dir, dataset)
    except Exception as exc:
        QMessageBox.warning(parent, "Import Snapshot", f"Could not import:\n{exc}")
        return
    if result["imported"]:
        QMessageBox.information(parent, "Import Snapshot",
                               f"Imported into dataset as:\n{Path(result['dest']).name}")
    else:
        QMessageBox.information(parent, "Import Snapshot",
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
    box.setInformativeText("It is fully reproducible and reviewable. What next?")
    review_btn = box.addButton("Open in Review", QMessageBox.ButtonRole.AcceptRole)
    import_btn = box.addButton("Import into Dataset…", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Done", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is review_btn:
        open_snapshot_in_review(parent, snapshot_dir, world=world)
    elif clicked is import_btn:
        import_snapshot_dialog(parent, snapshot_dir)
    return snapshot_dir


__all__ = ["save_snapshot_and_offer", "open_snapshot_in_review", "import_snapshot_dialog"]
