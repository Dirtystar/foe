"""Scan-All summary window (observe-only).

Shows one row per attached World from a Scan-All run: capture status, weakening
read + decision, detector stage counts, and the selected candidate. It is a
diagnostic table — it never compares state across Worlds, never clicks, and never
sends keyboard input. Each row is tagged with its own World alias/hostname/tab so
results can never be confused between Worlds.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bap.forge.detection.testscan import SCAN_ALL_COLUMNS


class ScanAllSummaryWindow(QMainWindow):
    def __init__(self, results) -> None:
        super().__init__()
        self._results = list(results)
        self._debuggers = []
        self.setWindowTitle("Forge — Scan All Worlds  ·  OBSERVE ONLY")

        central = QWidget()
        root = QVBoxLayout(central)

        banner = QLabel("OBSERVE ONLY — NO CLICK PERFORMED · each World scanned independently")
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet("background:#a01818; color:white; font-weight:bold; padding:6px;")
        root.addWidget(banner)

        keys = [k for k, _ in SCAN_ALL_COLUMNS]
        headers = [h for _, h in SCAN_ALL_COLUMNS] + ["Open"]
        self.table = QTableWidget(len(self._results), len(keys) + 1)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for r, result in enumerate(self._results):
            row = result.row()
            for c, key in enumerate(keys):
                value = row.get(key)
                text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                if key == "capture" and value != "ok":
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(r, c, item)
            # Per-World "Open result" — proves this row came from that World's tab.
            btn = QPushButton("Open result")
            btn.setEnabled(result.image is not None and result.scan is not None)
            btn.clicked.connect(lambda _c=False, res=result: self._open_result(res))
            self.table.setCellWidget(r, len(keys), btn)
        root.addWidget(self.table)

        note = QLabel("Diagnostic only. No World's result depends on another's. "
                      "Real clicking stays disabled.")
        root.addWidget(note)
        self.setCentralWidget(central)

    def _open_result(self, result) -> None:
        """Open this World's own capture in the observe-only debugger."""
        from bap.gui.forge_debugger import DebuggerWindow, _bundled_classifier

        if result.image is None:
            return
        win = DebuggerWindow(result.image, world=None, classifier=_bundled_classifier(),
                             source=f"{result.alias} (scan-all)")
        win.resize(1280, 760)
        win.show()
        self._debuggers.append(win)


__all__ = ["ScanAllSummaryWindow"]
