"""Vision Validation page (Milestone 4.11) — observe-only self-diagnosis.

One button — **Validate Vision** — runs the whole observe-only pipeline against
the currently selected World's live capture (or a chosen offline screenshot) and
renders a colour-coded PASS / WARNING / FAIL / INFO health report, section by
section, each with a plain-language explanation and, when not healthy, a probable
reason and a recommended operator action.

The page only observes: it reuses the existing capture + `validate_vision` and
never clicks, moves the cursor, types, or changes any threshold. Heavy work runs
in a background thread so the UI stays responsive.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bap.gui import widgets
from bap.gui.theme import DARK

_STATUS_COLOR = {"PASS": DARK.green, "WARNING": DARK.amber, "FAIL": DARK.red, "INFO": DARK.muted}


def _chip(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{_STATUS_COLOR.get(text, DARK.muted)}; font-weight:700;")
    return lab


class VisionValidationPage(QWidget):
    """Self-diagnosing Vision health page. Construct with providers so it stays
    decoupled from the main window and testable in isolation."""

    _done = Signal(object, object)   # (report_or_None, error_or_None)

    def __init__(self, *, world_aliases=None, world_getter=None, capture_fn=None,
                 classifier_provider=None, calibration_provider=None, parent=None) -> None:
        super().__init__(parent)
        # Providers (all optional so the page degrades gracefully / tests inject fakes).
        self._world_aliases = world_aliases or (lambda: [])
        self._world_getter = world_getter or (lambda alias: None)
        self._capture_fn = capture_fn                       # alias -> (image, latency_s, error)
        self._classifier_provider = classifier_provider or (lambda: None)
        self._calibration_provider = calibration_provider or (lambda: None)
        self._thread: threading.Thread | None = None
        self._last_report = None
        self._last_image = None
        self._last_alias = None
        self._build()
        self._done.connect(self._on_done)
        self.refresh_worlds()

    # --- construction ------------------------------------------------------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Vision Validation"))
        v.addWidget(widgets.muted(
            "Press Validate Vision to run the whole observe-only pipeline against the "
            "selected World and see, section by section, whether Vision is healthy."
        ))

        controls = QHBoxLayout()
        controls.addWidget(widgets.muted("World:"))
        self._world_combo = QComboBox()
        controls.addWidget(self._world_combo)
        controls.addStretch(1)
        self._validate_btn = QPushButton("Validate Vision")
        self._validate_btn.setProperty("primary", True)
        self._validate_btn.clicked.connect(self._validate_live)
        self._offline_btn = QPushButton("Validate from screenshot…")
        self._offline_btn.clicked.connect(self._validate_offline)
        self._snapshot_btn = QPushButton("Save Snapshot")
        self._snapshot_btn.setToolTip(
            "Freeze this validated frame into a permanent, reproducible, reviewable "
            "snapshot — negative or positive — so the live game changing can't lose it.")
        self._snapshot_btn.setEnabled(False)
        self._snapshot_btn.clicked.connect(self._save_snapshot)
        self._export_btn = QPushButton("Export report…")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export)
        for b in (self._validate_btn, self._offline_btn, self._snapshot_btn, self._export_btn):
            controls.addWidget(b)
        v.addLayout(controls)

        self._summary = QLabel("No validation run yet. Select a World and press Validate Vision.")
        self._summary.setStyleSheet(f"color:{DARK.muted};")
        v.addWidget(self._summary)

        # Results container (sections appended here on each run).
        self._results = QVBoxLayout()
        self._results.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._results)
        v.addWidget(holder, stretch=1)

    # --- world list --------------------------------------------------------

    def refresh_worlds(self) -> None:
        aliases = list(self._world_aliases())
        prev = self._world_combo.currentData()
        self._world_combo.blockSignals(True)
        self._world_combo.clear()
        for a in aliases:
            self._world_combo.addItem(a, a)
        if prev in aliases:
            self._world_combo.setCurrentIndex(aliases.index(prev))
        self._world_combo.blockSignals(False)

    def selected_world(self) -> str | None:
        return self._world_combo.currentData()

    # --- run (live / offline) ---------------------------------------------

    def _validate_live(self) -> None:
        alias = self.selected_world()
        if alias is None:
            QMessageBox.information(self, "Validate Vision", "No World selected. Add/attach a World first.")
            return
        if self._capture_fn is None:
            QMessageBox.information(self, "Validate Vision",
                                    "Live capture is not wired here. Use “Validate from screenshot…”.")
            return
        img, latency, err = self._capture_fn(alias)
        if img is None:
            QMessageBox.warning(self, "Validate Vision (live)",
                                f"Cannot capture World “{alias}”:\n{err}\n\n"
                                "Open the browser and Scan && Reattach, or use “Validate from screenshot…”.")
            return
        self._run_async(img, alias, latency_s=latency, live=True)

    def _validate_offline(self) -> None:
        import cv2

        path, _ = QFileDialog.getOpenFileName(self, "Validate from Forge screenshot", "", "PNG (*.png)")
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            QMessageBox.warning(self, "Validate Vision", "Could not load that image.")
            return
        self._run_async(img, self.selected_world(), latency_s=None, live=False)

    def _run_async(self, image, alias, *, latency_s, live) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._last_image = image
        self._last_alias = alias
        self._validate_btn.setEnabled(False)
        self._offline_btn.setEnabled(False)
        self._summary.setText("Validating… (running the full pipeline — this can take a few seconds)")

        def work() -> None:
            try:
                report = self.run_validation(image, alias, latency_s=latency_s, live=live)
                self._done.emit(report, None)
            except Exception as exc:  # never crash the UI over a validation
                self._done.emit(None, str(exc))

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def run_validation(self, image, alias, *, latency_s=None, live=False):
        """Run the validation synchronously (also the test entry point)."""
        from bap.forge.detection.validation import validate_vision

        world = self._world_getter(alias) if alias is not None else None
        return validate_vision(
            image, world=world, world_alias=alias,
            classifier=self._classifier_provider(),
            calibration=self._calibration_provider(),
            capture_latency_s=latency_s, live=live,
        )

    # --- render ------------------------------------------------------------

    def _on_done(self, report, error) -> None:
        self._validate_btn.setEnabled(True)
        self._offline_btn.setEnabled(True)
        if report is None:
            self._summary.setText(f"Validation failed: {error}")
            return
        self._last_report = report
        self._export_btn.setEnabled(True)
        self._snapshot_btn.setEnabled(report.scan is not None and self._last_image is not None)
        self.render_report(report)

    def _save_snapshot(self) -> None:
        """Freeze the validated frame into a reproducible snapshot, with the
        validation report bundled in. Observe-only — writes files only."""
        if self._last_report is None or self._last_report.scan is None or self._last_image is None:
            return
        from bap.gui.snapshot_actions import save_snapshot_and_offer

        world = self._world_getter(self._last_alias) if self._last_alias is not None else None
        save_snapshot_and_offer(
            self, image=self._last_image, scan=self._last_report.scan, world=world,
            classifier=self._classifier_provider(),
            validation_markdown=self._last_report.to_markdown(),
            url=getattr(world, "last_url", None),
        )

    def render_report(self, report) -> None:
        self._last_report = report
        # Clear previous results.
        while self._results.count():
            item = self._results.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        c = report.counts()
        self._summary.setText(
            f"Overall: {report.overall.value}    ·    ✅ {c['PASS']} PASS  "
            f"⚠️ {c['WARNING']} WARNING  ❌ {c['FAIL']} FAIL  ℹ️ {c['INFO']} INFO    ·    "
            f"World {report.world_alias or '(none)'} · {'live' if report.live else 'offline'}"
        )
        self._summary.setStyleSheet(f"color:{_STATUS_COLOR.get(report.overall.value, DARK.muted)}; font-weight:700;")

        for section in report.sections:
            card = widgets.Card(section.title, section.status.value)
            if card.note is not None:
                card.note.setStyleSheet(f"color:{_STATUS_COLOR.get(section.status.value, DARK.muted)}; font-weight:700;")
            card.body.addWidget(widgets.muted(section.blurb))
            grid = QGridLayout()
            grid.setContentsMargins(0, 4, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            for row, chk in enumerate(section.checks):
                grid.addWidget(_chip(chk.status.value), row, 0, Qt.AlignmentFlag.AlignTop)
                name = QLabel(chk.name); name.setStyleSheet(f"color:{DARK.ink};")
                grid.addWidget(name, row, 1, Qt.AlignmentFlag.AlignTop)
                val = QLabel(str(chk.value)); val.setStyleSheet(f"color:{DARK.ink}; font-weight:600;")
                grid.addWidget(val, row, 2, Qt.AlignmentFlag.AlignTop)
                note_txt = chk.explanation
                if chk.action:
                    note_txt = f"{chk.explanation}  →  {chk.action}"
                note = QLabel(note_txt); note.setWordWrap(True)
                note.setStyleSheet(f"color:{DARK.muted};")
                grid.addWidget(note, row, 3, Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(3, 1)
            holder = QWidget(); holder.setLayout(grid)
            card.body.addWidget(holder)
            self._results.addWidget(card)

    def _export(self) -> None:
        if self._last_report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export validation report",
                                              "VISION_VALIDATION_REPORT.md", "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._last_report.to_markdown())
        except Exception as exc:
            QMessageBox.warning(self, "Export report", f"Could not write report:\n{exc}")


__all__ = ["VisionValidationPage"]
