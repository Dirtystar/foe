"""PySide6 labelling window — a thin view over LabelSession.

Workflow: it shows a frame with any auto-suggested badge centres, you confirm or
place centres by clicking, press a number key to set the percentage, and move on.
Everything autosaves; closing and reopening resumes at the first unreviewed frame.

Controls
  Left-click empty  add a badge centre (uses the armed %)
  Left-click a dot  select it (then a number key sets its %)
  Right-click a dot delete it
  1..5              set % to 20 / 40 / 60 / 80 / 100 (arms it for new clicks too)
  Space / G         accept all suggested centres on this frame
  N                 mark frame as a negative (reviewed, no badges) and advance
  R                 toggle "reviewed" for this frame
  C                 clear this frame's badges
  ← / →  or  A / D  previous / next frame
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from bap.forge.labeling.model import VALID_PCTS
from bap.forge.labeling.session import LabelSession
from bap.forge.labeling import suggest

_PCT_KEYS = {
    Qt.Key.Key_1: 20, Qt.Key.Key_2: 40, Qt.Key.Key_3: 60,
    Qt.Key.Key_4: 80, Qt.Key.Key_5: 100,
}
_PCT_COLORS = {
    20: QColor(90, 170, 255), 40: QColor(90, 210, 130), 60: QColor(240, 200, 60),
    80: QColor(245, 140, 50), 100: QColor(235, 80, 70), None: QColor(180, 180, 180),
}


class ImageCanvas(QWidget):
    """Draws the frame scaled-to-fit with badge + suggestion overlays and maps
    clicks back to original image pixels."""

    clicked = Signal(int, int, object)  # image_x, image_y, Qt.MouseButton

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 400)
        self._image: QImage | None = None
        self._badges: list = []
        self._suggestions: list[tuple[int, int]] = []
        self._active: int | None = None
        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0

    def set_frame(self, image, badges, suggestions, active) -> None:
        self._image = image
        self._badges = badges
        self._suggestions = suggestions
        self._active = active
        self.update()

    def _recompute_transform(self) -> None:
        if self._image is None:
            return
        iw, ih = self._image.width(), self._image.height()
        if iw == 0 or ih == 0:
            return
        self._scale = min(self.width() / iw, self.height() / ih)
        self._ox = (self.width() - iw * self._scale) / 2
        self._oy = (self.height() - ih * self._scale) / 2

    def _to_image(self, x: float, y: float) -> tuple[int, int]:
        if self._scale == 0:
            return 0, 0
        return int((x - self._ox) / self._scale), int((y - self._oy) / self._scale)

    def _to_widget(self, cx: float, cy: float) -> QPointF:
        return QPointF(self._ox + cx * self._scale, self._oy + cy * self._scale)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._image is None:
            return
        ix, iy = self._to_image(event.position().x(), event.position().y())
        self.clicked.emit(ix, iy, event.button())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._recompute_transform()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 22, 20))
        if self._image is None:
            return
        self._recompute_transform()
        target = QRectF(self._ox, self._oy, self._image.width() * self._scale,
                        self._image.height() * self._scale)
        painter.drawImage(target, self._image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Suggestions: faint dashed rings the user can accept.
        pen = QPen(QColor(160, 160, 160, 200), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for cx, cy in self._suggestions:
            c = self._to_widget(cx, cy)
            painter.drawEllipse(c, 16, 16)

        # Confirmed badges: solid rings coloured by %, active one thicker.
        font = QFont()
        font.setBold(True)
        painter.setFont(font)
        for i, b in enumerate(self._badges):
            color = _PCT_COLORS.get(b.pct, _PCT_COLORS[None])
            width = 3.5 if i == self._active else 2.0
            painter.setPen(QPen(color, width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            c = self._to_widget(b.cx, b.cy)
            painter.drawEllipse(c, 14, 14)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(c, 2.5, 2.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            label = f"{b.pct}%" if b.pct is not None else "?"
            painter.drawText(QPointF(c.x() + 16, c.y() - 10), label)


class LabelWindow(QMainWindow):
    def __init__(self, session: LabelSession, frames_dir: Path | str) -> None:
        super().__init__()
        self._session = session
        self._frames_dir = Path(frames_dir)
        self._suggestions: list[tuple[int, int]] = []
        self.setWindowTitle("Forge badge labelling")

        central = QWidget()
        root = QVBoxLayout(central)
        self.canvas = ImageCanvas()
        self.canvas.clicked.connect(self._on_canvas_clicked)
        root.addWidget(self.canvas, stretch=1)

        legend = QLabel(
            "Left-click: add/select   Right-click: delete   1-5: 20/40/60/80/100   "
            "Space: accept suggestions   N: negative   R: reviewed   C: clear   ←/→: frame"
        )
        legend.setWordWrap(True)
        root.addWidget(legend)

        bar = QHBoxLayout()
        self.status = QLabel("")
        self.progress = QLabel("")
        bar.addWidget(self.status, stretch=1)
        bar.addWidget(self.progress)
        root.addLayout(bar)

        self.setCentralWidget(central)
        self._load_current()

    # --- frame loading ------------------------------------------------------

    def _load_current(self) -> None:
        file = self._session.current_file()
        path = self._frames_dir / file
        image = QImage(str(path))
        self._suggestions = suggest.suggest_badges(path) if suggest.available() else []
        # Hide suggestions that already coincide with a confirmed badge.
        existing = self._session.badges()
        self._suggestions = [
            (cx, cy) for (cx, cy) in self._suggestions
            if all((cx - b.cx) ** 2 + (cy - b.cy) ** 2 > 30 * 30 for b in existing)
        ]
        self._refresh(image)

    def _refresh(self, image: QImage | None = None) -> None:
        if image is None:
            image = QImage(str(self._frames_dir / self._session.current_file()))
        self.canvas.set_frame(
            image, self._session.badges(), self._suggestions, self._session.active_index
        )
        s = self._session
        armed = f"{s.armed_pct}%" if s.armed_pct is not None else "—"
        review = "REVIEWED" if s.current().reviewed else "not reviewed"
        self.status.setText(
            f"[{s.index + 1}/{s.total}] {s.current_file()}   "
            f"badges: {len(s.badges())}  unclassified: {s.unclassified()}  "
            f"armed: {armed}  {review}"
        )
        self.progress.setText(f"reviewed {s.reviewed_count()}/{s.total}")

    # --- interaction --------------------------------------------------------

    def _on_canvas_clicked(self, ix: int, iy: int, button) -> None:
        if button == Qt.MouseButton.RightButton:
            self._session.remove_nearest(ix, iy, radius=40)
        elif self._session.select_nearest(ix, iy, radius=20) is None:
            self._session.add_badge(ix, iy)
        self._refresh()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if key in _PCT_KEYS:
            self._session.arm_pct(_PCT_KEYS[key])
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._advance(+1)
            return
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._advance(-1)
            return
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_G):
            self._session.accept_suggestions(self._suggestions)
            self._suggestions = []
        elif key == Qt.Key.Key_N:
            self._session.current().badges.clear()
            self._session.set_reviewed(True)
            self._advance(+1)
            return
        elif key == Qt.Key.Key_R:
            self._session.set_reviewed(not self._session.current().reviewed)
        elif key == Qt.Key.Key_C:
            self._session.current().badges.clear()
            self._session.store.save()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._session.remove_active()
        else:
            super().keyPressEvent(event)
            return
        self._refresh()

    def _advance(self, delta: int) -> None:
        # Auto-mark a frame reviewed when leaving it if it is fully classified
        # (every badge has a %); negatives are marked explicitly with N.
        cur = self._session.current()
        if cur.badges and all(b.pct is not None for b in cur.badges):
            cur.reviewed = True
            self._session.store.save()
        self._session.goto(self._session.index + delta)
        self._load_current()


def run(frames_dir: str, labels_path: str) -> int:
    """Open the labelling window over `frames_dir`, saving to `labels_path`."""
    import sys

    from PySide6.QtWidgets import QApplication

    session = LabelSession.open(frames_dir, labels_path)
    qapp = QApplication.instance() or QApplication(sys.argv)
    window = LabelWindow(session, frames_dir)
    window.resize(1200, 780)
    window.show()
    return int(qapp.exec())


__all__ = ["ImageCanvas", "LabelWindow", "run"]
