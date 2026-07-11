"""Forge World Manager GUI pieces: the add/edit dialog for a World.

Kept out of main_window so the window stays a thin observer/controller. The
dialog is pure Qt over the `World` domain model — it validates by constructing a
`World` (raising `WorldError` on bad input) and never persists anything itself;
the caller owns the `WorldStore`.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bap.forge.worlds import BADGE_PCTS, World, WorldError, is_forge_hostname, normalize_hostname


class WorldDialog(QDialog):
    """Add or edit one World.

    `existing` pre-fills every field (edit mode). `detected_tabs` (add mode)
    offers the open Forge tabs so the user picks one and the hostname / URL /
    title fill in automatically — no manual URL typing.
    """

    def __init__(self, parent=None, *, existing: World | None = None, detected_tabs=None) -> None:
        super().__init__(parent)
        self._result: World | None = None
        self._last_url = existing.last_url if existing else ""
        self.setWindowTitle("Edit World" if existing else "Add World")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Prefill-from-tab picker (add mode only). Only real Forge tabs are offered.
        forge_tabs = [t for t in (detected_tabs or []) if is_forge_hostname(t.url)]
        self.detected_combo = None
        if existing is None and forge_tabs:
            self.detected_combo = QComboBox()
            self.detected_combo.addItem("— choose a scanned tab to prefill —", None)
            for tab in forge_tabs:
                self.detected_combo.addItem(f"{normalize_hostname(tab.url)} — {tab.title}", tab)
            self.detected_combo.currentIndexChanged.connect(self._on_detected_selected)
            form.addRow("Detected tab", self.detected_combo)

        self.alias_edit = QLineEdit(existing.alias if existing else "")
        self.alias_edit.setPlaceholderText("Main, Farm, H …")
        form.addRow("Alias (your name for it)", self.alias_edit)

        self.host_edit = QLineEdit(existing.hostname if existing else "")
        self.host_edit.setPlaceholderText("cz8.forgeofempires.com  (or paste the world URL)")
        form.addRow("Forge server (hostname)", self.host_edit)

        self.title_edit = QLineEdit(existing.title if existing else "")
        self.title_edit.setPlaceholderText("(auto-filled from the tab)")
        form.addRow("Detected title", self.title_edit)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 60000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setValue(existing.interval_ms if existing else 1000)
        form.addRow("Click cadence", self.interval_spin)

        self.maxweak_spin = QSpinBox()
        self.maxweak_spin.setRange(0, 100)
        self.maxweak_spin.setSingleStep(20)
        self.maxweak_spin.setSuffix(" %")
        self.maxweak_spin.setValue(existing.max_weakening_pct if existing else 100)
        form.addRow("Max weakening", self.maxweak_spin)

        pct_row = QWidget()
        pct_layout = QHBoxLayout(pct_row)
        pct_layout.setContentsMargins(0, 0, 0, 0)
        self.pct_boxes: dict[int, QCheckBox] = {}
        allowed = set(existing.allowed_pcts) if existing else set(BADGE_PCTS)
        for pct in BADGE_PCTS:
            box = QCheckBox(f"{pct}%")
            box.setChecked(pct in allowed)
            self.pct_boxes[pct] = box
            pct_layout.addWidget(box)
        pct_layout.addStretch(1)
        form.addRow("Allowed badge %", pct_row)

        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setObjectName("worldError")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_detected_selected(self) -> None:
        """Fill hostname / title / URL from the chosen scanned tab; leave alias
        for the user. Never overwrites an alias the user already typed."""
        tab = self.detected_combo.currentData() if self.detected_combo else None
        if tab is None:
            return
        self.host_edit.setText(normalize_hostname(tab.url))
        self.title_edit.setText(tab.title or "")
        self._last_url = tab.url

    def _build_world(self) -> World:
        allowed = tuple(p for p, box in self.pct_boxes.items() if box.isChecked())
        if not allowed:
            raise WorldError("Enable at least one allowed badge percentage.")
        return World(
            alias=self.alias_edit.text(),
            hostname=self.host_edit.text(),
            interval_ms=self.interval_spin.value(),
            max_weakening_pct=self.maxweak_spin.value(),
            allowed_pcts=allowed,
            title=self.title_edit.text().strip(),
            last_url=self._last_url,
        )

    def _on_accept(self) -> None:
        try:
            self._result = self._build_world()
        except WorldError as exc:
            # Keep the dialog open and explain what's wrong — no silent reject.
            self.error_label.setText(str(exc))
            return
        self.accept()

    def world(self) -> World | None:
        """The validated World, or None if the dialog was cancelled."""
        return self._result

    @staticmethod
    def get_world(parent, *, existing: World | None = None, detected_tabs=None) -> World | None:
        dialog = WorldDialog(parent, existing=existing, detected_tabs=detected_tabs)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.world()
        return None


def confirm_remove(parent, alias: str) -> bool:
    reply = QMessageBox.question(
        parent,
        "Remove World",
        f"Remove world “{alias}”?\n\nIts saved settings will be deleted. "
        "Your browser tab and login are not affected.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes


__all__ = ["WorldDialog", "confirm_remove"]
