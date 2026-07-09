"""Monitoring console main window.

A consumer of runtime reports and a sender of control commands — nothing
more. It receives a RuntimeService (control) and a QtReportBridge (signals)
by injection; it never builds an application, browser, session, rule, or
handler. All view updates run on the Qt thread because they are driven by
bridge signals delivered via queued connections.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bap.gui.dashboard import DashboardWidget
from bap.gui.qt_bridge import QtReportBridge
from bap.gui.report_view import log_line, row_for
from bap.gui.runtime_service import RuntimeService

_COLUMNS = ["Profile", "Status", "Last tick", "Rules", "Actions", "Error", "Timing", "Health"]
_HEALTH_COL = _COLUMNS.index("Health")


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: RuntimeService,
        bridge: QtReportBridge,
        *,
        on_close: Callable[[], None] | None = None,
        metrics_repository=None,
        max_memory_mb: int | None = None,
        max_pages: int | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._bridge = bridge
        self._on_close = on_close
        self._row_index: dict[str, int] = {}
        # Dashboard is optional: only shown when analytics history is available.
        self.dashboard = (
            DashboardWidget(metrics_repository, max_memory_mb=max_memory_mb, max_pages=max_pages)
            if metrics_repository is not None
            else None
        )

        self.setWindowTitle("Browser Automation Platform — Monitor")
        self._build_ui()
        self._build_menu()
        self._populate_sessions(service.profile_ids)
        self._connect_signals()
        self._apply_state("stopped")

    # --- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        monitor = QWidget()
        layout = QVBoxLayout(monitor)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.tick_button = QPushButton("Tick once")
        self.state_label = QLabel("stopped")
        self.state_label.setObjectName("stateLabel")
        for widget in (self.start_button, self.stop_button, self.tick_button):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(QLabel("Status:"))
        self.status_label = QLabel("stopped")
        self.status_label.setObjectName("statusLabel")
        controls.addWidget(self.status_label)
        controls.addWidget(QLabel("Runtime:"))
        controls.addWidget(self.state_label)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, stretch=2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)  # bounded live stream
        layout.addWidget(self.log, stretch=1)

        tabs.addTab(monitor, "Monitor")
        if self.dashboard is not None:
            tabs.addTab(self.dashboard, "Dashboard")
        self.setCentralWidget(tabs)

        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.tick_button.clicked.connect(self._on_tick_clicked)

    def _build_menu(self) -> None:
        # Non-developer entry points: install the browser, export diagnostics,
        # open the data folder — all without a command line. Each delegates to
        # the ops layer; the window holds no automation logic.
        bar = self.menuBar()
        tools = bar.addMenu("&Tools")
        tools.addAction("Install browser…", self._install_browser)
        tools.addAction("Export diagnostics…", self._export_diagnostics)
        tools.addSeparator()
        tools.addAction("Open data folder", self._open_data_folder)
        tools.addAction("Run first-run setup…", self._run_first_run)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction("About", self._about)

    def _install_browser(self) -> None:
        from bap.gui.first_run import BrowserInstallDialog

        BrowserInstallDialog(self).exec()

    def _export_diagnostics(self) -> None:
        from bap.ops.diagnostics import export_diagnostics

        try:
            path = export_diagnostics()
        except Exception as exc:  # never crash the UI over a diagnostics export
            QMessageBox.warning(self, "Diagnostics", f"Could not export diagnostics:\n{exc}")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Diagnostics exported")
        box.setText(f"Saved to:\n{path}")
        open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _open_data_folder(self) -> None:
        from bap.ops.paths import ensure_dirs, get_paths

        home = ensure_dirs(get_paths()).home
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(home)))

    def _run_first_run(self) -> None:
        from bap.gui.first_run import FirstRunDialog

        FirstRunDialog(self).exec()

    def _about(self) -> None:
        from bap import __version__

        QMessageBox.about(
            self,
            "About",
            f"<b>Browser Automation Platform</b><br>Version {__version__}<br><br>"
            "A generic, site-agnostic visual browser automation platform.",
        )

    def _populate_sessions(self, profile_ids) -> None:
        self.table.setRowCount(len(profile_ids))
        for row, profile_id in enumerate(profile_ids):
            self._row_index[profile_id] = row
            values = [profile_id, "idle", "-", "-", "-", "", "-", "healthy"]
            for col, text in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _connect_signals(self) -> None:
        # Queued delivery (cross-thread) guarantees these slots run on the UI thread.
        self._bridge.report_received.connect(self._on_report)
        self._bridge.state_changed.connect(self._apply_state)
        self._bridge.error_occurred.connect(self._on_error)
        self._bridge.health_changed.connect(self._on_health)
        self._bridge.status_changed.connect(self._apply_status)

    # --- control slots ------------------------------------------------------

    def _on_start_clicked(self) -> None:
        self._append_log("Starting runtime...")
        self._service.start_runtime()

    def _on_stop_clicked(self) -> None:
        self._append_log("Stopping runtime...")
        self._service.stop_runtime()

    def _on_tick_clicked(self) -> None:
        self._append_log("Running one manual tick...")
        self._service.tick_once()

    # --- report/state slots (UI thread) -------------------------------------

    def _on_report(self, report) -> None:
        row_data = row_for(report)
        row = self._row_index.get(row_data.profile_id)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._row_index[row_data.profile_id] = row
        cells = [
            row_data.profile_id,
            row_data.status,
            row_data.last_tick,
            row_data.rules,
            row_data.actions,
            row_data.error,
            row_data.timing,
        ]
        for col, text in enumerate(cells):
            self.table.setItem(row, col, QTableWidgetItem(text))
        if self.table.item(row, _HEALTH_COL) is None:  # new row: seed health, don't clobber
            self.table.setItem(row, _HEALTH_COL, QTableWidgetItem("healthy"))
        self._append_log(log_line(report))

    def _apply_state(self, state: str) -> None:
        self.state_label.setText(state)
        running = state == "running"
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.tick_button.setEnabled(not running)

    def _apply_status(self, status: str, reason: str) -> None:
        self.status_label.setText(status)
        self._append_log(f"STATUS -> {status}" + (f" ({reason})" if reason else ""))

    def _on_health(self, profile_id: str, health: str, reason: str) -> None:
        row = self._row_index.get(profile_id)
        if row is not None:
            self.table.setItem(row, _HEALTH_COL, QTableWidgetItem(health))
        self._append_log(f"HEALTH [{profile_id}] -> {health} ({reason})")

    def _on_error(self, message: str) -> None:
        self._append_log(f"ERROR: {message}")

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)

    # --- shutdown -----------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._service.stop_loop()
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)


__all__ = ["MainWindow"]
