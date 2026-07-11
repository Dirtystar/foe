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
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
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
        attended: bool = False,
        assignment=None,
        forge: bool = False,
        world_store=None,
    ) -> None:
        super().__init__()
        self._service = service
        self._bridge = bridge
        self._on_close = on_close
        # Forge mode is the product surface: a persistent World Manager. It is a
        # specialisation of attended mode (the user drives a real browser), so it
        # reuses the tab-assignment/start-gating machinery and adds world CRUD +
        # hostname reattachment on top.
        self._forge = forge
        self._attended = attended or forge
        self._assignment = assignment
        self._world_store = world_store
        self._running = False
        self._pickers: dict[str, QComboBox] = {}
        self._selected_alias: str | None = None
        self._row_index: dict[str, int] = {}
        # Dashboard is optional: only shown when analytics history is available.
        self.dashboard = (
            DashboardWidget(metrics_repository, max_memory_mb=max_memory_mb, max_pages=max_pages)
            if metrics_repository is not None
            else None
        )

        title = (
            "Forge of Empires Assistant" if forge else "Browser Automation Platform — Monitor"
        )
        self.setWindowTitle(title)
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

        if self._forge:
            layout.addWidget(self._build_forge_panel())
        elif self._attended:
            layout.addWidget(self._build_attended_panel())

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

    # --- attended browser panel ---------------------------------------------

    def _build_attended_panel(self) -> QGroupBox:
        """Open Browser → Scan tabs → assign a tab to each session. The window
        only collects the choice; adopting the tab happens in the runtime."""
        box = QGroupBox("Attended browser — assign a tab to each session")
        outer = QVBoxLayout(box)

        row = QHBoxLayout()
        self.open_browser_button = QPushButton("Open Browser")
        self.scan_button = QPushButton("Scan tabs")
        self.scan_button.setEnabled(False)  # enabled once the browser is open
        self.attended_hint = QLabel("Open the browser, open your pages, then scan.")
        self.attended_hint.setObjectName("attendedHint")
        row.addWidget(self.open_browser_button)
        row.addWidget(self.scan_button)
        row.addWidget(self.attended_hint)
        row.addStretch(1)
        outer.addLayout(row)

        form = QFormLayout()
        for profile_id in self._service.profile_ids:
            combo = QComboBox()
            combo.setEnabled(False)
            combo.addItem("— scan tabs first —", None)
            combo.currentIndexChanged.connect(
                lambda _i, pid=profile_id: self._on_tab_selected(pid)
            )
            self._pickers[profile_id] = combo
            form.addRow(QLabel(f"Session “{profile_id}”"), combo)
        outer.addLayout(form)

        self.open_browser_button.clicked.connect(self._on_open_browser_clicked)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        return box

    # --- Forge World Manager (primary product UI) ---------------------------

    def _build_forge_panel(self) -> QGroupBox:
        """The World Manager: persistent worlds + explicit browser lifecycle +
        hostname reattachment. The runnable set (per-world tab pickers) is the
        worlds present at launch — service.profile_ids; world CRUD edits the
        persistent store and takes effect on the next launch."""
        box = QGroupBox("Worlds")
        outer = QVBoxLayout(box)

        row = QHBoxLayout()
        self.open_browser_button = QPushButton("Open Browser")
        self.close_browser_button = QPushButton("Close Browser")
        self.close_browser_button.setEnabled(False)
        self.scan_button = QPushButton("Scan && Reattach")
        self.scan_button.setEnabled(False)
        self.attended_hint = QLabel("Open the browser, log in to your worlds, then Scan && Reattach.")
        self.attended_hint.setObjectName("attendedHint")
        for widget in (self.open_browser_button, self.close_browser_button, self.scan_button):
            row.addWidget(widget)
        row.addWidget(self.attended_hint)
        row.addStretch(1)
        outer.addLayout(row)

        self.worlds_table = QTableWidget(0, 5)
        self.worlds_table.setHorizontalHeaderLabels(
            ["Alias", "Server", "Cadence", "Max weakening", "Allowed %"]
        )
        self.worlds_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.worlds_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.worlds_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.worlds_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.worlds_table.itemSelectionChanged.connect(self._on_world_selection_changed)
        outer.addWidget(self.worlds_table)

        crud = QHBoxLayout()
        self.add_world_button = QPushButton("Add World…")
        self.edit_world_button = QPushButton("Edit…")
        self.remove_world_button = QPushButton("Remove")
        self.edit_world_button.setEnabled(False)
        self.remove_world_button.setEnabled(False)
        for widget in (self.add_world_button, self.edit_world_button, self.remove_world_button):
            crud.addWidget(widget)
        crud.addStretch(1)
        outer.addLayout(crud)

        # Per-world tab assignment for the launch-time set. Auto-filled by
        # hostname on scan; the combo is the manual fallback.
        if self._service.profile_ids:
            form = QFormLayout()
            for alias in self._service.profile_ids:
                combo = QComboBox()
                combo.setEnabled(False)
                combo.addItem("— scan to reattach —", None)
                combo.currentIndexChanged.connect(lambda _i, a=alias: self._on_tab_selected(a))
                self._pickers[alias] = combo
                form.addRow(QLabel(f"World “{alias}” — tab"), combo)
            outer.addLayout(form)
        else:
            outer.addWidget(
                QLabel("No worlds are connected yet. Add a world, then relaunch to run it.")
            )

        self.open_browser_button.clicked.connect(self._on_open_browser_clicked)
        self.close_browser_button.clicked.connect(self._on_close_browser_clicked)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        self.add_world_button.clicked.connect(self._on_add_world)
        self.edit_world_button.clicked.connect(self._on_edit_world)
        self.remove_world_button.clicked.connect(self._on_remove_world)
        self._refresh_worlds_table()
        return box

    def _refresh_worlds_table(self) -> None:
        worlds = self._world_store.list() if self._world_store is not None else []
        self.worlds_table.setRowCount(len(worlds))
        for r, world in enumerate(worlds):
            cells = [
                world.alias,
                world.hostname,
                f"{world.interval_ms} ms",
                f"{world.max_weakening_pct}%",
                "/".join(str(p) for p in world.allowed_pcts),
            ]
            for c, text in enumerate(cells):
                self.worlds_table.setItem(r, c, QTableWidgetItem(text))

    def _on_world_selection_changed(self) -> None:
        rows = self.worlds_table.selectionModel().selectedRows()
        self._selected_alias = (
            self.worlds_table.item(rows[0].row(), 0).text() if rows else None
        )
        self.edit_world_button.setEnabled(self._selected_alias is not None)
        self.remove_world_button.setEnabled(self._selected_alias is not None)

    def _on_add_world(self) -> None:
        from bap.forge.worlds import WorldError
        from bap.gui.forge_panel import WorldDialog

        world = WorldDialog.get_world(self)
        if world is None:
            return
        try:
            self._world_store.add(world)
        except WorldError as exc:
            QMessageBox.warning(self, "Add World", str(exc))
            return
        self._refresh_worlds_table()
        self._append_log(f"Added world “{world.alias}” ({world.hostname}). Saved.")
        if world.alias not in self._pickers:
            self._append_log("New worlds connect on the next launch.")

    def _on_edit_world(self) -> None:
        from bap.forge.worlds import WorldError
        from bap.gui.forge_panel import WorldDialog

        if not self._selected_alias:
            return
        existing = self._world_store.get(self._selected_alias)
        if existing is None:
            return
        world = WorldDialog.get_world(self, existing=existing)
        if world is None:
            return
        try:
            self._world_store.update(self._selected_alias, world)
        except WorldError as exc:
            QMessageBox.warning(self, "Edit World", str(exc))
            return
        self._refresh_worlds_table()
        self._append_log(f"Updated world “{world.alias}”. Saved.")

    def _on_remove_world(self) -> None:
        from bap.gui.forge_panel import confirm_remove

        if not self._selected_alias:
            return
        if not confirm_remove(self, self._selected_alias):
            return
        alias = self._selected_alias
        self._world_store.remove(alias)
        self._selected_alias = None
        self._refresh_worlds_table()
        self._append_log(f"Removed world “{alias}”. Saved.")

    def _on_close_browser_clicked(self) -> None:
        self._append_log("Closing browser…")
        self.close_browser_button.setEnabled(False)
        future = self._service.close_browser()
        future.add_done_callback(self._browser_close_done)

    def _browser_close_done(self, future) -> None:
        try:
            future.result()
        except Exception as exc:
            self._bridge.error_occurred.emit(f"Could not close browser: {exc}")
            return
        self._bridge.browser_closed.emit()

    def _on_browser_closed(self) -> None:
        self.open_browser_button.setEnabled(True)
        self.open_browser_button.setText("Open Browser")
        self.scan_button.setEnabled(False)
        if hasattr(self, "close_browser_button"):
            self.close_browser_button.setEnabled(False)
        self.attended_hint.setText("Browser closed. Open it again to reconnect your worlds.")
        self._append_log("Browser closed.")

    def _on_forge_tabs_scanned(self, tabs) -> None:
        """Auto-reattach worlds to open tabs by Forge hostname (never tab id),
        then populate the manual-fallback pickers with the matches preselected."""
        tabs = list(tabs)
        matched = 0
        if self._world_store is not None and self._assignment is not None:
            for alias, tab in self._world_store.match_tabs(tabs).items():
                if alias in self._pickers:  # only the runnable (launch-time) set
                    self._assignment.assign(alias, tab)
                    matched += 1
        self._populate_tab_pickers(tabs)
        self.attended_hint.setText(
            f"{len(tabs)} tab(s) found — {matched} world(s) auto-reattached by hostname. "
            "Adjust any manually below."
        )

    def _on_open_browser_clicked(self) -> None:
        self._append_log("Opening browser…")
        self.open_browser_button.setEnabled(False)
        future = self._service.open_browser()
        future.add_done_callback(self._browser_open_done)

    def _browser_open_done(self, future) -> None:
        # Runs on the runtime thread; hop to the UI thread via signals.
        try:
            future.result()
        except Exception as exc:  # surfaced, never raised into the thread
            self._bridge.error_occurred.emit(f"Could not open browser: {exc}")
            return
        self._bridge.browser_ready.emit()

    def _on_browser_ready(self) -> None:
        self.scan_button.setEnabled(True)
        self.open_browser_button.setText("Browser open")
        self.open_browser_button.setEnabled(False)
        if hasattr(self, "close_browser_button"):
            self.close_browser_button.setEnabled(True)
        self.attended_hint.setText("Open your pages, then Scan.")
        self._append_log("Browser open. Open your pages, then Scan.")

    def _on_scan_clicked(self) -> None:
        self._append_log("Scanning open tabs…")
        future = self._service.scan_tabs()
        future.add_done_callback(self._scan_done)

    def _scan_done(self, future) -> None:
        try:
            tabs = future.result()
        except Exception as exc:
            self._bridge.error_occurred.emit(f"Could not scan tabs: {exc}")
            return
        self._bridge.tabs_scanned.emit(tabs)

    def _populate_tab_pickers(self, tabs) -> None:
        tabs = list(tabs)
        self.attended_hint.setText(f"{len(tabs)} tab(s) found — pick one per session.")
        for profile_id, combo in self._pickers.items():
            previous = self._assignment.get(profile_id) if self._assignment else None
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— select tab —", None)
            selected_index = 0
            for i, tab in enumerate(tabs, start=1):
                label = f"{tab.title or tab.url} — {tab.url}"
                combo.addItem(label, tab)
                if previous is not None and previous.tab_id == tab.tab_id:
                    selected_index = i
            combo.setCurrentIndex(selected_index)
            combo.setEnabled(True)
            combo.blockSignals(False)
            self._on_tab_selected(profile_id)  # sync assignment with the shown value

    def _on_tab_selected(self, profile_id: str) -> None:
        if self._assignment is None:
            return
        tab = self._pickers[profile_id].currentData()
        if tab is None:
            self._assignment.clear(profile_id)
        else:
            self._assignment.assign(profile_id, tab)
        self._update_start_gate()

    def _update_start_gate(self) -> None:
        idle = not self._running
        assigned = True
        if self._attended:
            profile_ids = list(self._service.profile_ids)
            # In forge mode with no worlds at launch there is nothing to run.
            has_sessions = bool(profile_ids)
            assigned = (
                has_sessions
                and self._assignment is not None
                and self._assignment.all_assigned(profile_ids)
            )
        self.start_button.setEnabled(idle and assigned)
        self.tick_button.setEnabled(idle and assigned)

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
        if self._forge:
            self._bridge.browser_ready.connect(self._on_browser_ready)
            self._bridge.browser_closed.connect(self._on_browser_closed)
            self._bridge.tabs_scanned.connect(self._on_forge_tabs_scanned)
        elif self._attended:
            self._bridge.browser_ready.connect(self._on_browser_ready)
            self._bridge.tabs_scanned.connect(self._populate_tab_pickers)

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
        self._running = state == "running"
        self.stop_button.setEnabled(self._running)
        self._update_start_gate()  # Start/Tick also respect the attended gate

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
        # Exit performs the full graceful teardown that Stop deliberately does
        # not: stop automation AND close the browser window. Best-effort and
        # bounded so a hung teardown can never wedge the app-close.
        try:
            future = self._service.shutdown_runtime()
            future.result(timeout=10.0)
        except Exception:  # a failed teardown must not block the window closing
            pass
        self._service.stop_loop()
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)


__all__ = ["MainWindow"]
