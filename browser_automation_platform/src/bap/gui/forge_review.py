"""Forge Vision Debugger — Review Mode (observe-only).

Steps through captured frames and, for each, shows what the detector sees and
lets a human confirm the ground truth. It covers BOTH required signals:

  1. On-map weakening badges — detector overlay + correction (left-click add,
     right-click remove, keys 1-5 set 20/40/60/80/100), autosaved.
  2. Current weakening — Set Weakening Region (drag a box), enter the correct
     value, and see the raw/processed crop, the OCR read + confidence, the
     world limit, and the fail-safe decision CONTINUE / STOP / UNKNOWN.

Nothing here clicks the game. It reads and records, so accuracy can be measured
and verified before real actions are ever enabled.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bap.core.domain.models import Rect
from bap.forge.detection.calibration import WeakeningCalibration
from bap.forge.detection.detector import BadgeDetector
from bap.forge.detection.weakening import decide, read_ocr
from bap.forge.labeling.app import _PCT_COLORS, _PCT_KEYS
from bap.forge.labeling.session import LabelSession


def _bgr_to_qimage(bgr) -> QImage:
    import cv2

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class ReviewCanvas(QWidget):
    """Frame view with editable badges, detector overlay, and a draggable
    weakening region. Two modes: badge editing (default) and region drawing."""

    badge_clicked = Signal(int, int, object)  # image_x, image_y, button
    region_drawn = Signal(object)             # Rect in image pixels

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 440)
        self._image: QImage | None = None
        self._badges: list = []
        self._detections: list = []
        self._weak_rect: Rect | None = None
        self._map_rect: Rect | None = None
        self.region_mode = False
        self.region_target = "weakening"  # or "battle_map"
        self._scale = 1.0
        self._ox = self._oy = 0.0
        self._drag_start: QPointF | None = None
        self._drag_now: QPointF | None = None

    def set_state(self, image, badges, detections, weak_rect, map_rect=None) -> None:
        self._image, self._badges, self._detections, self._weak_rect = (
            image, badges, detections, weak_rect,
        )
        self._map_rect = map_rect
        self.update()

    def _fit(self) -> None:
        if self._image is None:
            return
        iw, ih = self._image.width(), self._image.height()
        self._scale = min(self.width() / iw, self.height() / ih)
        self._ox = (self.width() - iw * self._scale) / 2
        self._oy = (self.height() - ih * self._scale) / 2

    def _to_image(self, x, y):
        return int((x - self._ox) / self._scale), int((y - self._oy) / self._scale)

    def _to_widget(self, x, y):
        return QPointF(self._ox + x * self._scale, self._oy + y * self._scale)

    def mousePressEvent(self, e):  # noqa: N802
        if self._image is None:
            return
        if self.region_mode:
            self._drag_start = e.position()
            self._drag_now = e.position()
        else:
            ix, iy = self._to_image(e.position().x(), e.position().y())
            self.badge_clicked.emit(ix, iy, e.button())

    def mouseMoveEvent(self, e):  # noqa: N802
        if self.region_mode and self._drag_start is not None:
            self._drag_now = e.position()
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.region_mode and self._drag_start is not None:
            x0, y0 = self._to_image(self._drag_start.x(), self._drag_start.y())
            x1, y1 = self._to_image(e.position().x(), e.position().y())
            self._drag_start = self._drag_now = None
            rx, ry = min(x0, x1), min(y0, y1)
            rw, rh = abs(x1 - x0), abs(y1 - y0)
            if rw >= 4 and rh >= 4:
                self.region_drawn.emit(Rect(x=rx, y=ry, w=rw, h=rh))

    def resizeEvent(self, e):  # noqa: N802
        self._fit()
        super().resizeEvent(e)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 20, 18))
        if self._image is None:
            return
        self._fit()
        p.drawImage(QRectF(self._ox, self._oy, self._image.width() * self._scale,
                           self._image.height() * self._scale), self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Detector detections (faint dashed).
        p.setPen(QPen(QColor(160, 160, 160, 200), 1.5, Qt.PenStyle.DashLine))
        for d in self._detections:
            p.drawEllipse(self._to_widget(d.cx, d.cy), 14, 14)

        # Confirmed badges (solid, coloured by %).
        for b in self._badges:
            color = _PCT_COLORS.get(b.pct, _PCT_COLORS[None])
            p.setPen(QPen(color, 2.4))
            c = self._to_widget(b.cx, b.cy)
            p.drawEllipse(c, 13, 13)
            p.drawText(QPointF(c.x() + 15, c.y() - 9), f"{b.pct}%" if b.pct is not None else "?")

        # Battle-map ROI (the whole analyzed map area).
        if self._map_rect is not None:
            r = self._map_rect
            tl = self._to_widget(r.x, r.y)
            p.setPen(QPen(QColor(90, 200, 110), 2))
            p.drawRect(QRectF(tl.x(), tl.y(), r.w * self._scale, r.h * self._scale))

        # Weakening region.
        if self._weak_rect is not None:
            r = self._weak_rect
            tl = self._to_widget(r.x, r.y)
            p.setPen(QPen(QColor(40, 220, 235), 2))
            p.drawRect(QRectF(tl.x(), tl.y(), r.w * self._scale, r.h * self._scale))

        # In-progress region drag.
        if self._drag_start is not None and self._drag_now is not None:
            p.setPen(QPen(QColor(40, 220, 235), 1, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(self._drag_start, self._drag_now).normalized())


class ForgeReviewWindow(QMainWindow):
    def __init__(self, session: LabelSession, frames_dir, calibration: WeakeningCalibration,
                 *, world=None, detector: BadgeDetector | None = None) -> None:
        super().__init__()
        self._session = session
        # Review Mode persists ONLY on an explicit Save, so a close can Discard
        # cleanly and edits never silently reach disk before the operator saves.
        self._session.store.autosave = False
        self._dirty = False
        self._frames_dir = Path(frames_dir)
        self._cal = calibration
        self._world = world
        self._detector = detector
        self._img = None
        self.setWindowTitle("Forge Vision Debugger — Review Mode  ·  OBSERVE ONLY")

        central = QWidget()
        root = QVBoxLayout(central)
        banner = QLabel("OBSERVE ONLY — NO CLICK PERFORMED")
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet("background:#a01818;color:white;font-weight:bold;padding:5px;")
        root.addWidget(banner)

        body = QHBoxLayout()
        self.canvas = ReviewCanvas()
        self.canvas.badge_clicked.connect(self._on_badge_clicked)
        self.canvas.region_drawn.connect(self._on_region_drawn)
        body.addWidget(self.canvas, stretch=3)
        body.addWidget(self._build_side_panel(), stretch=2)
        root.addLayout(body)

        legend = QLabel("Badges: left-click add/select · right-click remove · 1-5 set 20/40/60/80/100"
                        "   |   ←/→ frame   ·   Set Weakening / Battle-Map Region → drag a box")
        legend.setWordWrap(True)
        root.addWidget(legend)
        self.setCentralWidget(central)
        self._load()

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        # --- explicit save bar (M4.14) --------------------------------------
        save_row = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.setToolTip("Write the current labels to the labels file now (atomic).")
        self.save_button.clicked.connect(self._save_now)
        self.reviewed_check = QCheckBox("Reviewed")
        self.reviewed_check.setToolTip(
            "Mark THIS frame reviewed — works for zero-badge negatives too. "
            "Written to disk on Save.")
        self.reviewed_check.toggled.connect(self._on_reviewed_toggled)
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.reviewed_check)
        save_row.addStretch(1)
        v.addLayout(save_row)
        self.save_status = QLabel("")
        v.addWidget(self.save_status)
        self.labels_path_lbl = QLabel("")
        self.labels_path_lbl.setWordWrap(True)
        self.labels_path_lbl.setStyleSheet("color:#888; font-size:11px;")
        v.addWidget(self.labels_path_lbl)
        self.dup_warn_lbl = QLabel("")
        self.dup_warn_lbl.setWordWrap(True)
        self.dup_warn_lbl.setStyleSheet("color:#b00020; font-weight:bold; font-size:11px;")
        v.addWidget(self.dup_warn_lbl)

        row = QHBoxLayout()
        self.detect_button = QPushButton("Run detector")
        self.detect_button.setCheckable(True)
        self.detect_button.clicked.connect(self._load)
        self.region_button = QPushButton("Set Weakening Region")
        self.region_button.setCheckable(True)
        self.region_button.toggled.connect(lambda on: self._toggle_region_mode(on, "weakening"))
        self.map_region_button = QPushButton("Set Battle-Map Region")
        self.map_region_button.setCheckable(True)
        self.map_region_button.toggled.connect(lambda on: self._toggle_region_mode(on, "battle_map"))
        row.addWidget(self.detect_button)
        row.addWidget(self.region_button)
        row.addWidget(self.map_region_button)
        v.addLayout(row)

        v.addWidget(QLabel("<b>Current weakening</b>"))
        self.raw_view = QLabel(); self.raw_view.setFixedHeight(48)
        self.raw_view.setStyleSheet("background:#111;")
        self.proc_view = QLabel(); self.proc_view.setFixedHeight(48)
        self.proc_view.setStyleSheet("background:#111;")
        v.addWidget(QLabel("raw crop:")); v.addWidget(self.raw_view)
        v.addWidget(QLabel("processed crop:")); v.addWidget(self.proc_view)

        grid = QGridLayout()
        self.detected_lbl = QLabel("—")
        self.conf_lbl = QLabel("—")
        self.limit_lbl = QLabel("—")
        self.decision_lbl = QLabel("UNKNOWN")
        self.decision_lbl.setStyleSheet("font-weight:bold;")
        self.gt_edit = QLineEdit()
        self.gt_edit.setPlaceholderText("correct value")
        self.gt_edit.editingFinished.connect(self._on_gt_entered)
        grid.addWidget(QLabel("detected:"), 0, 0); grid.addWidget(self.detected_lbl, 0, 1)
        grid.addWidget(QLabel("confidence:"), 1, 0); grid.addWidget(self.conf_lbl, 1, 1)
        grid.addWidget(QLabel("ground truth:"), 2, 0); grid.addWidget(self.gt_edit, 2, 1)
        grid.addWidget(QLabel("world limit:"), 3, 0); grid.addWidget(self.limit_lbl, 3, 1)
        grid.addWidget(QLabel("decision:"), 4, 0); grid.addWidget(self.decision_lbl, 4, 1)
        v.addLayout(grid)

        nav = QHBoxLayout()
        prev = QPushButton("← Prev"); prev.clicked.connect(lambda: self._nav(-1))
        nxt = QPushButton("Next →"); nxt.clicked.connect(lambda: self._nav(+1))
        nav.addWidget(prev); nav.addWidget(nxt)
        v.addLayout(nav)
        self.status = QLabel("")
        v.addWidget(self.status)
        v.addStretch(1)
        return panel

    # --- state --------------------------------------------------------------

    def _toggle_region_mode(self, on: bool, target: str) -> None:
        # Only one region tool active at a time.
        if on:
            other = self.map_region_button if target == "weakening" else self.region_button
            if other.isChecked():
                other.setChecked(False)
            self.canvas.region_target = target
        self.canvas.region_mode = on
        self.region_button.setText(
            "Drawing… (drag a box)" if (on and target == "weakening") else "Set Weakening Region")
        self.map_region_button.setText(
            "Drawing… (drag a box)" if (on and target == "battle_map") else "Set Battle-Map Region")

    def _weak_region(self) -> Rect | None:
        if self._img is None:
            return None
        h, w = self._img.shape[:2]
        return self._cal.get(w, h)

    def _map_region(self) -> Rect | None:
        if self._img is None:
            return None
        h, w = self._img.shape[:2]
        return self._cal.get_battle_map(w, h)

    def _load(self) -> None:
        import cv2

        path = self._frames_dir / self._session.current_file()
        self._img = cv2.imread(str(path))
        detections = []
        if self._img is not None and self.detect_button.isChecked():
            detector = self._detector or BadgeDetector()
            detections = detector.detect(self._img)
        rect = self._weak_region()
        if self._img is not None:
            self.canvas.set_state(_bgr_to_qimage(self._img), self._session.badges(),
                                  detections, rect, self._map_region())
        self._refresh_weakening(rect)
        gt = self._session.weakening()
        self.gt_edit.setText("" if gt is None else str(gt))
        s = self._session
        self.status.setText(f"[{s.index + 1}/{s.total}] {s.current_file()}   "
                            f"badges {len(s.badges())}  reviewed {s.reviewed_count()}/{s.total}")
        # Reflect this frame's reviewed state without re-triggering the toggle.
        self.reviewed_check.blockSignals(True)
        self.reviewed_check.setChecked(self._session.current().reviewed)
        self.reviewed_check.blockSignals(False)
        self._refresh_save_ui()

    # --- explicit save / dirty state (M4.14) --------------------------------

    def _refresh_save_ui(self) -> None:
        path = self._session.store.path
        self.labels_path_lbl.setText(f"Labels file: {path}")
        # Warn if a *different* labels.json sits in the frames dir (a classic
        # foot-gun: edits go to the labels file above, not that one).
        dup = self._frames_dir / "labels.json"
        store_path = Path(path) if path is not None else None
        try:
            is_other = dup.exists() and (store_path is None or dup.resolve() != store_path.resolve())
        except OSError:
            is_other = dup.exists()
        self.dup_warn_lbl.setText(
            f"⚠ A different labels.json exists in the frames folder:\n{dup}\n"
            "Edits are written to the labels file above, not that one."
            if is_other else "")
        if not self._dirty:
            if not self.save_status.text().startswith("✅"):
                self.save_status.setText("○ No unsaved changes")
                self.save_status.setStyleSheet("color:#888;")

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.save_status.setText("● Unsaved changes")
        self.save_status.setStyleSheet("color:#b00020; font-weight:bold;")

    def _save_now(self) -> None:
        import time

        self._session.store.save()          # explicit + atomic, to the bound path
        self._dirty = False
        path = self._session.store.path
        self.save_status.setText(f"✅ Saved to: {path}   ·   {time.strftime('%H:%M:%S')}")
        self.save_status.setStyleSheet("color:#2e7d32; font-weight:bold;")

    def _on_reviewed_toggled(self, checked: bool) -> None:
        # Explicit reviewed control — works for zero-badge negatives too; never
        # inferred from merely opening the frame. Persisted on Save.
        if self._session.current().reviewed != checked:
            self._session.current().reviewed = checked
            self._mark_dirty()

    def _refresh_weakening(self, rect: Rect | None) -> None:
        self.limit_lbl.setText(str(getattr(self._world, "max_weakening", "—")) if self._world else "—")
        if rect is None or self._img is None:
            self.detected_lbl.setText("(set a weakening region)")
            self.conf_lbl.setText("—")
            self.decision_lbl.setText("UNKNOWN")
            self.raw_view.clear(); self.proc_view.clear()
            return
        read = read_ocr(self._img, rect)
        self.detected_lbl.setText("unreadable" if read.value is None else str(read.value))
        self.conf_lbl.setText(f"{read.confidence:.2f}")
        d = decide(read, self._world)
        self.decision_lbl.setText(d.value)
        colors = {"CONTINUE": "#2e7d32", "STOP": "#b00020", "UNKNOWN": "#8a6d00"}
        self.decision_lbl.setStyleSheet(f"font-weight:bold;color:{colors[d.value]};")
        if read.raw_crop is not None:
            self.raw_view.setPixmap(self._crop_pixmap(read.raw_crop, gray=False))
        if read.processed_crop is not None:
            self.proc_view.setPixmap(self._crop_pixmap(read.processed_crop, gray=True))

    def _crop_pixmap(self, crop, *, gray: bool):
        from PySide6.QtGui import QPixmap

        if gray:
            h, w = crop.shape[:2]
            q = QImage(crop.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        else:
            q = _bgr_to_qimage(crop)
        return QPixmap.fromImage(q).scaledToHeight(44, Qt.TransformationMode.SmoothTransformation)

    # --- interaction --------------------------------------------------------

    def _on_badge_clicked(self, ix, iy, button) -> None:
        changed = False
        if button == Qt.MouseButton.RightButton:
            changed = self._session.remove_nearest(ix, iy, radius=40)
        elif self._session.select_nearest(ix, iy, radius=20) is None:
            self._session.add_badge(ix, iy)
            changed = True
        if changed:
            self._mark_dirty()
        self._load()

    def _on_region_drawn(self, rect: Rect) -> None:
        if self._img is None:
            return
        h, w = self._img.shape[:2]
        if self.canvas.region_target == "battle_map":
            self._cal.set_battle_map(w, h, rect)  # persists per-resolution
            self.map_region_button.setChecked(False)
        else:
            self._cal.set(w, h, rect)             # persists per-resolution
            self.region_button.setChecked(False)
        self._load()

    def _on_gt_entered(self) -> None:
        text = self.gt_edit.text().strip()
        new = int(text) if text.isdigit() else None
        if self._session.weakening() != new:
            self._session.set_weakening(new)
            self._mark_dirty()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        key = e.key()
        if key in _PCT_KEYS:
            self._session.arm_pct(_PCT_KEYS[key]); self._mark_dirty(); self._load()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._nav(+1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._nav(-1)
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._session.remove_active():
                self._mark_dirty()
            self._load()
        else:
            super().keyPressEvent(e)

    def _nav(self, delta: int) -> None:
        # No implicit reviewed write on navigation — reviewed is set only by the
        # explicit checkbox. All frames' edits live in the in-memory store, so
        # navigating never loses them; they persist together on the next Save.
        self._session.goto(self._session.index + delta)
        self._load()

    def _prompt_unsaved(self) -> str:
        """Show the unsaved-changes dialog; return 'save' | 'discard' | 'cancel'."""
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText("Save changes before closing?")
        save_b = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_b = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_b)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            return "cancel"
        return "save" if clicked is save_b else "discard"

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Never lose edits silently: prompt when there are unsaved changes.
        if not self._dirty:
            super().closeEvent(event)
            return
        choice = self._prompt_unsaved()
        if choice == "cancel":
            event.ignore()
            return
        if choice == "save":
            self._save_now()
        super().closeEvent(event)  # Discard: proceed without writing


def run_review(frames_dir: str, labels_path: str, calibration_path: str, world=None) -> int:
    import sys

    from PySide6.QtWidgets import QApplication

    session = LabelSession.open(frames_dir, labels_path)
    cal = WeakeningCalibration.load(calibration_path)
    qapp = QApplication.instance() or QApplication(sys.argv)
    win = ForgeReviewWindow(session, frames_dir, cal, world=world)
    win.resize(1360, 800)
    win.show()
    return int(qapp.exec())


def main(argv=None) -> int:
    """CLI: review the scans in a frames folder.

        python -m bap.gui.forge_review <frames_dir> [--labels P] [--calibration P]
    """
    import argparse

    from bap.forge.labeling.__main__ import default_labels_path

    parser = argparse.ArgumentParser(prog="bap-forge-review", description="Forge Review Mode")
    parser.add_argument("frames_dir")
    parser.add_argument("--labels", default=None)
    parser.add_argument("--calibration", default=None)
    args = parser.parse_args(argv)
    frames_dir = Path(args.frames_dir)
    labels = args.labels or str(default_labels_path(frames_dir))
    calibration = args.calibration or str(frames_dir.parent / "calibration.json")
    return run_review(str(frames_dir), labels, calibration)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ForgeReviewWindow", "ReviewCanvas", "run_review", "main"]
