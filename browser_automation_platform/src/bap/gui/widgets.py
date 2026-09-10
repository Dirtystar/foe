"""Reusable presentation widgets for the M4.8 desktop UI.

Thin, behaviour-free building blocks — cards, stat tiles, status pills, section
headers, and the navigation rail — styled by ``theme.py`` via object names and
dynamic properties. They hold no automation logic and emit only UI signals.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bap.gui import icons
from bap.gui.theme import DARK, STATUS_COLORS


def _apply_role(widget: QLabel, role: str) -> QLabel:
    widget.setProperty("role", role)
    return widget


class Card(QFrame):
    """A rounded surface panel with an optional section title + right-hand note.
    Add content with ``card.body`` (a QVBoxLayout)."""

    def __init__(self, title: str = "", note: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        if title:
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.addWidget(_apply_role(QLabel(title), "ctitle"))
            head.addStretch(1)
            self.note = _apply_role(QLabel(note), "faint")
            head.addWidget(self.note)
            outer.addLayout(head)
        else:
            self.note = None
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addLayout(self.body)

    def set_note(self, text: str) -> None:
        if self.note is not None:
            self.note.setText(text)


class StatTile(Card):
    """A KPI tile: uppercase label, large value, and a small sub-line."""

    def __init__(self, label: str, value: str = "—", sub: str = "", accent: str = "bronze",
                 icon_name: str = "chart", parent=None) -> None:
        super().__init__(parent=parent)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_apply_role(QLabel(label), "ctitle"))
        row.addStretch(1)
        badge = QLabel()
        badge.setPixmap(icons.icon(icon_name, stroke=getattr(DARK, accent), size=18).pixmap(18, 18))
        row.addWidget(badge)
        self.body.addLayout(row)
        self._value = _apply_role(QLabel(value), "kpi")
        self.body.addWidget(self._value)
        self._sub = _apply_role(QLabel(sub), "faint")
        self.body.addWidget(self._sub)

    def set_value(self, value: str, sub: str | None = None) -> None:
        self._value.setText(value)
        if sub is not None:
            self._sub.setText(sub)


class StatusPill(QLabel):
    """A small dot + label pill whose colour follows a semantic status key."""

    def __init__(self, text: str = "", status: str = "idle", parent=None) -> None:
        super().__init__(parent)
        self.setProperty("pill", True)
        self._status = status
        self.set_status(text, status)

    def set_status(self, text: str, status: str) -> None:
        self._status = status
        token = STATUS_COLORS.get(status, "muted")
        self.setText(f"●  {text}")
        col = getattr(DARK, token)
        # dot colour via rich text is limited in QLabel; colour the whole label text
        # muted and rely on the leading dot; keep it simple and readable.
        self.setStyleSheet(f"color:{col};")


def section_title(text: str) -> QLabel:
    return _apply_role(QLabel(text), "ctitle")


def display_title(text: str) -> QLabel:
    return _apply_role(QLabel(text), "display")


def muted(text: str) -> QLabel:
    return _apply_role(QLabel(text), "muted")


class NavRail(QListWidget):
    """Vertical icon+label navigation. Emits ``section_changed(key)`` and drives a
    QStackedWidget when connected."""

    section_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setFixedWidth(212)
        self.setSpacing(0)
        self.setUniformItemSizes(False)
        self._keys: list[str] = []
        self.currentRowChanged.connect(self._emit)

    def add_section(self, key: str, label: str, icon_name: str) -> None:
        item = QListWidgetItem(icons.icon(icon_name, stroke="#9C93A6", size=20), f"  {label}")
        item.setData(Qt.ItemDataRole.UserRole, key)
        self.addItem(item)
        self._keys.append(key)

    def add_header(self, label: str) -> None:
        item = QListWidgetItem(label.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor("#6E6678"))
        self.addItem(item)
        self._keys.append("")  # non-selectable placeholder

    def select(self, key: str) -> None:
        if key in self._keys:
            self.setCurrentRow(self._keys.index(key))

    def _emit(self, row: int) -> None:
        if 0 <= row < len(self._keys) and self._keys[row]:
            self.section_changed.emit(self._keys[row])


class Divider(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(214,186,132,0.10);")


__all__ = [
    "Card", "StatTile", "StatusPill", "NavRail", "Divider",
    "section_title", "display_title", "muted",
]
