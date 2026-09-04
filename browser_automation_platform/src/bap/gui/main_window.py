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
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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
        browser_settings=None,
    ) -> None:
        super().__init__()
        self._service = service
        self._bridge = bridge
        self._on_close = on_close
        # Browser mode (Milestone 4.16): Managed Chromium (default) vs External
        # Chrome (CDP). Persisted; drives the Worlds-page connection UI, the exit
        # prompt, and the browser provenance stamped onto captures/snapshots.
        if browser_settings is None:
            from bap.forge.browser_settings import BrowserSettings

            browser_settings = BrowserSettings()
        self._browser_settings = browser_settings
        self._external_chrome = getattr(browser_settings, "is_external", False)
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
        # Widgets are created once (shared across shells) so every existing
        # attribute, signal, and handler is preserved; only their arrangement and
        # styling change (Milestone 4.8 — presentation only).
        self._build_runtime_controls()
        self._build_activity_widgets()
        if self._forge:
            self.setCentralWidget(self._build_forge_shell())
        else:
            self.setCentralWidget(self._build_classic_shell())

        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.tick_button.clicked.connect(self._on_tick_clicked)

    def _build_runtime_controls(self) -> None:
        self.start_button = QPushButton("Start"); self.start_button.setProperty("primary", True)
        self.stop_button = QPushButton("Stop"); self.stop_button.setProperty("danger", True)
        self.tick_button = QPushButton("Tick once")
        self.state_label = QLabel("stopped"); self.state_label.setObjectName("stateLabel")
        self.status_label = QLabel("stopped"); self.status_label.setObjectName("statusLabel")

    def _build_activity_widgets(self) -> None:
        # In Forge mode the runtime unit is a World, not a generic Profile.
        columns = ["World" if c == "Profile" else c for c in _COLUMNS] if self._forge else _COLUMNS
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)  # bounded live stream

    # --- classic shell (generic monitor / attended mode) --------------------

    def _build_classic_shell(self) -> QWidget:
        tabs = QTabWidget()
        monitor = QWidget()
        layout = QVBoxLayout(monitor)
        controls = QHBoxLayout()
        for widget in (self.start_button, self.stop_button, self.tick_button):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(QLabel("Status:")); controls.addWidget(self.status_label)
        controls.addWidget(QLabel("Runtime:")); controls.addWidget(self.state_label)
        layout.addLayout(controls)
        if self._attended:
            layout.addWidget(self._build_attended_panel())
        layout.addWidget(self.table, stretch=2)
        layout.addWidget(self.log, stretch=1)
        tabs.addTab(monitor, "Monitor")
        if self.dashboard is not None:
            tabs.addTab(self.dashboard, "Dashboard")
        return tabs

    # --- Forge desktop shell (nav rail + toolbar + pages + footer) ----------

    def _build_forge_shell(self) -> QWidget:
        from bap.gui import widgets

        root = QWidget(); root.setObjectName("appRoot")
        v = QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        v.addWidget(self._build_title_bar())

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        # The nav is split by audience: everyday "Play" actions a user needs, kept
        # separate from "Developer" tools (validation, performance, reports) so the
        # common path stays uncluttered. Every page is unchanged — only grouped.
        self._nav = widgets.NavRail()
        self._nav.add_header("Overview")
        self._nav.add_section("dashboard", "Dashboard", "compass")
        self._nav.add_header("Play")
        for key, label, ic in (("worlds", "Worlds", "shield"), ("vision", "Vision", "eye"),
                               ("review", "Review", "quill"),
                               ("datasets", "Datasets", "datasets")):
            self._nav.add_section(key, label, ic)
        self._nav.add_header("Developer")
        for key, label, ic in (("validation", "Validation", "check"),
                               ("performance", "Performance", "chart"),
                               ("reports", "Reports", "report")):
            self._nav.add_section(key, label, ic)
        self._nav.add_header("System")
        self._nav.add_section("settings", "Settings", "gear")
        self._nav.section_changed.connect(self._show_page)
        body.addWidget(self._nav)

        self._stack = QStackedWidget()
        self._pages: dict[str, int] = {}
        for key, builder in (("dashboard", self._build_dashboard_page),
                             ("worlds", self._build_worlds_page),
                             ("vision", self._build_vision_page),
                             ("validation", self._build_validation_page),
                             ("review", self._build_review_page),
                             ("datasets", self._build_datasets_page),
                             ("reports", self._build_reports_page),
                             ("performance", self._build_performance_page),
                             ("settings", self._build_settings_page)):
            self._pages[key] = self._stack.addWidget(self._scrolled(builder()))
        body.addWidget(self._stack, stretch=1)
        v.addLayout(body, stretch=1)

        v.addWidget(self._build_footer())
        # Populate now that every page's widgets exist. The tab pickers refresh
        # the Test Scan combo, which lives on the Vision page, so this must run
        # after all pages are built — hence here rather than in a page builder.
        self._refresh_worlds_table()
        self._rebuild_pickers()
        self._nav.select("dashboard")
        self._refresh_dashboard()
        return root

    def _scrolled(self, inner: QWidget) -> QWidget:
        area = QScrollArea(); area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame); area.setObjectName("page")
        area.setWidget(inner)
        return area

    def _show_page(self, key: str) -> None:
        if key in getattr(self, "_pages", {}):
            self._stack.setCurrentIndex(self._pages[key])
        # The Performance page live-refreshes only while it is the visible page,
        # so its timer never runs in the background or during unrelated tests.
        perf = getattr(self, "_perf_page", None)
        if perf is not None:
            if key == "performance":
                perf.refresh()
                perf.start_live()
            else:
                perf.stop_live()
        val = getattr(self, "_validation_page", None)
        if val is not None and key == "validation":
            val.refresh_worlds()

    def _build_title_bar(self) -> QWidget:
        from bap.gui import icons, widgets

        bar = QFrame(); bar.setObjectName("titleBar"); bar.setFixedHeight(46)
        h = QHBoxLayout(bar); h.setContentsMargins(16, 0, 16, 0); h.setSpacing(10)
        mark = QLabel(); mark.setPixmap(icons.icon("shield", stroke="#C89B5E", size=22).pixmap(22, 22))
        h.addWidget(mark)
        h.addWidget(widgets.display_title("Forge Assistant"))
        sub = widgets.muted("· Vision Console"); h.addWidget(sub)
        h.addStretch(1)
        self._safety_chip = QLabel("OBSERVE ONLY · read-only")
        self._safety_chip.setStyleSheet("color:#5FB98A; font-size:12px; font-weight:600;")
        h.addWidget(self._safety_chip)
        return bar

    def _build_footer(self) -> QWidget:
        bar = QFrame(); bar.setObjectName("footerBar"); bar.setFixedHeight(30)
        h = QHBoxLayout(bar); h.setContentsMargins(16, 0, 16, 0); h.setSpacing(14)
        obs = QLabel("● OBSERVE ONLY — NO CLICK PERFORMED")
        obs.setStyleSheet("color:#5FB98A; font-weight:700; font-size:11px;")
        h.addWidget(obs)
        h.addStretch(1)
        self._footer_status = QLabel("")
        self._footer_status.setStyleSheet("color:#9C93A6; font-size:11px;")
        h.addWidget(self._footer_status)
        sep = QLabel("·"); sep.setStyleSheet("color:#6E6678;"); h.addWidget(sep)
        base = QLabel("baseline forge-m4-stable")
        base.setStyleSheet("color:#6E6678; font-size:11px;")
        h.addWidget(base)
        return bar

    def _build_menu(self) -> None:
        # Non-developer entry points: install the browser, export diagnostics,
        # open the data folder — all without a command line. Each delegates to
        # the ops layer; the window holds no automation logic.
        bar = self.menuBar()
        tools = bar.addMenu("&Tools")
        tools.addAction("Live Data Collection…", self._open_live_collection)
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

    def _open_live_collection(self) -> None:
        """Open the Live Data Collection window (Milestone 5D) — read-only capture
        across Worlds into the canonical dataset. Never clicks or moves the cursor."""
        from bap.gui.forge_collection import ForgeCollectionWindow

        mode = self.browser_mode_combo.currentData() if hasattr(self, "browser_mode_combo") else "unknown"
        self._collection_window = ForgeCollectionWindow(
            world_store=self._world_store, assignment=self._assignment,
            capture_callback=self._capture_callback, browser_open=self._browser_open,
            browser_mode=str(mode),
        )
        self._collection_window.show()

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

    # Each nav section is one page. The widgets, signal wiring, and handlers are
    # identical to the previous single-panel layout — only their arrangement into
    # cards/pages changes (Milestone 4.8 — presentation only). Populating refresh
    # calls run once in `_build_forge_shell` after every page's widgets exist.

    def _build_dashboard_page(self) -> QWidget:
        """Overview: KPI tiles, runtime controls, live activity table and log."""
        from bap.gui import widgets

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Dashboard"))
        v.addWidget(widgets.muted("Observe-only overview of your worlds and the vision pipeline."))

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self._kpi_worlds = widgets.StatTile("Worlds", "0", "configured", accent="bronze", icon_name="world")
        self._kpi_attached = widgets.StatTile("Attached", "0", "live tabs", accent="green", icon_name="check")
        self._kpi_browser = widgets.StatTile("Browser", "Closed", "chromium", accent="blue", icon_name="power")
        self._kpi_runtime = widgets.StatTile("Runtime", "Stopped", "capture loop", accent="amber", icon_name="chart")
        for tile in (self._kpi_worlds, self._kpi_attached, self._kpi_browser, self._kpi_runtime):
            kpis.addWidget(tile, 1)
        v.addLayout(kpis)

        controls = widgets.Card("Runtime", "capture only — nothing is clicked")
        crow = QHBoxLayout()
        crow.setSpacing(8)
        for widget in (self.start_button, self.stop_button, self.tick_button):
            crow.addWidget(widget)
        crow.addStretch(1)
        crow.addWidget(widgets.muted("Status:")); crow.addWidget(self.status_label)
        crow.addWidget(widgets.muted("Runtime:")); crow.addWidget(self.state_label)
        controls.body.addLayout(crow)
        v.addWidget(controls)

        activity = widgets.Card("World activity", "live capture reports")
        activity.body.addWidget(self.table)
        v.addWidget(activity, stretch=2)

        logcard = widgets.Card("Live log")
        logcard.body.addWidget(self.log)
        v.addWidget(logcard, stretch=1)
        return page

    def _build_worlds_page(self) -> QWidget:
        """The World Manager: persistent worlds, explicit browser lifecycle, and
        hostname reattachment. Worlds can be added/edited/removed live (no
        restart); each world gets a tab picker the moment it exists."""
        from bap.gui import widgets

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Worlds"))

        # P0-6: never let the user assume automation exists. This mode only
        # captures screenshots — no rules, no actions, nothing is clicked.
        self.forge_status = QLabel(
            "CAPTURE ONLY — NO RULES — NO ACTIONS.  Start captures screenshots "
            "of each world for inspection; nothing is clicked or changed."
        )
        self.forge_status.setObjectName("forgeStatus")
        self.forge_status.setWordWrap(True)
        self.forge_status.setStyleSheet("font-weight: bold; color: #E0B454;")
        v.addWidget(self.forge_status)

        v.addWidget(self._build_browser_card())

        manager = widgets.Card("World Manager", "add, edit, and reattach worlds live")
        self.worlds_table = QTableWidget(0, len(self._WORLD_COLS))
        self.worlds_table.setHorizontalHeaderLabels(self._WORLD_COLS)
        self.worlds_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.worlds_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.worlds_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.worlds_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.worlds_table.setAlternatingRowColors(True)
        self.worlds_table.itemSelectionChanged.connect(self._on_world_selection_changed)
        manager.body.addWidget(self.worlds_table)

        crud = QHBoxLayout()
        self.add_world_button = QPushButton("Add World…")
        self.add_world_button.setProperty("primary", True)
        self.edit_world_button = QPushButton("Edit…")
        self.remove_world_button = QPushButton("Remove")
        self.remove_world_button.setProperty("danger", True)
        self.edit_world_button.setEnabled(False)
        self.remove_world_button.setEnabled(False)
        for widget in (self.add_world_button, self.edit_world_button, self.remove_world_button):
            crud.addWidget(widget)
        crud.addStretch(1)
        manager.body.addLayout(crud)
        v.addWidget(manager, stretch=1)

        # Per-world tab pickers live in a rebuildable form so add/remove updates
        # the picker set immediately, with no restart.
        pickers = widgets.Card("Tab assignment", "match each world to an open tab")
        self._pickers_form = QFormLayout()
        pickers.body.addLayout(self._pickers_form)
        v.addWidget(pickers)

        self.add_world_button.clicked.connect(self._on_add_world)
        self.edit_world_button.clicked.connect(self._on_edit_world)
        self.remove_world_button.clicked.connect(self._on_remove_world)
        return page

    def _build_browser_card(self):
        """The Browser card — Managed Chromium or External Chrome (CDP).

        It reflects the RUNNING browser mode (chosen at launch from persisted
        settings). Managed shows Open/Close; External shows the CDP endpoint, Test
        Connection, Attach, and Disconnect — never an 'Open Browser' button, since
        BAP does not open the operator's Chrome. The mode selector persists the
        choice for the next launch (there is no silent hot-swap of the running
        browser)."""
        from PySide6.QtWidgets import QComboBox, QLineEdit

        from bap.forge.browser_settings import BrowserMode
        from bap.gui import widgets

        external = self._external_chrome
        subtitle = ("attach to your Chrome over CDP, then reattach"
                    if external else "open Chromium, log in, then reattach")
        card = widgets.Card("Browser", subtitle)

        # --- mode selector (persisted; applies on next launch) ----------------
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Browser mode:"))
        self.browser_mode_combo = QComboBox()
        self.browser_mode_combo.addItem(BrowserMode.MANAGED.label, BrowserMode.MANAGED.value)
        self.browser_mode_combo.addItem(BrowserMode.EXTERNAL.label, BrowserMode.EXTERNAL.value)
        current = BrowserMode.EXTERNAL if external else BrowserMode.MANAGED
        self.browser_mode_combo.setCurrentIndex(self.browser_mode_combo.findData(current.value))
        self.browser_mode_combo.currentIndexChanged.connect(self._on_browser_mode_changed)
        mode_row.addWidget(self.browser_mode_combo)
        self.browser_mode_note = QLabel("")
        self.browser_mode_note.setWordWrap(True)
        self.browser_mode_note.setProperty("role", "muted")
        mode_row.addWidget(self.browser_mode_note)
        mode_row.addStretch(1)
        card.body.addLayout(mode_row)

        # --- External-Chrome connection controls ------------------------------
        self.cdp_endpoint_edit = QLineEdit(self._browser_settings.cdp_endpoint)
        self.test_conn_button = QPushButton("Test Connection")
        self.test_conn_button.clicked.connect(self._on_test_connection)
        self.connection_status_label = QLabel("")
        self.connection_status_label.setObjectName("connectionStatus")
        self.connection_status_label.setWordWrap(True)
        self.localhost_warning_label = QLabel("")
        self.localhost_warning_label.setWordWrap(True)
        self.localhost_warning_label.setStyleSheet("color:#C0563A; font-weight:bold;")
        self.launch_command_label = QLabel("")
        self.launch_command_label.setWordWrap(True)
        self.launch_command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.launch_command_label.setStyleSheet("font-family: monospace;")

        if external:
            ep_row = QHBoxLayout()
            ep_row.addWidget(QLabel("CDP endpoint:"))
            ep_row.addWidget(self.cdp_endpoint_edit, stretch=1)
            ep_row.addWidget(self.test_conn_button)
            card.body.addLayout(ep_row)
            card.body.addWidget(self.launch_command_label)
            card.body.addWidget(self.localhost_warning_label)
            card.body.addWidget(self.connection_status_label)

        # --- Attach/Open + Disconnect/Close + Scan ----------------------------
        row = QHBoxLayout()
        self.open_browser_button = QPushButton("Attach Chrome" if external else "Open Browser")
        self.close_browser_button = QPushButton("Disconnect" if external else "Close Browser")
        self.close_browser_button.setEnabled(False)
        self.scan_button = QPushButton("Scan && Reattach")
        self.scan_button.setEnabled(False)
        default_hint = ("Attach to your Chrome, then Scan && Reattach."
                        if external else "Open the browser, log in to your worlds, then Scan && Reattach.")
        self.attended_hint = QLabel(default_hint)
        self.attended_hint.setObjectName("attendedHint")
        for widget in (self.open_browser_button, self.close_browser_button, self.scan_button):
            row.addWidget(widget)
        row.addWidget(self.attended_hint)
        row.addStretch(1)
        card.body.addLayout(row)

        self.open_browser_button.clicked.connect(self._on_open_browser_clicked)
        self.close_browser_button.clicked.connect(self._on_close_browser_clicked)
        self.scan_button.clicked.connect(self._on_scan_clicked)

        if external:
            self._refresh_external_chrome_ui()
        return card

    def _build_vision_page(self) -> QWidget:
        """Test Scan (observe-only): an EXPLICIT World selector — the scan always
        runs against the chosen World, never implicitly the first one. Live and
        offline are separate actions; the file picker is never an implicit
        fallback for a broken live mapping."""
        from bap.gui import widgets

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Vision"))
        v.addWidget(widgets.muted(
            "Observe-only capture and detection. Test Scan runs against the "
            "explicitly selected world — never implicitly the first one."
        ))

        scan = widgets.Card("Test Scan", "capture and inspect — never clicks")
        picker_row = QHBoxLayout()
        picker_row.addWidget(widgets.muted("Test Scan World:"))
        self.test_scan_combo = QComboBox()
        self.test_scan_combo.currentIndexChanged.connect(self._on_test_scan_world_changed)
        picker_row.addWidget(self.test_scan_combo)
        picker_row.addStretch(1)
        scan.body.addLayout(picker_row)

        btn_row = QHBoxLayout()
        self.test_scan_live_button = QPushButton("Test Scan Live World")
        self.test_scan_live_button.setProperty("primary", True)
        self.test_scan_live_button.clicked.connect(self._on_test_scan_live)
        self.scan_all_button = QPushButton("Scan All Attached Worlds")
        self.scan_all_button.clicked.connect(self._on_scan_all)
        self.open_offline_button = QPushButton("Open Offline Screenshot…")
        self.open_offline_button.clicked.connect(self._on_open_offline)
        for widget in (self.test_scan_live_button, self.scan_all_button, self.open_offline_button):
            btn_row.addWidget(widget)
        btn_row.addStretch(1)
        scan.body.addLayout(btn_row)

        self.test_scan_target_label = QLabel("")
        self.test_scan_target_label.setObjectName("testScanTarget")
        self.test_scan_target_label.setWordWrap(True)
        scan.body.addWidget(self.test_scan_target_label)
        v.addWidget(scan)
        v.addStretch(1)
        return page

    def _build_review_page(self) -> QWidget:
        return self._build_info_page(
            "Review",
            "Grade captured detections to improve the vision pipeline.",
            [("Review Mode", "Live and historical detections are graded in the Review "
              "window, which opens from a Test Scan or Scan All result. Reviewing is "
              "observe-only and never changes a world's live tab assignment.")],
        )

    def _build_datasets_page(self) -> QWidget:
        """THE one Reviewed Dataset (Milestone 4.15): the single place reviewed
        ground truth lives. Shows its exact path and counts, opens it in Review
        (every Review entry point edits this exact dataset), and imports snapshots
        into it. There is no other editable review target."""
        from bap.gui import widgets

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Datasets"))
        v.addWidget(widgets.muted(
            "One Reviewed Dataset holds all reviewed ground truth. Opening Review "
            "anywhere in the app edits this exact dataset; snapshots are immutable "
            "archives you import into it."))

        card = widgets.Card("Reviewed Dataset", "the single source of truth")
        self._dataset_path_lbl = QLabel("")
        self._dataset_path_lbl.setWordWrap(True)
        self._dataset_counts_lbl = QLabel("")
        self._dataset_counts_lbl.setProperty("role", "muted")
        card.body.addWidget(self._dataset_path_lbl)
        card.body.addWidget(self._dataset_counts_lbl)

        row = QHBoxLayout()
        open_btn = QPushButton("Open Dataset in Review")
        open_btn.setProperty("primary", True)
        open_btn.clicked.connect(self._on_open_dataset_review)
        import_btn = QPushButton("Import snapshot…")
        import_btn.clicked.connect(self._on_import_snapshot)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_dataset_page)
        for b in (open_btn, import_btn, refresh_btn):
            row.addWidget(b)
        row.addStretch(1)
        card.body.addLayout(row)
        v.addWidget(card)
        v.addStretch(1)

        self._refresh_dataset_page()
        return page

    def _refresh_dataset_page(self) -> None:
        """Show the canonical dataset's exact path and frame/reviewed counts."""
        from bap.forge import dataset_store

        try:
            summary = dataset_store.dataset_summary()
        except Exception as exc:  # never crash the page over a read
            self._dataset_path_lbl.setText("Reviewed Dataset: (unavailable)")
            self._dataset_counts_lbl.setText(str(exc))
            return
        self._dataset_path_lbl.setText(f"Location: {summary['dir']}")
        self._dataset_counts_lbl.setText(
            f"{summary['frames']} frame(s) · {summary['reviewed']} reviewed "
            f"· {summary['labelled']} labelled")

    def _on_open_dataset_review(self) -> None:
        from bap.gui.snapshot_actions import open_dataset_in_review

        open_dataset_in_review(self)
        self._refresh_dataset_page()

    def _on_import_snapshot(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from bap.gui.snapshot_actions import import_snapshot_dialog

        snap = QFileDialog.getExistingDirectory(self, "Pick a snapshot directory to import")
        if not snap:
            return
        import_snapshot_dialog(self, snap)
        self._refresh_dataset_page()

    def _build_reports_page(self) -> QWidget:
        return self._build_info_page(
            "Reports",
            "Diagnostics and evaluation output.",
            [("Diagnostics", "Export a diagnostics bundle from Settings to capture the "
              "current environment and recent logs for troubleshooting — no gameplay "
              "data leaves the machine unless you share the bundle.")],
        )

    def _build_performance_page(self) -> QWidget:
        """The Performance Observatory page (Milestone 4.9): per-World and global
        timing, live charts, recent slow ticks, and an offline benchmark. Reads
        the shared metrics registry; measurement only, changes no behaviour."""
        from bap.gui.perf_page import PerformancePage

        self._perf_page = PerformancePage()
        return self._perf_page

    def _build_validation_page(self) -> QWidget:
        """The Vision Validation page (Milestone 4.11): one button runs the whole
        observe-only pipeline against the selected World and grades every stage
        PASS/WARNING/FAIL/INFO. Reuses the existing capture + validate_vision;
        changes no behaviour."""
        from bap.gui.vision_validation import VisionValidationPage

        self._validation_page = VisionValidationPage(
            world_aliases=self._world_aliases,
            world_getter=(lambda a: self._world_store.get(a) if self._world_store else None),
            capture_fn=self._capture_world_timed,
            classifier_provider=self._forge_classifier,
            calibration_provider=self._forge_calibration,
        )
        return self._validation_page

    def _capture_world_timed(self, alias):
        """Capture the selected World's live tab (read-only) and time it. Returns
        ``(image_or_None, latency_seconds_or_None, error_or_None)``."""
        import time

        from bap.forge.detection.testscan import capture_world_image

        t0 = time.perf_counter()
        img, err = capture_world_image(
            alias, world_store=self._world_store, assignment=self._assignment,
            browser_open=self._browser_open, capture_callback=self._capture_callback,
        )
        latency = (time.perf_counter() - t0) if img is not None else None
        return img, latency, err

    def _forge_classifier(self):
        """The bundled classifier, built once and cached for this window."""
        if getattr(self, "_classifier_cache", None) is None:
            from bap.gui.forge_debugger import _bundled_classifier

            self._classifier_cache = _bundled_classifier()
        return self._classifier_cache

    def _build_settings_page(self) -> QWidget:
        """Non-developer entry points, mirroring the Tools menu as buttons."""
        from bap.gui import widgets

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Settings"))
        v.addWidget(widgets.muted("Setup and maintenance — the same actions as the Tools menu."))

        setup = widgets.Card("Setup", "one-time and on-demand tasks")
        srow = QHBoxLayout()
        install_btn = QPushButton("Install browser…"); install_btn.clicked.connect(self._install_browser)
        first_run_btn = QPushButton("Run first-run setup…"); first_run_btn.clicked.connect(self._run_first_run)
        srow.addWidget(install_btn); srow.addWidget(first_run_btn); srow.addStretch(1)
        setup.body.addLayout(srow)
        v.addWidget(setup)

        maint = widgets.Card("Maintenance", "diagnostics and data")
        mrow = QHBoxLayout()
        diag_btn = QPushButton("Export diagnostics…"); diag_btn.clicked.connect(self._export_diagnostics)
        data_btn = QPushButton("Open data folder"); data_btn.clicked.connect(self._open_data_folder)
        mrow.addWidget(diag_btn); mrow.addWidget(data_btn); mrow.addStretch(1)
        maint.body.addLayout(mrow)
        v.addWidget(maint)
        v.addStretch(1)
        return page

    def _build_info_page(self, title: str, subtitle: str, cards) -> QWidget:
        """A simple read-only page: a display title, a subtitle, and one or more
        informational cards. Used for sections whose actions live in dedicated
        windows launched from existing flows."""
        from bap.gui import widgets

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title(title))
        v.addWidget(widgets.muted(subtitle))
        for card_title, body in cards:
            card = widgets.Card(card_title)
            label = QLabel(body)
            label.setWordWrap(True)
            label.setProperty("role", "muted")
            card.body.addWidget(label)
            v.addWidget(card)
        v.addStretch(1)
        return page

    def _refresh_dashboard(self) -> None:
        """Update the Dashboard KPI tiles from currently available, honest state
        (world/attachment counts, browser and runtime state). No fabricated
        metrics — presentation only over what the app already knows."""
        if not hasattr(self, "_kpi_worlds"):
            return
        worlds = self._world_aliases()
        attached = self._attached_aliases()
        self._kpi_worlds.set_value(str(len(worlds)), "configured")
        self._kpi_attached.set_value(str(len(attached)), "live tabs")
        self._kpi_browser.set_value("Open" if self._browser_open else "Closed", "chromium")
        self._kpi_runtime.set_value("Running" if self._running else "Stopped", "capture loop")

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
        from datetime import datetime, timezone

        captured_at = datetime.now(timezone.utc)
        assigned = self._assignment.get(alias) if self._assignment else None
        tab_id = assigned.tab_id if assigned is not None else None
        self._append_log(f"Live Test Scan of World “{alias}”.")
        self._open_debugger(img, world=world, source=f"{alias} (live)",
                            geometry_meta=self._geometry_meta(),
                            live=True, captured_at=captured_at, alias=alias, tab_id=tab_id)

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
            geometry_meta=self._geometry_meta(),
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

    def _geometry_meta(self) -> dict:
        """Capture provenance for live scans: which browser produced the pixels.
        Keeps External-Chrome captures calibrated separately from Managed ones and
        stamps snapshot metadata (Milestone 4.16)."""
        from bap.forge.browser_settings import BrowserMode

        if self._external_chrome:
            return {"browser_mode": BrowserMode.EXTERNAL.value,
                    "cdp_endpoint": self._browser_settings.cdp_endpoint}
        return {"browser_mode": BrowserMode.MANAGED.value, "cdp_endpoint": None}

    def _open_debugger(self, image, *, world=None, source: str = "", geometry_meta=None,
                       live: bool = False, captured_at=None, alias=None, tab_id=None) -> None:
        from bap.gui.forge_debugger import DebuggerWindow, _bundled_classifier
        from bap.forge.detection.geometry import CaptureGeometry, derive_rois

        geometry = CaptureGeometry.from_image(image, **(geometry_meta or {}))
        # Cursor preview (M5A) is offered ONLY for a fresh live scan — never for an
        # offline image. Both are None otherwise, so the section shows as unavailable.
        cursor_controller = self._cursor_controller() if live else None
        cursor_context = (
            self._build_cursor_context(world, alias, tab_id, image, captured_at, geometry_meta)
            if (live and cursor_controller is not None) else None
        )
        # M6A.1 — Open & Verify is offered ONLY for a fresh live scan (never offline),
        # and only when a real click adapter exists (Windows). Disabled by default.
        open_verify_controller = self._open_verify_controller() if live else None
        self._debugger = DebuggerWindow(
            image, world=world, classifier=_bundled_classifier(), source=source,
            geometry=geometry, rois=derive_rois(geometry, self._forge_calibration()),
            cursor_controller=cursor_controller, cursor_context=cursor_context,
            open_verify_controller=open_verify_controller,
            panel_calibration=(self._panel_calibration_store() if live else None),
        )
        self._debugger.resize(1280, 760)
        self._debugger.show()

    def _cursor_controller(self):
        """The one session cursor-preview controller (M5A), created lazily and
        DISABLED by default — nothing persists its enabled flag, so it resets to
        disabled on every launch. Returns None when no real cursor adapter is
        available (e.g. non-Windows), so the preview shows as unavailable rather
        than guessing."""
        if getattr(self, "_cursor_ctl", "unset") != "unset":
            return self._cursor_ctl
        self._cursor_ctl = None
        try:
            from bap.adapters.cursor.os_cursor import WindowsCursorPreview
            from bap.forge.cursor.audit import CursorPreviewAudit, default_audit_path
            from bap.forge.cursor.controller import CursorPreviewController

            cursor = WindowsCursorPreview()  # raises off Windows / without win32
            self._cursor_ctl = CursorPreviewController(cursor, CursorPreviewAudit(default_audit_path()))
        except Exception:
            self._cursor_ctl = None  # no real cursor here → preview unavailable
        return self._cursor_ctl

    def _open_verify_controller(self):
        """The one session Open & Verify controller (M6A.1), created lazily and
        DISABLED by default (its enable flag is never persisted). Returns None when
        no real click adapter is available (e.g. non-Windows), so the section shows
        as unavailable rather than being able to click. Reuses the cursor adapter for
        the pre-click move, the bundled classifier for an INDEPENDENT panel read, a
        live re-capture for panel detection, and a fail-closed click audit."""
        if getattr(self, "_openverify_ctl", "unset") != "unset":
            return self._openverify_ctl
        self._openverify_ctl = None
        try:
            from bap.adapters.cursor.os_cursor import WindowsCursorPreview
            from bap.adapters.input.os_click import WindowsSingleClick
            from bap.forge.click.audit import ClickAudit, default_click_audit_path
            from bap.forge.click.open_verify import OpenAndVerifyController
            from bap.forge.click.panel_reader import PanelReader
            from bap.forge.detection.scan import build_scan
            from bap.gui.forge_debugger import _bundled_classifier
            from bap.ops.paths import ensure_dirs, get_paths

            click = WindowsSingleClick()          # raises off Windows / without win32
            cursor = WindowsCursorPreview()
            reader = PanelReader(_bundled_classifier())

            def capture_fn():
                alias = self._current_test_scan_alias()
                if alias is None:
                    return None
                img, _lat, _err = self._capture_world_timed(alias)
                return img

            def panel_present_fn(img):
                try:
                    return build_scan(img, classifier=_bundled_classifier()).panel is not None
                except Exception:
                    return False

            diag = ensure_dirs(get_paths()).data_dir / "forge" / "openverify_diagnostics"
            self._openverify_ctl = OpenAndVerifyController(
                cursor, click, reader, ClickAudit(default_click_audit_path()),
                capture_fn=capture_fn, panel_present_fn=panel_present_fn,
                cursor_pos_fn=getattr(cursor, "current_position", None),
                diagnostics_dir=diag)
        except Exception:
            self._openverify_ctl = None  # no real click adapter → Open & Verify unavailable
        return self._openverify_ctl

    def _panel_calibration_store(self):
        """The persistent Panel Click Point Calibration store (M6A.1), created once.
        Measurement only — it records where a future action button sits; it never
        clicks anything."""
        if getattr(self, "_panel_cal_store", None) is None:
            try:
                from bap.forge.click.panel_calibration import (
                    PanelClickCalibrationStore,
                    default_calibration_path,
                )
                self._panel_cal_store = PanelClickCalibrationStore(default_calibration_path())
            except Exception:
                self._panel_cal_store = None
        return self._panel_cal_store

    def _content_calibration(self):
        """The persisted operator content-origin calibration (M5A.1), loaded once."""
        if getattr(self, "_content_cal", None) is None:
            try:
                from bap.forge.cursor.window_geometry import (
                    ContentOriginCalibration,
                    default_calibration_path,
                )

                self._content_cal = ContentOriginCalibration.load(default_calibration_path())
            except Exception:
                from bap.forge.cursor.window_geometry import ContentOriginCalibration

                self._content_cal = ContentOriginCalibration()
        return self._content_cal

    def _calibration_key(self, image, geometry_meta):
        from bap.forge.browser_settings import BrowserMode
        from bap.forge.cursor.window_geometry import CalibrationKey

        h, w = (image.shape[0], image.shape[1]) if image is not None else (0, 0)
        meta = geometry_meta or {}
        mode = meta.get("browser_mode") or (
            BrowserMode.EXTERNAL.value if self._external_chrome else BrowserMode.MANAGED.value)
        endpoint = meta.get("cdp_endpoint") or (
            self._browser_settings.cdp_endpoint if self._external_chrome else "managed")
        dpr = float(meta.get("device_pixel_ratio") or 1.0)
        zoom = float(meta.get("zoom") or 1.0)
        return CalibrationKey(mode, endpoint, w, h, w, h, dpr, zoom, 1.0, "primary")

    def _window_geometry(self, image, geometry_meta):
        """A usable WindowGeometry from the persisted content-origin calibration for
        the current geometry key, or None (the gate then blocks and the operator
        uses "Set Browser Content Origin"). Precise window position and monitor
        scaling are OS facts; this measures the content rectangle the operator marked
        rather than guessing constants (M5A.1)."""
        from bap.forge.cursor.geometry import WindowGeometry

        key = self._calibration_key(image, geometry_meta)
        rect = self._content_calibration().get(key)
        if rect is None:
            return None
        h, w = (image.shape[0], image.shape[1]) if image is not None else (0, 0)
        left, top, right, bottom = rect
        return WindowGeometry(
            window_x=left, window_y=top, window_w=right - left, window_h=bottom - top,
            content_offset_x=0, content_offset_y=0,
            device_pixel_ratio=key.device_pixel_ratio, zoom=key.zoom,
            viewport_w=w, viewport_h=h, capture_w=w, capture_h=h,
            monitor_scale=key.monitor_scale, window_id="calibrated",
            monitor_id=key.monitor_id, content_rect=(left, top, right, bottom),
            source="operator_calibrated", native_window_id="calibrated",
        )

    def _calibrate_content_origin(self, image, geometry_meta) -> bool:
        """Operator marks the Forge content rectangle on screen; persist it keyed by
        the current geometry. Reads screen coordinates only — sends no input to
        Chrome and never clicks anything in the game."""
        rect = self._capture_content_rect_overlay()
        if rect is None:
            return False
        self._content_calibration().set(self._calibration_key(image, geometry_meta), rect)
        return True

    def _capture_content_rect_overlay(self):
        """A translucent, BAP-owned full-screen overlay: the operator clicks the
        content area's top-left then bottom-right. Returns (l,t,r,b) in physical
        pixels, or None if cancelled. Best-effort across DPI (see the M5A.1 report)."""
        try:
            from bap.gui.cursor_calibration import capture_content_rect

            return capture_content_rect(self)
        except Exception as exc:  # never crash the debugger over a calibration attempt
            self._append_log(f"Content-origin calibration unavailable: {exc}")
            return None

    def _build_cursor_context(self, world, alias, tab_id, image, captured_at, geometry_meta):
        from bap.forge.browser_settings import BrowserMode
        from bap.forge.cursor.context import CursorPreviewContext

        h, w = (image.shape[0], image.shape[1]) if image is not None else (0, 0)
        mode = (BrowserMode.EXTERNAL.value if self._external_chrome else BrowserMode.MANAGED.value)
        geom_at_scan = self._window_geometry(image, geometry_meta)

        def selected_alias():
            return self._current_test_scan_alias()

        def current_tab():
            assigned = self._assignment.get(alias) if (self._assignment and alias) else None
            return assigned.tab_id if assigned is not None else None

        def geometry_status():
            return None if geom_at_scan is not None else \
                "browser content origin not calibrated — use “Set Browser Content Origin”"

        return CursorPreviewContext(
            world_alias=alias, hostname=getattr(world, "hostname", None), browser_mode=mode,
            tab_id_at_scan=tab_id, live=True, captured_at=captured_at,
            capture_w=w, capture_h=h, geometry_at_scan=geom_at_scan,
            selected_alias_getter=selected_alias,
            current_tab_getter=current_tab,
            # Re-read at move time so a changed viewport/DPR/zoom (a new key) → no
            # calibration match → geometry None → blocked.
            current_geometry_getter=lambda: self._window_geometry(image, geometry_meta),
            window_owned_getter=lambda: bool(self._browser_open),
            calibrate_content_origin=lambda: self._calibrate_content_origin(image, geometry_meta),
            geometry_status_getter=geometry_status,
        )

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
        self.open_browser_button.setText("Attach Chrome" if self._external_chrome else "Open Browser")
        self.scan_button.setEnabled(False)
        if hasattr(self, "close_browser_button"):
            self.close_browser_button.setEnabled(False)
        if self._external_chrome:
            self.attended_hint.setText("Disconnected. Chrome is still open — Attach again to reconnect.")
            self._set_connection_status("Disconnected", ok=None)
            self._append_log("Disconnected from external Chrome (Chrome left running).")
        else:
            self.attended_hint.setText("Browser closed. Open it again to reconnect your worlds.")
            self._append_log("Browser closed.")
        self._refresh_test_scan_combo()
        self._refresh_dashboard()

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
        self._append_log("Attaching to external Chrome…" if self._external_chrome else "Opening browser…")
        self.open_browser_button.setEnabled(False)
        future = self._service.open_browser()
        future.add_done_callback(self._browser_open_done)

    def _browser_open_done(self, future) -> None:
        # Runs on the runtime thread; hop to the UI thread via signals.
        try:
            future.result()
        except Exception as exc:  # surfaced, never raised into the thread
            verb = "attach to external Chrome" if self._external_chrome else "open browser"
            self._bridge.error_occurred.emit(f"Could not {verb}: {exc}")
            # Leave the app recoverable: re-enable Attach so the operator can
            # launch Chrome and retry, without a silent fallback to another mode.
            self._bridge.browser_closed.emit()
            return
        self._bridge.browser_ready.emit()

    def _on_browser_ready(self) -> None:
        self._browser_open = True
        self.scan_button.setEnabled(True)
        self.open_browser_button.setText("Attached" if self._external_chrome else "Browser open")
        self.open_browser_button.setEnabled(False)
        if hasattr(self, "close_browser_button"):
            self.close_browser_button.setEnabled(True)
        if self._external_chrome:
            self.attended_hint.setText("Attached. Open your Forge world tabs in Chrome, then Scan && Reattach.")
            self._set_connection_status("Connected", ok=True)
            self._append_log("Attached to external Chrome (read-only).")
        else:
            self.attended_hint.setText("Open your pages, then Scan.")
            self._append_log("Browser open. Open your pages, then Scan.")
        self._refresh_test_scan_combo()
        self._refresh_dashboard()

    # --- External Chrome (CDP) controls -------------------------------------

    def _on_browser_mode_changed(self, *_args) -> None:
        """Persist the selected browser mode. It applies on the next launch — the
        running browser is never hot-swapped (no silent mode change mid-session)."""
        from bap.forge.browser_settings import (
            BrowserMode,
            default_settings_path,
            save_browser_settings,
        )

        selected = BrowserMode(self.browser_mode_combo.currentData())
        running = BrowserMode.EXTERNAL if self._external_chrome else BrowserMode.MANAGED
        self._browser_settings = self._browser_settings.with_changes(mode=selected)
        try:
            save_browser_settings(default_settings_path(), self._browser_settings)
        except Exception as exc:  # never crash the UI over a settings write
            self._append_log(f"Could not save browser mode: {exc}")
        if selected is running:
            self.browser_mode_note.setText("")
        else:
            self.browser_mode_note.setText(
                f"Saved. Restart BAP to use {selected.label}; this session is still "
                f"running {running.label}.")

    def _on_test_connection(self) -> None:
        """GET the CDP endpoint's /json/version to report reachability, browser
        version, and tab count — without connecting a driver. Persists the typed
        endpoint. Does not launch Chrome."""
        from bap.adapters.browser.cdp_attach_adapter import normalize_endpoint, probe_cdp
        from bap.forge.browser_settings import default_settings_path, save_browser_settings

        endpoint = normalize_endpoint(self.cdp_endpoint_edit.text())
        self.cdp_endpoint_edit.setText(endpoint)
        self._browser_settings = self._browser_settings.with_changes(cdp_endpoint=endpoint)
        try:
            save_browser_settings(default_settings_path(), self._browser_settings)
        except Exception:
            pass
        self._refresh_external_chrome_ui()
        result = probe_cdp(endpoint)
        if result.get("reachable"):
            tabs = result.get("tabs")
            forge = result.get("forge_tabs")
            detail = f"{result.get('browser', 'Chrome')}"
            if tabs is not None:
                detail += f" · {tabs} tab(s)"
                if forge is not None:
                    detail += f" ({forge} Forge)"
            self._set_connection_status(f"Reachable — {detail}", ok=True)
        else:
            self._set_connection_status(
                f"Connection refused / not running at {endpoint}. "
                "Launch Chrome with remote debugging first.", ok=False)

    def _set_connection_status(self, text: str, *, ok) -> None:
        if not hasattr(self, "connection_status_label"):
            return
        color = "#3A8A3A" if ok else ("#C0563A" if ok is False else "#888888")
        self.connection_status_label.setStyleSheet(f"color:{color};")
        self.connection_status_label.setText(f"Status: {text}")

    def _refresh_external_chrome_ui(self) -> None:
        """Update the localhost warning and the copyable launch command from the
        current endpoint."""
        from bap.adapters.browser.cdp_attach_adapter import is_localhost_endpoint, normalize_endpoint
        from bap.forge.browser_settings import windows_launch_command

        if not hasattr(self, "cdp_endpoint_edit"):
            return
        endpoint = normalize_endpoint(self.cdp_endpoint_edit.text())
        if is_localhost_endpoint(endpoint):
            self.localhost_warning_label.setText("")
        else:
            self.localhost_warning_label.setText(
                "⚠ Endpoint is not localhost. The Chrome debugging port must not be "
                "exposed to the network — use 127.0.0.1.")
        self.launch_command_label.setText(
            "Launch Chrome (Windows):  " + windows_launch_command(self._browser_settings))

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
        self._refresh_dashboard()

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
        if self._external_chrome:
            # External Chrome is operator-owned: exit disconnects (shutdown_runtime
            # → adapter.stop() disconnects only) but NEVER closes Chrome. No
            # "keep the browser open" prompt — there is no BAP-owned browser.
            close_browser = True
        elif self._forge and self._browser_open:
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
