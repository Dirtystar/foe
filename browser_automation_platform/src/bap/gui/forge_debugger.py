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

    def __init__(self, image, *, world=None, classifier=None, source: str = "",
                 weakening_region=None, rois=None, geometry=None,
                 live_review_dir=None) -> None:
        super().__init__()
        self._image = image
        self._classifier = classifier
        self._world = world
        self._source = source
        self._live_review_dir = live_review_dir
        self._review = None
        self._scan = build_scan(image, world=world, classifier=classifier,
                                weakening_region=weakening_region, rois=rois,
                                geometry=geometry)
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
        self.review_button = QPushButton("Label in Review Mode…")
        self.review_button.setToolTip(
            "Correct these live detections: click to add, right-click to remove, "
            "keys 1-5 set 20/40/60/80/100. Saved as live ground truth.")
        self.review_button.clicked.connect(self._on_label_review)
        controls.addWidget(self.review_button)
        self.snapshot_button = QPushButton("Save Snapshot")
        self.snapshot_button.setToolTip(
            "Freeze this exact scan into a permanent, reproducible, reviewable "
            "snapshot so the live game changing can never lose it.")
        self.snapshot_button.clicked.connect(self._on_save_snapshot)
        controls.addWidget(self.snapshot_button)
        controls.addStretch(1)
        note = QLabel("Real clicking stays disabled until you confirm these detections.")
        controls.addWidget(note)
        root.addLayout(controls)

        self.setCentralWidget(central)

    def _on_label_review(self) -> None:
        """Open the current live capture in Review Mode so the operator can add /
        correct badges (keys 1-5), remove false positives, and save the result as
        additional live ground truth — reusing the existing labelling tools, no
        external editor."""
        from bap.forge.detection.calibration import WeakeningCalibration
        from bap.forge.detection.detector import BadgeDetector
        from bap.forge.labeling.session import LabelSession
        from bap.gui.forge_review import ForgeReviewWindow

        try:
            base = self._live_review_dir or self._default_live_review_dir()
            frames_dir, name = save_live_review_frame(self._image, self._source, base)
            session = LabelSession.open(frames_dir, Path(base) / "labels.json")
            for i in range(session.total):
                session.goto(i)
                if session.current_file() == name:
                    break
            cal = WeakeningCalibration.load(Path(base) / "calibration.json")
            self._review = ForgeReviewWindow(session, frames_dir, cal, world=self._world,
                                             detector=BadgeDetector())
            self._review.resize(1360, 800)
            self._review.show()
        except Exception as exc:  # never crash the debugger over a review launch
            QMessageBox.warning(self, "Review Mode", f"Could not open Review Mode:\n{exc}")

    def _on_save_snapshot(self) -> None:
        """Freeze this scan into a reproducible snapshot (raw + annotated + trace +
        world + calibration + labels + metadata), then offer Open-in-Review /
        Import. Observe-only — it writes files, nothing more."""
        from bap.forge.detection.detector import BadgeDetector
        from bap.gui.snapshot_actions import save_snapshot_and_offer

        save_snapshot_and_offer(
            self, image=self._image, scan=self._scan, world=self._world,
            classifier=self._classifier, detector=BadgeDetector(),
            url=getattr(self._world, "last_url", None),
        )

    @staticmethod
    def _default_live_review_dir() -> Path:
        from bap.ops.paths import ensure_dirs, get_paths

        return ensure_dirs(get_paths()).data_dir / "forge" / "live_review"

    def _on_save(self) -> None:
        from bap.forge.detection.scan import save_scan

        out = QFileDialog.getExistingDirectory(self, "Save scan artifacts to…")
        if not out:
            return
        try:
            paths = save_scan(self._image, self._scan, out, classifier=self._classifier)
        except Exception as exc:  # never crash the UI over a save
            QMessageBox.warning(self, "Save", f"Could not save artifacts:\n{exc}")
            return
        QMessageBox.information(
            self, "Saved",
            "Saved:\n" + "\n".join(Path(p).name for p in paths.values()),
        )


def save_live_review_frame(image, source: str, base_dir) -> tuple[str, str]:
    """Persist a live capture as a Review-Mode frame under ``base_dir/frames`` and
    return ``(frames_dir, filename)``. The filename carries the World/source and a
    timestamp so live scans accumulate as reviewable ground truth."""
    import re
    from datetime import datetime

    import cv2

    frames_dir = Path(base_dir) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9_-]+", "_", (source or "scan").split()[0]) or "scan"
    name = f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    cv2.imwrite(str(frames_dir / name), image)
    return str(frames_dir), name


def _bundled_classifier():
    """A classifier trained from the reviewed grading set **and** the reviewed
    live-browser scans, so live-scale badges have same-scale exemplars. Returns
    None if nothing is reviewed (the debugger then shows detections without %)."""
    try:
        from bap.forge.detection.classify import (
            default_assets_root,
            default_label_sources,
            train_from_sources,
        )

        root = default_assets_root()
        if root is None:
            return None
        sources = default_label_sources(root)
        return train_from_sources(sources) if sources else None
    except Exception:
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
