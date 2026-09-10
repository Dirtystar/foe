"""Live Data Collection window (Milestone 5D) — OBSERVE-ONLY.

One operator surface for rapidly collecting, reviewing, and validating live Chrome
badge data across many Worlds: start a named session, one-click capture per World
(or all), a filterable/sortable capture queue, live canonical statistics with
shortage hints and target progress, dataset validation, a manual commit plan, a
session report, and Open-in-Review.

It captures read-only screenshots via the existing capture path and files them into
the canonical dataset through the collection core. It never clicks, moves the
cursor, types, retrains, or changes any detector/classifier threshold.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bap.forge.collection import session as sess_mod
from bap.forge.collection.capture_quality import assess_capture
from bap.forge.collection.commit import prepare_commit
from bap.forge.collection.dataset_view import (
    build_queue,
    dataset_statistics,
    session_dashboard,
    status_summary,
    target_progress,
)
from bap.forge.collection.report import write_session_report
from bap.forge.collection.validate import validate_dataset

_QUEUE_COLS = ["World", "Timestamp", "Resolution", "Det", "Cls", "UNK",
               "Review", "Dup", "Session", "Frame"]
_FILTERS = [("All", None), ("Unreviewed", "unreviewed"), ("Reviewed", "reviewed"),
            ("No badge", "no_badge"), ("Has UNKNOWN", "has_unknown"),
            ("Negative", "negative"), ("20%", "20"), ("40%", "40"),
            ("60%", "60"), ("80%", "80"), ("100%", "100")]
_SORTS = [("Priority (UNKNOWN → rare → newest)", "priority"), ("Newest", "newest"),
          ("Highest uncertainty", "uncertainty"), ("Rarest class", "rarest_class"),
          ("Most detections", "most_detections"), ("World", "world")]


class _CaptureWorker(QObject):
    """Runs a :class:`CaptureJob` on its own thread and marshals every stage back
    to the GUI via signals. It touches no GUI object — it only emits signals, which
    Qt delivers to the GUI thread through queued connections."""

    progress = Signal(object)   # WorldProgress
    finished = Signal(object)   # JobSummary

    def __init__(self, job):
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            summary = self._job.run(on_progress=self.progress.emit)
        except Exception as exc:   # never let a worker exception kill the process
            from bap.forge.collection.capture_job import JobSummary
            summary = JobSummary(total=0, completed=0, skipped=0, failed=0,
                                 cancelled=0, duration_ms=0.0, was_cancelled=False)
            summary._error = str(exc)  # type: ignore[attr-defined]
        self.finished.emit(summary)


class _StatsWorker(QObject):
    """Compute the heavy corpus statistics off the GUI thread. ``load_all`` reads
    every reviewed frame from disk (~2.7 s), which would otherwise freeze the window
    on every refresh; cv2.imread releases the GIL, so this runs concurrently."""

    done = Signal(object)   # (status_summary_dict, dataset_statistics_dict) or None

    def __init__(self, session_id):
        super().__init__()
        self._sid = session_id

    def run(self) -> None:
        try:
            from bap.forge.detection.dataset import load_all
            from bap.forge.collection.dataset_view import (
                dataset_statistics, status_summary)
            samples = load_all()   # read the corpus once, share it
            ss = status_summary(samples=samples)
            st = dataset_statistics(samples=samples, session_id=self._sid)
            self.done.emit((ss, st))
        except Exception:
            self.done.emit(None)


class ForgeCollectionWindow(QWidget):
    """The Live Data Collection page. Dependencies are injected so it is testable
    without a real browser: ``capture_fn(world) -> BGR image | None`` overrides the
    live capture path (used by tests)."""

    def __init__(self, *, world_store=None, assignment=None, capture_callback=None,
                 browser_open=False, browser_mode="unknown", capture_fn=None,
                 analyze_fn=None, parent=None):
        super().__init__(parent)
        self._analyze_fn = analyze_fn   # tests inject a fake/slow analyzer
        self.setWindowTitle("Live Data Collection")
        self._world_store = world_store
        self._assignment = assignment
        self._capture_callback = capture_callback
        self._browser_open = browser_open
        self._browser_mode = browser_mode
        self._capture_fn = capture_fn
        self._session = sess_mod.active_session()
        self._world_checks: dict[str, QCheckBox] = {}
        self._job = None            # CaptureJob while a batch runs
        self._job_thread = None     # QThread
        self._job_worker = None     # _CaptureWorker
        self._stats_thread = None   # background corpus-statistics compute
        self._stats_worker = None
        self._stats_pending = False
        self._build()
        self._install_shortcuts()
        self._restore_geometry()
        self.refresh()
        self.capture_all_btn.setFocus()   # ready to capture immediately

    def _install_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut
        # Capture All is the all-day action → give it a one-key shortcut.
        for seq, slot in (("Ctrl+Return", lambda: self._capture(selected_only=False)),
                          ("Ctrl+Enter", lambda: self._capture(selected_only=False)),
                          ("F5", self.refresh),
                          ("Ctrl+E", self._open_selected_row)):
            QShortcut(QKeySequence(seq), self, activated=slot)

    # ---- construction ----
    def _build(self) -> None:
        root = QVBoxLayout(self)

        # Always-visible session status + live dashboard.
        self.session_lbl = QLabel()
        self.session_lbl.setStyleSheet("font-weight: 600;")
        root.addWidget(self.session_lbl)
        self.dashboard_lbl = QLabel()
        self.dashboard_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.dashboard_lbl.setToolTip("Live metrics for the current session — real, "
                                      "never fabricated.")
        root.addWidget(self.dashboard_lbl)

        # Always-visible dataset status (reviewed / pending / negative / classes /
        # UNKNOWN, plus today's additions).
        self.status_lbl = QLabel()
        self.status_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setToolTip("Canonical dataset status. Shortages guide the "
                                   "most useful next capture.")
        root.addWidget(self.status_lbl)

        session_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Session")
        self.start_btn.setToolTip("Begin a named collection session (survives an app "
                                  "restart). Records Worlds, time, browser mode, git commit.")
        self.start_btn.clicked.connect(self._start_session)
        session_row.addWidget(self.start_btn)
        self.capture_sel_btn = QPushButton("📷 Capture Selected")
        self.capture_sel_btn.setToolTip("Capture a read-only screenshot of each ticked "
                                        "World into the dataset (duplicates skipped).")
        self.capture_sel_btn.clicked.connect(lambda: self._capture(selected_only=True))
        session_row.addWidget(self.capture_sel_btn)
        self.capture_all_btn = QPushButton("📷 Capture All Worlds  (Ctrl+↵)")
        self.capture_all_btn.setToolTip("Capture every World once, in the background. "
                                        "The window stays responsive; Cancel any time.")
        self.capture_all_btn.clicked.connect(lambda: self._capture(selected_only=False))
        session_row.addWidget(self.capture_all_btn)
        self.cancel_btn = QPushButton("⏹ Cancel Capture")
        self.cancel_btn.setToolTip("Stop scheduling new Worlds. The current World "
                                   "finishes safely and every completed result is kept.")
        self.cancel_btn.clicked.connect(self._cancel_capture)
        self.cancel_btn.setVisible(False)
        session_row.addWidget(self.cancel_btn)
        self.resume_btn = QPushButton("⤿ Resume Unfinished")
        self.resume_btn.setToolTip("Capture only the Worlds a previous batch did not "
                                   "finish (completed Worlds are never re-captured).")
        self.resume_btn.clicked.connect(self._resume_unfinished)
        self.resume_btn.setVisible(False)
        session_row.addWidget(self.resume_btn)
        session_row.addStretch(1)
        session_row.addWidget(QLabel("Analysis:"))
        self.threads_combo = QComboBox()
        self.threads_combo.setToolTip("OpenCV analysis threads. 1 keeps the machine "
                                      "most responsive; Auto uses OpenCV's default.")
        self.threads_combo.addItem("1 thread (responsive)", 1)
        self.threads_combo.addItem("2 threads", 2)
        self.threads_combo.addItem("Auto", "auto")
        session_row.addWidget(self.threads_combo)
        root.addLayout(session_row)

        # Live progress line during an async batch.
        self.progress_lbl = QLabel("")
        self.progress_lbl.setStyleSheet("color:#2e7d32; font-weight:600;")
        root.addWidget(self.progress_lbl)

        # World checkboxes
        worlds_row = QHBoxLayout()
        worlds_row.addWidget(QLabel("Worlds:"))
        for alias in self._world_aliases():
            cb = QCheckBox(alias)
            cb.setChecked(True)
            self._world_checks[alias] = cb
            worlds_row.addWidget(cb)
        worlds_row.addStretch(1)
        root.addLayout(worlds_row)

        # filters + sort
        controls = QHBoxLayout()
        self.filter_combo = QComboBox()
        for label, _ in _FILTERS:
            self.filter_combo.addItem(label)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(QLabel("Filter:"))
        controls.addWidget(self.filter_combo)
        self.sort_combo = QComboBox()
        for label, _ in _SORTS:
            self.sort_combo.addItem(label)
        self.sort_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(QLabel("Sort:"))
        controls.addWidget(self.sort_combo)
        self.today_check = QCheckBox("Today")
        self.today_check.toggled.connect(self.refresh)
        controls.addWidget(self.today_check)
        self.open_review_btn = QPushButton("✎ Open in Review")
        self.open_review_btn.setToolTip("Open the whole dataset in Review Mode "
                                        "(fast keyboard labelling).")
        self.open_review_btn.clicked.connect(self._open_review)
        controls.addWidget(self.open_review_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        # One-tap quick filters (chips) for the most common operator views.
        quick = QHBoxLayout()
        quick.addWidget(QLabel("Quick:"))
        for label, filt, srt in (("Needs review", "unreviewed", "priority"),
                                  ("Has UNKNOWN", "has_unknown", "uncertainty"),
                                  ("Rare classes", None, "rarest_class"),
                                  ("Negatives", "negative", "newest"),
                                  ("All", None, "newest")):
            b = QPushButton(label)
            b.setToolTip("Quick view — sets the filter and sort together.")
            b.clicked.connect(lambda _=False, f=filt, s=srt: self._quick(f, s))
            quick.addWidget(b)
        quick.addStretch(1)
        root.addLayout(quick)

        # queue table + empty state
        self.queue_hint = QLabel()
        self.queue_hint.setStyleSheet("color: #888;")
        self.queue_hint.hide()
        root.addWidget(self.queue_hint)
        self.table = QTableWidget(0, len(_QUEUE_COLS))
        self.table.setHorizontalHeaderLabels(_QUEUE_COLS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setToolTip("Double-click a row to open that frame in Review "
                              "(or select it and press Ctrl+E).")
        self.table.itemDoubleClicked.connect(
            lambda *_: self._open_selected_row())
        root.addWidget(self.table, 2)

        # stats + actions
        self.stats = QPlainTextEdit()
        self.stats.setReadOnly(True)
        self.stats.setMaximumBlockCount(400)
        root.addWidget(self.stats, 1)

        actions = QHBoxLayout()
        for text, slot, tip in (
                ("Validate Dataset", self._validate,
                 "Check the dataset for problems (shown below — never auto-fixed)."),
                ("Prepare Dataset Commit", self._prepare_commit,
                 "Show the files, class delta, and the exact Git Bash commands to run."),
                ("Write Session Report", self._write_report,
                 "Write LIVE_COLLECTION_SESSION_<id>.md for this session."),
                ("Refresh  (F5)", self.refresh, "Reload the queue and status.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        root.addLayout(actions)

        # Inline results (Validate / Prepare Commit / Report) — no interrupting
        # dialogs, so a long day of collecting is never blocked by a popup.
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Validate / Prepare Commit / Report results "
                                        "appear here.")
        root.addWidget(self.results, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setPlaceholderText("Capture activity log.")
        root.addWidget(self.log, 1)

    # ---- helpers ----
    def _world_aliases(self) -> list[str]:
        store = self._world_store
        if store is None:
            return []
        worlds = store.list() if hasattr(store, "list") else list(store)
        return [getattr(w, "alias", str(w)) for w in worlds]

    def _world_by_alias(self, alias: str):
        store = self._world_store
        worlds = store.list() if hasattr(store, "list") else list(store or [])
        for w in worlds:
            if getattr(w, "alias", None) == alias:
                return w
        return None

    def _selected_aliases(self, selected_only: bool) -> list[str]:
        if not selected_only:
            return list(self._world_checks.keys())
        return [a for a, cb in self._world_checks.items() if cb.isChecked()]

    def _append(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    # ---- actions ----
    def _start_session(self) -> None:
        aliases = self._selected_aliases(selected_only=False)
        self._session = sess_mod.start_session(
            aliases, browser_mode=self._browser_mode, notes="")
        self._append(f"Started session {self._session.session_id} "
                     f"({len(aliases)} Worlds).")
        self.refresh()

    def _capture_image(self, world):
        if self._capture_fn is not None:
            return self._capture_fn(world), None
        from bap.forge.detection.testscan import capture_world_image
        return capture_world_image(
            getattr(world, "alias", world), world_store=self._world_store,
            assignment=self._assignment, browser_open=self._browser_open,
            capture_callback=self._capture_callback)

    def _capture(self, *, selected_only: bool, aliases: list[str] | None = None) -> None:
        """Start an ASYNCHRONOUS Capture-All batch on a worker thread. The GUI
        thread only presents progress — it never runs capture/detector/classifier/
        dataset code, so the window stays responsive for the whole 8-World run."""
        if self._job_thread is not None:
            self._append("A capture is already running — Cancel it first.")
            return
        if self._session is None:
            self._start_session()
        if aliases is None:
            aliases = self._selected_aliases(selected_only)
        if not aliases:
            self._warn("No Worlds selected", "Tick at least one World, or use "
                       "Capture All Worlds.")
            return

        from PySide6.QtCore import QThread
        from bap.forge.collection.capture_job import CaptureJob

        worlds = [(a, self._world_by_alias(a)) for a in aliases]
        job = CaptureJob(worlds, capture_fn=self._capture_image, session=self._session,
                         analyze_fn=self._analyze_fn,
                         cv2_threads=self._analysis_threads(),
                         quality_fn=lambda img, w: assess_capture(img, world=w))
        self._job = job
        self._job_thread = QThread(self)
        self._job_worker = _CaptureWorker(job)
        self._job_worker.moveToThread(self._job_thread)
        self._job_thread.started.connect(self._job_worker.run)
        self._job_worker.progress.connect(self._on_progress)   # queued → GUI thread
        self._job_worker.finished.connect(self._on_job_finished)
        self._set_running(True, len(worlds))
        self._append(f"▶ Capturing {len(worlds)} World(s) in the background — the "
                     "window stays responsive; Cancel any time.")
        self._job_thread.start()

    def _on_progress(self, p) -> None:
        """Runs on the GUI thread (queued signal). Presentation only."""
        from bap.forge.collection.capture_job import Stage
        for msg in getattr(p, "warnings", []) or []:
            self._append(f"⚠ {p.alias}: {msg}")
        self.progress_lbl.setText(
            f"[{p.position}/{p.total}]  {p.alias}: {p.stage.value}"
            + (f"  ({p.duration_ms/1000:.1f}s)" if p.duration_ms else ""))
        if p.stage is Stage.COMPLETED:
            self._append(f"✔ {p.alias}: {p.frame} — det {p.detected}, "
                         f"cls {p.classified}, UNK {p.unknown}  ({p.duration_ms/1000:.1f}s)")
            # Light incremental update only (the queue). The heavy corpus statistics
            # refresh runs once at job finish, off the hot path, so per-World updates
            # never block the GUI thread; the progress label shows live state.
            self._refresh_queue()
        elif p.stage is Stage.SKIPPED:
            self._append(f"↺ {p.alias}: duplicate skipped ({p.frame})")
        elif p.stage is Stage.FAILED:
            e = p.error or {}
            self._append(f"✖ {p.alias}: [{e.get('stage')}] {e.get('reason')}  →  {e.get('fix')}")
        elif p.stage is Stage.CANCELLED:
            self._append(f"⊘ {p.alias}: cancelled (not captured)")

    def _on_job_finished(self, summary) -> None:
        self._append("— " + summary.message())
        self._show_results("Capture All", [
            summary.message(),
            f"completed {summary.completed} · duplicates {summary.skipped} · "
            f"failed {summary.failed} · cancelled {summary.cancelled}",
            f"total {summary.duration_ms/1000:.1f}s"])
        # tear the worker thread down cleanly
        if self._job_thread is not None:
            self._job_thread.quit()
            self._job_thread.wait(3000)
        self._job = self._job_thread = self._job_worker = None
        self._set_running(False, 0)
        self.refresh()

    def _cancel_capture(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self.progress_lbl.setText("Cancelling — finishing the current World safely…")
            self.cancel_btn.setEnabled(False)

    def _analysis_threads(self):
        data = self.threads_combo.currentData() if hasattr(self, "threads_combo") else 1
        return None if data == "auto" else int(data)

    def _set_running(self, on: bool, total: int) -> None:
        for b in (self.capture_sel_btn, self.capture_all_btn, self.start_btn):
            b.setEnabled(not on)
        self.cancel_btn.setVisible(on)
        self.cancel_btn.setEnabled(on)
        self.capture_all_btn.setText("⏳ Capturing…" if on else "📷 Capture All Worlds  (Ctrl+↵)")
        if not on:
            self.progress_lbl.setText("")

    def _resume_unfinished(self) -> None:
        """Capture only the Worlds the last batch did not finish (crash/cancel
        recovery). Completed Worlds are never re-captured."""
        if self._session is None:
            return
        pending = [a for a in self._session.unfinished_worlds()
                   if a in self._world_checks]
        if not pending:
            self._append("Nothing to resume — the last batch completed.")
            return
        self._append(f"Resuming {len(pending)} unfinished World(s): {', '.join(pending)}")
        self._capture(selected_only=False, aliases=pending)

    @property
    def _job_running(self) -> bool:
        return self._job_thread is not None

    def _warn(self, title: str, detail: str) -> None:
        # Inline, non-blocking — a trivial popup would interrupt an all-day flow.
        self._append(f"⚠ {title}: {detail}")

    def _quick(self, filt, srt) -> None:
        """One-tap view: set the filter + sort together and refresh."""
        idx = next((i for i, (_, f) in enumerate(_FILTERS) if f == filt), 0)
        self.filter_combo.setCurrentIndex(idx)
        sidx = next((i for i, (_, s) in enumerate(_SORTS) if s == srt), 0)
        self.sort_combo.setCurrentIndex(sidx)
        self.refresh()

    def refresh(self) -> None:
        # Light, instant updates on the GUI thread…
        self.session_lbl.setText(self._session_text())
        self._refresh_dashboard()
        self._refresh_queue()
        # …and the heavy corpus statistics off-thread so refresh never blocks.
        self._refresh_stats_async()
        # Offer Resume when a previous batch left unfinished Worlds and none is running.
        pending = (self._session.unfinished_worlds()
                   if (self._session and not self._job_running) else [])
        self.resume_btn.setVisible(bool(pending))
        if pending:
            self.resume_btn.setText(f"⤿ Resume Unfinished ({len(pending)})")

    def _refresh_stats_async(self) -> None:
        """Recompute the corpus status + statistics on a background thread and
        render them when ready. Overlapping requests are coalesced."""
        if self._stats_thread is not None:
            self._stats_pending = True
            return
        from PySide6.QtCore import QThread
        sid = self._session.session_id if self._session else None
        self._stats_thread = QThread(self)
        self._stats_worker = _StatsWorker(sid)
        self._stats_worker.moveToThread(self._stats_thread)
        self._stats_thread.started.connect(self._stats_worker.run)
        self._stats_worker.done.connect(self._on_stats_ready)
        self._stats_thread.start()

    def _on_stats_ready(self, payload) -> None:
        if payload is not None:
            ss, st = payload
            try:
                self._render_status(ss)
                self._render_stats(st)
            except Exception:
                pass
        if self._stats_thread is not None:
            self._stats_thread.quit()
            self._stats_thread.wait(2000)
        self._stats_thread = self._stats_worker = None
        if self._stats_pending:          # a refresh arrived while computing — redo
            self._stats_pending = False
            self._refresh_stats_async()

    def _refresh_dashboard(self) -> None:
        d = session_dashboard(self._session)
        if not d.get("active"):
            self.dashboard_lbl.setText("<i>No active session — click Start Session "
                                       "to begin collecting.</i>")
            return
        rate = f"{d['capture_rate_per_hour']}/h" if d["capture_rate_per_hour"] else "—"
        self.dashboard_lbl.setText(
            f"<b>Today's session</b> · Worlds {d['worlds_attached']} · "
            f"captured <b>{d['frames_captured']}</b> · skipped {d['frames_skipped']} · "
            f"reviewed {d['frames_reviewed']} · pending {d['frames_pending']} · "
            f"duplicates {d['duplicates']} · rate {rate} · "
            f"duration {d['duration_human']}")

    def _refresh_status(self) -> None:
        try:
            self._render_status(status_summary())
        except Exception as exc:
            self.status_lbl.setText(f"<i>(dataset status unavailable: {exc})</i>")

    def _render_status(self, ss) -> None:
        pc = ss["per_class"]
        t = ss["today"]
        cls = " ".join(f"{k}%=<b>{pc[k]}</b>" for k in ("20", "40", "60", "80", "100"))
        zero = ", ".join(f"{c}%" for c in ss["shortages"]["zero_example_classes"])
        zero_txt = f" · <span style='color:#c0392b'>zero: {zero}</span>" if zero else ""
        self.status_lbl.setText(
            f"<b>Dataset</b>: reviewed {ss['reviewed']} · pending {ss['pending']} · "
            f"negative {ss['negative']} · UNKNOWN {ss['unknown']}<br>"
            f"Classes: {cls}{zero_txt}<br>"
            f"<b>Today</b>: +{t['frames']} frames, {t['reviewed']} reviewed, "
            f"{t['negative']} negative · "
            + " ".join(f"{k}%+{t['per_class'][k]}" for k in ('20', '40', '60', '80', '100')))

    def _session_text(self) -> str:
        if self._session is None:
            return "No active session — click Start Session."
        s = self._session
        return (f"Session {s.session_id} · mode {s.browser_mode} · "
                f"{len(s.captured_frames)} captured · {s.duplicates_skipped} dup skipped "
                f"· commit {(s.git_commit or '')[:8]}")

    def _current_filters(self) -> list[str]:
        _, key = _FILTERS[self.filter_combo.currentIndex()]
        return [key] if key else []

    def _refresh_queue(self) -> None:
        _, sort = _SORTS[self.sort_combo.currentIndex()]
        rows = build_queue(filters=self._current_filters(), sort=sort,
                           today=self.today_check.isChecked())
        if not rows:
            self.queue_hint.setText(
                "No frames match this view. "
                + ("Capture a World to begin." if self._session else
                   "Start a session and Capture All Worlds to begin."))
            self.queue_hint.show()
        else:
            self.queue_hint.hide()
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            res = f"{e.capture_w}x{e.capture_h}" if e.capture_w else "—"
            values = [e.world or "—", (e.timestamp or "—").replace("T", " "),
                      res, str(e.detected), str(e.classified), str(e.unknown),
                      e.review_state, "dup" if e.duplicate else "",
                      e.session_id or "—", e.frame]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))

    def _refresh_stats(self) -> None:
        try:
            sid = self._session.session_id if self._session else None
            self._render_stats(dataset_statistics(session_id=sid))
        except Exception as exc:
            self.stats.setPlainText(f"(statistics unavailable: {exc})")

    def _render_stats(self, st) -> None:
        lines = [
            f"Frames: {st['total_frames']} total · {st['reviewed_frames']} reviewed "
            f"· {st['reviewed_negative_frames']} negative · {st['pending_frames']} pending",
            f"Badges: {st['total_badges']}   Per class: " +
            "  ".join(f"{k}%={v}" for k, v in st["per_class"].items()),
            f"Live Chrome vs historical: {st['live_vs_historical']}",
            f"Today: {st['today_frames']}   This session: {st['session_frames']}",
            f"Shortage → {st['shortages']['message']}"
            f"  (zero: {st['shortages']['zero_example_classes']})",
        ]
        if self._session:
            prog = target_progress(self._session)
            if prog:
                lines.append("Targets: " + "  ".join(
                    f"{k} {v['have']}/{v['target']}{'✓' if v['met'] else ''}"
                    for k, v in prog.items()))
        self.stats.setPlainText("\n".join(lines))

    def _show_results(self, title: str, lines: list[str]) -> None:
        import time
        self.results.setPlainText(f"── {title}  ·  {time.strftime('%H:%M:%S')} ──\n"
                                  + "\n".join(lines))

    def _validate(self) -> None:
        v = validate_dataset()
        head = ("✅ OK" if v["ok"] else "❌ errors present")
        msg = [f"{head} — {v['counts']['errors']} error(s), "
               f"{v['counts']['warnings']} warning(s)"]
        for it in v["issues"][:60]:
            msg.append(f"[{it['severity']}] {it['kind']} · {it['frame']}: "
                       f"{it['detail']}  → {it['suggested_fix']}")
        if v["ok"] and not v["issues"]:
            msg.append("No problems found.")
        self._show_results("Validate Dataset", msg)

    def _prepare_commit(self) -> None:
        p = prepare_commit(session=self._session)
        lines = [
            f"Dataset: {p['dataset_dir']}",
            f"Files added: {p['files_added']}   modified: {p['files_modified']}",
            f"Frames reviewed: {p['frames_reviewed']}   pending: {p['frames_pending']}",
            f"Class-count delta: {p['class_count_delta']}",
            f"Validation: {'OK' if p['validation_ok'] else 'ERRORS'}",
        ]
        for w in p["warnings"]:
            lines.append(f"⚠ {w}")
        lines.append("")
        lines.append("Run these yourself in Git Bash:")
        lines += p["suggested_commands"]
        self._show_results("Prepare Dataset Commit", lines)

    def _write_report(self) -> None:
        if self._session is None:
            self._show_results("Session Report", ["No active session — Start Session first."])
            return
        path = write_session_report(self._session)
        self._append(f"Session report written: {path}")
        self._show_results("Session Report", [f"Written: {path}"])

    def _open_review(self, frame: str | None = None) -> None:
        from bap.forge.dataset_store import dataset_review_paths
        from bap.gui.forge_review import ForgeReviewWindow
        from bap.forge.detection.calibration import WeakeningCalibration
        from bap.forge.labeling.session import LabelSession

        frames_dir, labels_path, calib_path = dataset_review_paths()
        session = LabelSession.open(frames_dir, labels_path)
        cal = WeakeningCalibration.load(calib_path)
        if frame:                                   # open straight at the chosen frame
            try:
                idx = session._frames.index(frame)
                session.goto(idx)
            except (ValueError, AttributeError):
                pass
        self._review = ForgeReviewWindow(session, frames_dir, cal)
        self._review.show()

    def _open_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self._open_review()
            return
        item = self.table.item(row, len(_QUEUE_COLS) - 1)   # last col = frame name
        self._open_review(item.text() if item else None)

    # ---- window geometry memory ----
    def _settings(self):
        from PySide6.QtCore import QSettings
        return QSettings("BAP", "ForgeCollection")

    def _restore_geometry(self) -> None:
        geo = self._settings().value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # A running batch must never be silently abandoned.
        if self._job_running:
            choice = self._prompt_running_close()
            if choice == "stay":
                event.ignore()
                return
            if choice == "cancel":
                self._cancel_capture()
                if self._job_thread is not None:   # let the in-flight World finish
                    self._job_thread.quit()
                    self._job_thread.wait(30000)
            # "keep" → detach the window but leave the worker running to completion
        if self._stats_thread is not None:   # stop any background stats compute
            self._stats_thread.quit()
            self._stats_thread.wait(2000)
        self._settings().setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    def _prompt_running_close(self) -> str:
        """Ask what to do when closing during a running capture. Returns
        'cancel' | 'keep' | 'stay'."""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle("Capture in progress")
        box.setText("A capture batch is still running. What would you like to do?")
        cancel_b = box.addButton("Cancel capture and close", QMessageBox.ButtonRole.DestructiveRole)
        keep_b = box.addButton("Keep running", QMessageBox.ButtonRole.AcceptRole)
        stay_b = box.addButton("Stay open", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(stay_b)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            return "cancel"
        if clicked is keep_b:
            return "keep"
        return "stay"


__all__ = ["ForgeCollectionWindow"]
