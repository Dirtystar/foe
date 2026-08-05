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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bap.forge.collection import session as sess_mod
from bap.forge.collection.capture import capture_frame
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


class ForgeCollectionWindow(QWidget):
    """The Live Data Collection page. Dependencies are injected so it is testable
    without a real browser: ``capture_fn(world) -> BGR image | None`` overrides the
    live capture path (used by tests)."""

    def __init__(self, *, world_store=None, assignment=None, capture_callback=None,
                 browser_open=False, browser_mode="unknown", capture_fn=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Data Collection")
        self._world_store = world_store
        self._assignment = assignment
        self._capture_callback = capture_callback
        self._browser_open = browser_open
        self._browser_mode = browser_mode
        self._capture_fn = capture_fn
        self._session = sess_mod.active_session()
        self._world_checks: dict[str, QCheckBox] = {}
        self._build()
        self.refresh()

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
        self.capture_all_btn = QPushButton("📷 Capture All Worlds")
        self.capture_all_btn.setToolTip("Capture every World once. Move the map between "
                                        "bursts to gather fresh badges.")
        self.capture_all_btn.clicked.connect(lambda: self._capture(selected_only=False))
        session_row.addWidget(self.capture_all_btn)
        session_row.addStretch(1)
        root.addLayout(session_row)

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
        root.addWidget(self.table, 2)

        # stats + actions
        self.stats = QPlainTextEdit()
        self.stats.setReadOnly(True)
        self.stats.setMaximumBlockCount(400)
        root.addWidget(self.stats, 1)

        actions = QHBoxLayout()
        for text, slot in (("Validate Dataset", self._validate),
                           ("Prepare Dataset Commit", self._prepare_commit),
                           ("Write Session Report", self._write_report),
                           ("Refresh", self.refresh)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        root.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
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

    def _capture(self, *, selected_only: bool) -> None:
        if self._session is None:
            self._start_session()
        aliases = self._selected_aliases(selected_only)
        if not aliases:
            self._warn("No Worlds selected", "Tick at least one World, or use "
                       "Capture All Worlds.")
            return
        # Loading indicator — disable capture while a burst runs.
        self._set_capturing(True)
        new = dup = err = warned = 0
        try:
            for alias in aliases:
                world = self._world_by_alias(alias)
                try:
                    image, error = self._capture_image(world)
                except Exception as exc:  # capture must never crash the page
                    image, error = None, str(exc)
                # Pre-flight quality: warn about detached/zoom/resolution/dup so the
                # operator never wastes time on unusable data.
                for w in assess_capture(image, world=world, capture_error=error):
                    warned += 1
                    self._append(f"⚠ {alias}: {w.message}  →  {w.fix}")
                if image is None:
                    err += 1
                    continue
                res = capture_frame(image, world=world, session=self._session)
                if res.is_new:
                    new += 1
                    self._append(f"✔ {alias}: {res.frame} — det {res.detected}, "
                                 f"cls {res.classified}, UNK {res.unknown}")
                else:
                    dup += 1
                    self._append(f"↺ {alias}: duplicate skipped ({res.frame})")
        finally:
            self._set_capturing(False)
        self._append(f"— Capture done: {new} new · {dup} duplicate(s) · "
                     f"{err} error(s) · {warned} warning(s).")
        self.refresh()

    def _set_capturing(self, on: bool) -> None:
        for b in (self.capture_sel_btn, self.capture_all_btn, self.start_btn):
            b.setEnabled(not on)
        self.capture_all_btn.setText("⏳ Capturing…" if on else "📷 Capture All Worlds")
        QApplication.processEvents()  # let the label repaint during a burst

    def _warn(self, title: str, detail: str) -> None:
        self._append(f"⚠ {title}: {detail}")
        QMessageBox.warning(self, title, detail)

    def _quick(self, filt, srt) -> None:
        """One-tap view: set the filter + sort together and refresh."""
        idx = next((i for i, (_, f) in enumerate(_FILTERS) if f == filt), 0)
        self.filter_combo.setCurrentIndex(idx)
        sidx = next((i for i, (_, s) in enumerate(_SORTS) if s == srt), 0)
        self.sort_combo.setCurrentIndex(sidx)
        self.refresh()

    def refresh(self) -> None:
        self.session_lbl.setText(self._session_text())
        self._refresh_dashboard()
        self._refresh_status()
        self._refresh_queue()
        self._refresh_stats()

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
            ss = status_summary()
        except Exception as exc:
            self.status_lbl.setText(f"<i>(dataset status unavailable: {exc})</i>")
            return
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
            st = dataset_statistics(session_id=sid)
        except Exception as exc:
            self.stats.setPlainText(f"(statistics unavailable: {exc})")
            return
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

    def _validate(self) -> None:
        v = validate_dataset()
        head = ("✅ OK" if v["ok"] else "❌ errors present")
        msg = [f"{head} — {v['counts']['errors']} error(s), "
               f"{v['counts']['warnings']} warning(s)"]
        for it in v["issues"][:40]:
            msg.append(f"[{it['severity']}] {it['kind']} · {it['frame']}: "
                       f"{it['detail']}  → {it['suggested_fix']}")
        QMessageBox.information(self, "Validate Dataset", "\n".join(msg))

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
        QMessageBox.information(self, "Prepare Dataset Commit", "\n".join(lines))

    def _write_report(self) -> None:
        if self._session is None:
            QMessageBox.information(self, "Session Report", "No active session.")
            return
        path = write_session_report(self._session)
        self._append(f"Session report written: {path}")
        QMessageBox.information(self, "Session Report", f"Written:\n{path}")

    def _open_review(self) -> None:
        from bap.forge.dataset_store import dataset_review_paths
        from bap.gui.forge_review import ForgeReviewWindow
        from bap.forge.detection.calibration import WeakeningCalibration
        from bap.forge.labeling.session import LabelSession

        frames_dir, labels_path, calib_path = dataset_review_paths()
        session = LabelSession.open(frames_dir, labels_path)
        cal = WeakeningCalibration.load(calib_path)
        self._review = ForgeReviewWindow(session, frames_dir, cal)
        self._review.show()


__all__ = ["ForgeCollectionWindow"]
