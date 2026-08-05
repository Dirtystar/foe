"""Operator content-origin calibration overlay (Milestone 5A.1).

A translucent, BAP-owned, full-screen overlay on which the operator clicks the
**top-left** then **bottom-right** corner of the Forge content area. It returns the
marked rectangle in **physical screen pixels**, so the cursor-preview transform can
map a raw-capture point onto the real screen without assuming any title-bar or
border constants.

It is strictly a read of the operator's two clicks on BAP's own window: it sends
**no input to Chrome**, never clicks in the game, and moves nothing. Escape (or a
right-click) cancels. Cross-DPI placement is best-effort — see
M5A1_WINDOWS_GEOMETRY_REPORT.md.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget


class ContentOriginOverlay(QWidget):
    """Captures two clicks and reports them in physical pixels."""

    def __init__(self, parent=None):
        super().__init__(None)  # top-level, not a child, so it can cover the desktop
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._points: list[QPoint] = []
        self._result: tuple[int, int, int, int] | None = None
        self._done = False

    def _to_physical(self, global_pos: QPoint) -> tuple[int, int]:
        """Convert a logical global position to physical screen pixels using the
        screen's device pixel ratio at that point."""
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        geo = screen.geometry() if screen is not None else None
        if geo is None:
            return int(round(global_pos.x() * dpr)), int(round(global_pos.y() * dpr))
        # Physical = screen origin (physical) + offset-within-screen × dpr.
        ox = geo.x() + (global_pos.x() - geo.x()) * dpr
        oy = geo.y() + (global_pos.y() - geo.y()) * dpr
        return int(round(ox)), int(round(oy))

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.RightButton:
            self._done = True
            self.close()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._points.append(event.globalPosition().toPoint())
        if len(self._points) >= 2:
            (x1, y1) = self._to_physical(self._points[0])
            (x2, y2) = self._to_physical(self._points[1])
            left, right = sorted((x1, x2))
            top, bottom = sorted((y1, y2))
            if right > left and bottom > top:
                self._result = (left, top, right, bottom)
            self._done = True
            self.close()
        else:
            self.update()

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self._done = True
            self.close()

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        painter.setPen(QColor(224, 180, 84))
        step = "top-left" if not self._points else "bottom-right"
        painter.drawText(30, 40,
                         f"Set Browser Content Origin — click the {step} corner of the "
                         "Forge content. Esc / right-click to cancel. (No click is sent to Chrome.)")
        for p in self._points:
            local = self.mapFromGlobal(p)
            painter.drawEllipse(local, 6, 6)

    def result_rect(self) -> tuple[int, int, int, int] | None:
        return self._result


def capture_content_rect(parent=None) -> tuple[int, int, int, int] | None:
    """Show the overlay modally and return the physical content rectangle, or None
    if cancelled. Never sends input to Chrome; never clicks in the game."""
    overlay = ContentOriginOverlay(parent)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()
    app = QGuiApplication.instance()
    # Pump events until the operator finishes; the overlay closes itself.
    while not overlay._done and overlay.isVisible():
        app.processEvents()
    return overlay.result_rect()


__all__ = ["ContentOriginOverlay", "capture_content_rect"]
