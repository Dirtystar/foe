"""Forge Vision Debugger / Test Scan window — observe-only.

Shows exactly what the detector sees for one captured frame: the analyzed
region, every detected badge with its percentage/confidence/centre, the fixed
side-panel pill separately, the sector a strategy would select, a proposed click
point drawn as a cross, and a plain-language explanation — under a permanent
OBSERVE ONLY banner. Nothing here clicks. Artifacts can be saved for the record.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bap.forge.detection.scan import OBSERVE_ONLY_BANNER, annotate, build_scan


def bgr_to_qimage(bgr) -> QImage:
    import cv2

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class _AnnotatedView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 400)
        self._image: QImage | None = None

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 16, 14))
        if self._image is None:
            return
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        ox, oy = (self.width() - iw * scale) / 2, (self.height() - ih * scale) / 2
        painter.drawImage(QRectF(ox, oy, iw * scale, ih * scale), self._image)


class DebuggerWindow(QMainWindow):
    """Displays one observe-only scan. `image` is a BGR ndarray."""

    def __init__(self, image, *, world=None, classifier=None, source: str = "") -> None:
        super().__init__()
        self._image = image
        self._scan = build_scan(image, world=world, classifier=classifier)
        self.setWindowTitle(f"Forge Vision Debugger — {source or 'scan'}  ·  OBSERVE ONLY")

        central = QWidget()
        root = QVBoxLayout(central)

        banner = QLabel(OBSERVE_ONLY_BANNER)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(
            "background:#a01818; color:white; font-weight:bold; font-size:15px; padding:6px;"
        )
        root.addWidget(banner)

        body = QHBoxLayout()
        self.view = _AnnotatedView()
        self.view.set_image(bgr_to_qimage(annotate(image, self._scan)))
        body.addWidget(self.view, stretch=3)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(self._scan.explanation())
        self.details.setMinimumWidth(320)
        body.addWidget(self.details, stretch=2)
        root.addLayout(body)

        controls = QHBoxLayout()
        self.save_button = QPushButton("Save artifacts…")
        self.save_button.clicked.connect(self._on_save)
        controls.addWidget(self.save_button)
        controls.addStretch(1)
        note = QLabel("Real clicking stays disabled until you confirm these detections.")
        controls.addWidget(note)
        root.addLayout(controls)

        self.setCentralWidget(central)

    def _on_save(self) -> None:
        from bap.forge.detection.scan import save_scan

        out = QFileDialog.getExistingDirectory(self, "Save scan artifacts to…")
        if not out:
            return
        try:
            paths = save_scan(self._image, self._scan, out)
        except Exception as exc:  # never crash the UI over a save
            QMessageBox.warning(self, "Save", f"Could not save artifacts:\n{exc}")
            return
        QMessageBox.information(
            self, "Saved",
            "Saved:\n" + "\n".join(Path(p).name for p in paths.values()),
        )


def _bundled_classifier():
    """A classifier trained from the repo grading set, if it has been reviewed;
    otherwise None (the debugger then shows detections without percentages)."""
    try:
        from bap.forge.detection.classify import train_from_labels

        base = Path(__file__).resolve().parents[2] / "tests" / "forge_assets" / "grading"
        if (base / "labels.json").exists():
            return train_from_labels(base / "frames", base / "labels.json")
    except Exception:
        return None
    return None


def run_over_folder(frames_dir: str, world=None) -> int:
    """Offline debugger: step through the PNGs in a folder. Useful for verifying
    the detector on saved screenshots with no browser."""
    import sys

    import cv2
    from PySide6.QtWidgets import QApplication

    frames = sorted(Path(frames_dir).glob("*.png"))
    if not frames:
        raise SystemExit(f"no .png frames in {frames_dir}")
    qapp = QApplication.instance() or QApplication(sys.argv)
    clf = _bundled_classifier()
    windows = []
    for p in frames[:1]:  # open the first; Next/Prev could be added later
        img = cv2.imread(str(p))
        win = DebuggerWindow(img, world=world, classifier=clf, source=p.name)
        win.resize(1280, 760)
        win.show()
        windows.append(win)
    return int(qapp.exec())


__all__ = ["DebuggerWindow", "bgr_to_qimage", "run_over_folder"]
