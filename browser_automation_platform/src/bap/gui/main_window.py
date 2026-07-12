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
        capture_callback=None,
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
        # Returns PNG bytes for an assigned world tab (live read-only capture),
        # or None. Wired by the composition root; None in tests / offline.
        self._capture_callback = capture_callback
        self._debugger = None
        self._running = False
        self._pickers: dict[str, QComboBox] = {}
        self._selected_alias: str | None = None
        self._scanned_tabs = None  # last Scan result (list[BrowserTab]) or None
        self._browser_open = False
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

        # In Forge mode the runtime unit is a World, not a generic Profile
        # (profile_id stays internal). Relabel the activity table accordingly.
        columns = ["World" if c == "Profile" else c for c in _COLUMNS] if self._forge else _COLUMNS
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
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

    _WORLD_COLS = ["Alias", "Server", "Cadence", "Max weakening", "Allowed %", "Rules", "Actions"]

    def _build_forge_panel(self) -> QGroupBox:
        """The World Manager: persistent worlds, explicit browser lifecycle, and
        hostname reattachment. Worlds can be added/edited/removed live (no
        restart); each world gets a tab picker the moment it exists."""
        box = QGroupBox("Worlds")
        outer = QVBoxLayout(box)

        # P0-6: never let the user assume automation exists. This mode only
        # captures screenshots — no rules, no actions, nothing is clicked.
        self.forge_status = QLabel(
            "CAPTURE ONLY — NO RULES — NO ACTIONS.  Start captures screenshots "
            "of each world for inspection; nothing is clicked or changed."
        )
        self.forge_status.setObjectName("forgeStatus")
        self.forge_status.setWordWrap(True)
        self.forge_status.setStyleSheet("font-weight: bold; color: #b06a00;")
        outer.addWidget(self.forge_status)

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

        self.worlds_table = QTableWidget(0, len(self._WORLD_COLS))
        self.worlds_table.setHorizontalHeaderLabels(self._WORLD_COLS)
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

        # Test Scan (observe-only): an EXPLICIT World selector — the scan always
        # runs against the chosen World, never implicitly the first one. Live and
        # offline are separate actions; the file picker is never an implicit
        # fallback for a broken live mapping.
        scan_row = QHBoxLayout()
        scan_row.addWidget(QLabel("Test Scan World:"))
        self.test_scan_combo = QComboBox()
        self.test_scan_combo.currentIndexChanged.connect(self._on_test_scan_world_changed)
        scan_row.addWidget(self.test_scan_combo)
        self.test_scan_live_button = QPushButton("Test Scan Live World")
        self.test_scan_live_button.clicked.connect(self._on_test_scan_live)
        self.scan_all_button = QPushButton("Scan All Attached Worlds")
        self.scan_all_button.clicked.connect(self._on_scan_all)
        self.open_offline_button = QPushButton("Open Offline Screenshot…")
        self.open_offline_button.clicked.connect(self._on_open_offline)
        for widget in (self.test_scan_live_button, self.scan_all_button, self.open_offline_button):
            scan_row.addWidget(widget)
        scan_row.addStretch(1)
        outer.addLayout(scan_row)

        self.test_scan_target_label = QLabel("")
        self.test_scan_target_label.setObjectName("testScanTarget")
        self.test_scan_target_label.setWordWrap(True)
        outer.addWidget(self.test_scan_target_label)

        # Per-world tab pickers live in a rebuildable form so add/remove updates
        # the picker set immediately, with no restart.
        self._pickers_form = QFormLayout()
        outer.addLayout(self._pickers_form)

        self.open_browser_button.clicked.connect(self._on_open_browser_clicked)
        self.close_browser_button.clicked.connect(self._on_close_browser_clicked)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        self.add_world_button.clicked.connect(self._on_add_world)
        self.edit_world_button.clicked.connect(self._on_edit_world)
        self.remove_world_button.clicked.connect(self._on_remove_world)
        self._refresh_worlds_table()
        self._rebuild_pickers()
        self._refresh_test_scan_combo()
        return box

    def _current_test_scan_alias(self) -> str | None:
        """The World explicitly chosen for Test Scan — never the first by
        default."""
        combo = getattr(self, "test_scan_combo", None)
        if combo is None or combo.count() == 0:
            return None
        return combo.currentData()

    def _refresh_test_scan_combo(self) -> None:
        """Rebuild the Test Scan World selector from the current world set,
        preserving the selection, and enable Live only for the attached World.
        Called whenever worlds, tabs, or browser state change so the selector can
        never point at a stale World or tab."""
        combo = getattr(self, "test_scan_combo", None)
        if combo is None:
            return
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for alias in self._world_aliases():
            combo.addItem(alias, alias)
        if previous is not None:
            idx = combo.findData(previous)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self._on_test_scan_world_changed()

    def _resolve_test_scan_target(self, alias):
        from bap.forge.detection.testscan import resolve_target

        return resolve_target(alias, world_store=self._world_store,
                              assignment=self._assignment, browser_open=self._browser_open)

    def _on_test_scan_world_changed(self, *_args) -> None:
        alias = self._current_test_scan_alias()
        has_worlds = alias is not None
        if not has_worlds:
            self.test_scan_target_label.setText("No worlds yet — add a World to Test Scan.")
            self.test_scan_live_button.setEnabled(False)
            self.scan_all_button.setEnabled(bool(self._attached_aliases()))
            return
        target = self._resolve_test_scan_target(alias)
        self.test_scan_target_label.setText(target.summary())
        self.test_scan_live_button.setEnabled(target.attached)
        self.scan_all_button.setEnabled(bool(self._attached_aliases()))

    def _attached_aliases(self) -> list[str]:
        from bap.forge.detection.testscan import attached_aliases

        return attached_aliases(world_store=self._world_store, assignment=self._assignment,
                                browser_open=self._browser_open)

    def _on_test_scan_live(self) -> None:
        """Capture the EXPLICITLY selected World's live tab and open the
        observe-only debugger. If that World is not attached, show a clear error —
        never open a file picker, never scan another World."""
        from bap.forge.detection.testscan import capture_world_image

        alias = self._current_test_scan_alias()
        if alias is None:
            QMessageBox.warning(self, "Test Scan", "No World selected.")
            return
        world = self._world_store.get(alias) if self._world_store else None
        img, err = capture_world_image(
            alias, world_store=self._world_store, assignment=self._assignment,
            browser_open=self._browser_open, capture_callback=self._capture_callback,
        )
        if img is None:
            QMessageBox.warning(self, "Test Scan (live)",
                                f"Cannot live-scan World “{alias}”:\n{err}\n\n"
                                "Use “Open Offline Screenshot…” to review a saved image instead.")
            return
        self._append_log(f"Live Test Scan of World “{alias}”.")
        self._open_debugger(img, world=world, source=f"{alias} (live)")

    def _on_open_offline(self) -> None:
        """Explicitly review a saved screenshot. Has no effect on any World's live
        tab assignment — it is a separate action, never a live-scan fallback."""
        import cv2
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "Open offline Forge screenshot", "", "PNG (*.png)")
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            QMessageBox.warning(self, "Open Offline Screenshot", "Could not load that image.")
            return
        # Use the selected World's settings for context only; assignment untouched.
        alias = self._current_test_scan_alias()
        world = self._world_store.get(alias) if (alias and self._world_store) else None
        self._open_debugger(img, world=world, source=path.rsplit("/", 1)[-1] + " (offline)")

    def _on_scan_all(self) -> None:
        """Scan every attached World independently and open a summary table."""
        from bap.forge.detection.testscan import scan_all_attached
        from bap.gui.forge_debugger import _bundled_classifier

        if not self._attached_aliases():
            QMessageBox.information(self, "Scan All Worlds",
                                    "No attached Worlds. Open the browser and Scan && Reattach first.")
            return
        results = scan_all_attached(
            world_store=self._world_store, assignment=self._assignment,
            browser_open=self._browser_open, capture_callback=self._capture_callback,
            classifier=_bundled_classifier(), calibration=self._forge_calibration(),
            artifacts_root=self._scan_all_artifacts_root(),
        )
        saved = sum(1 for r in results if r.artifacts_dir)
        self._append_log(f"Scan All: {len(results)} attached World(s) scanned independently"
                         f"{f'; artifacts saved for {saved}' if saved else ''}.")
        self._open_scan_all_summary(results)

    def _scan_all_artifacts_root(self):
        """Where Scan All writes per-World artifacts (scan_all/<ts>/<alias>/)."""
        try:
            from bap.ops.paths import ensure_dirs, get_paths

            return ensure_dirs(get_paths()).data_dir / "forge" / "scan_all"
        except Exception:
            return None

    def _open_scan_all_summary(self, results) -> None:
        from bap.gui.forge_scan_all import ScanAllSummaryWindow

        self._scan_all_window = ScanAllSummaryWindow(results)
        self._scan_all_window.resize(1200, 360)
        self._scan_all_window.show()

    def _open_debugger(self, image, *, world=None, source: str = "") -> None:
        from bap.gui.forge_debugger import DebuggerWindow, _bundled_classifier
        from bap.forge.detection.geometry import CaptureGeometry, derive_rois

        geometry = CaptureGeometry.from_image(image)
        self._debugger = DebuggerWindow(
            image, world=world, classifier=_bundled_classifier(), source=source,
            geometry=geometry, rois=derive_rois(geometry, self._forge_calibration()),
        )
        self._debugger.resize(1280, 760)
        self._debugger.show()

    def _forge_calibration(self):
        """The per-user Forge calibration (weakening + battle-map regions),
        persisted by the Debugger's Set-Region tools. None if unavailable."""
        try:
            from bap.forge.detection.calibration import WeakeningCalibration
            from bap.ops.paths import ensure_dirs, get_paths

            path = ensure_dirs(get_paths()).data_dir / "forge" / "calibration.json"
            return WeakeningCalibration.load(path)
        except Exception:
            return None

    def _world_aliases(self) -> list[str]:
        return self._world_store.aliases() if self._world_store is not None else []

    def _refresh_worlds_table(self) -> None:
        worlds = self._world_store.list() if self._world_store is not None else []
        self.worlds_table.setRowCount(len(worlds))
        for r, world in enumerate(worlds):
            cells = [
                world.alias,
                world.hostname,
                f"{world.interval_ms} ms",
                str(world.max_weakening),
                "/".join(str(p) for p in world.allowed_pcts),
                "0",  # rules configured — capture-only
                "0",  # actions configured — capture-only
            ]
            for c, text in enumerate(cells):
                self.worlds_table.setItem(r, c, QTableWidgetItem(text))

    def _rebuild_pickers(self) -> None:
        """Rebuild the per-world tab pickers from the current world set. Called
        on launch and after every add/remove so a new world gets its picker
        immediately. Restores tab selections from the last scan if there was one."""
        while self._pickers_form.rowCount():
            self._pickers_form.removeRow(0)
        self._pickers = {}
        aliases = self._world_aliases()
        if not aliases:
            self._pickers_form.addRow(QLabel("No worlds yet — click “Add World…”."))
            self._update_start_gate()
            return
        for alias in aliases:
            combo = QComboBox()
            combo.setEnabled(False)
            combo.addItem("— scan to reattach —", None)
            combo.currentIndexChanged.connect(lambda _i, a=alias: self._on_tab_selected(a))
            self._pickers[alias] = combo
            self._pickers_form.addRow(QLabel(f"World “{alias}” — tab"), combo)
        if self._scanned_tabs is not None:
            self._apply_scanned_to_pickers()
        self._update_start_gate()
        self._refresh_test_scan_combo()

    def _on_world_selection_changed(self) -> None:
        rows = self.worlds_table.selectionModel().selectedRows()
        self._selected_alias = (
            self.worlds_table.item(rows[0].row(), 0).text() if rows else None
        )
        self.edit_world_button.setEnabled(self._selected_alias is not None)
        self.remove_world_button.setEnabled(self._selected_alias is not None)

    def _on_add_world(self) -> None:
        from bap.forge.config import forge_session_spec
        from bap.forge.worlds import WorldError
        from bap.gui.forge_panel import WorldDialog

        # Prefill from a scanned tab so the user never types a URL (P0-2).
        world = WorldDialog.get_world(self, detected_tabs=self._scanned_tabs)
        if world is None:
            return
        try:
            self._world_store.add(world)
        except WorldError as exc:
            QMessageBox.warning(self, "Add World", str(exc))
            return
        # Live plan update + immediate picker (P0-3) — no restart.
        self._service.add_world_session(forge_session_spec(world))
        self._refresh_worlds_table()
        self._rebuild_pickers()
        self._append_log(f"Added world “{world.alias}” ({world.hostname}). Saved.")

    def _on_edit_world(self) -> None:
        from bap.forge.config import forge_session_spec
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
        old_alias = self._selected_alias
        try:
            self._world_store.update(old_alias, world)
        except WorldError as exc:
            QMessageBox.warning(self, "Edit World", str(exc))
            return
        # Apply live. An alias rename is a remove+add of the plan entry; a
        # settings change (e.g. cadence) rebuilds the running session in place.
        if world.alias != old_alias:
            self._service.remove_world_session(old_alias)
            self._service.add_world_session(forge_session_spec(world))
        else:
            self._service.edit_world_session(forge_session_spec(world))
        self._selected_alias = None
        self._refresh_worlds_table()
        self._rebuild_pickers()
        self._append_log(f"Updated world “{world.alias}”. Saved.")

    def _on_remove_world(self) -> None:
        from bap.gui.forge_panel import confirm_remove

        if not self._selected_alias:
            return
        if not confirm_remove(self, self._selected_alias):
            return
        alias = self._selected_alias
        self._world_store.remove(alias)
        # Drop its session (never its browser tab) live (P0-3).
        self._service.remove_world_session(alias)
        self._selected_alias = None
        self._refresh_worlds_table()
        self._rebuild_pickers()
        self._append_log(f"Removed world “{alias}” (browser tab kept). Saved.")

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
        self._browser_open = False
        self.open_browser_button.setEnabled(True)
        self.open_browser_button.setText("Open Browser")
        self.scan_button.setEnabled(False)
        if hasattr(self, "close_browser_button"):
            self.close_browser_button.setEnabled(False)
        self.attended_hint.setText("Browser closed. Open it again to reconnect your worlds.")
        self._append_log("Browser closed.")
        self._refresh_test_scan_combo()

    def _on_forge_tabs_scanned(self, tabs) -> None:
        """Remember the scan (also used to prefill Add World), then auto-reattach
        worlds to open tabs by Forge hostname (never tab id)."""
        self._scanned_tabs = list(tabs)
        self._apply_scanned_to_pickers()

    def _apply_scanned_to_pickers(self) -> None:
        """Auto-match the remembered scan to the current world set by hostname and
        populate the fallback pickers with matches preselected."""
        tabs = self._scanned_tabs or []
        matched = 0
        if self._world_store is not None and self._assignment is not None:
            for alias, tab in self._world_store.match_tabs(tabs).items():
                if alias in self._pickers:
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
        self._browser_open = True
        self.scan_button.setEnabled(True)
        self.open_browser_button.setText("Browser open")
        self.open_browser_button.setEnabled(False)
        if hasattr(self, "close_browser_button"):
            self.close_browser_button.setEnabled(True)
        self.attended_hint.setText("Open your pages, then Scan.")
        self._append_log("Browser open. Open your pages, then Scan.")
        self._refresh_test_scan_combo()

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
        self._refresh_test_scan_combo()

    def _update_start_gate(self) -> None:
        idle = not self._running
        assigned = True
        if self._attended:
            # Forge's source of truth is the World store (worlds change live);
            # generic attended mode uses the fixed launch profile set.
            profile_ids = self._world_aliases() if self._forge else list(self._service.profile_ids)
            # Nothing to run if there are no worlds/sessions.
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
        # P0-4: never silently close managed Chromium on exit. If a browser we
        # opened is still up, ask — and default to keeping it open (preserving
        # tabs and login). Stop always means automation-only; only an explicit
        # choice here tears the browser down.
        close_browser = True
        if self._forge and self._browser_open:
            choice = self._ask_exit_choice()
            if choice == "cancel":
                event.ignore()
                return
            close_browser = choice == "both"

        try:
            future = (
                self._service.shutdown_runtime() if close_browser else self._service.stop_runtime()
            )
            future.result(timeout=10.0)
        except Exception:  # a failed teardown must not block the window closing
            pass
        self._service.stop_loop()
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)

    def _ask_exit_choice(self) -> str:
        """Return 'keep' (close assistant, keep Chromium), 'both', or 'cancel'."""
        box = QMessageBox(self)
        box.setWindowTitle("Close assistant")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Chromium is still open with your worlds and login.")
        box.setInformativeText("What would you like to do?")
        keep_btn = box.addButton("Keep Chromium open", QMessageBox.ButtonRole.AcceptRole)
        both_btn = box.addButton("Close assistant and Chromium", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_btn)  # default keeps the browser open
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return "cancel"
        if clicked is both_btn:
            return "both"
        return "keep"


__all__ = ["MainWindow"]
