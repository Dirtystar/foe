"""Forge Vision Debugger / Test Scan window — observe-only.

Shows exactly what the detector sees for one captured frame: the analyzed
region, every detected badge with its percentage/confidence/centre, the fixed
side-panel pill separately, the sector a strategy would select, a proposed click
point drawn as a cross, and a plain-language explanation — under a permanent
OBSERVE ONLY banner. Nothing here clicks. Artifacts can be saved for the record.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bap.forge.detection.scan import OBSERVE_ONLY_BANNER, annotate, build_scan


def bgr_to_qimage(bgr) -> QImage:
    import cv2

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _enabled_req(req):
    """A copy of a PreviewRequest with the session-enable flag forced on, used only
    to *display* the gate decision before the operator confirms (the controller
    re-evaluates the real gate at click time)."""
    if getattr(req, "enabled", False):
        return req
    from dataclasses import replace
    return replace(req, enabled=True)


class _AnnotatedView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 400)
        self._image: QImage | None = None

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 16, 14))
        if self._image is None:
            return
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        ox, oy = (self.width() - iw * scale) / 2, (self.height() - ih * scale) / 2
        painter.drawImage(QRectF(ox, oy, iw * scale, ih * scale), self._image)


class DebuggerWindow(QMainWindow):
    """Displays one observe-only scan. `image` is a BGR ndarray."""

    def __init__(self, image, *, world=None, classifier=None, source: str = "",
                 weakening_region=None, rois=None, geometry=None,
                 dataset_dir=None, cursor_controller=None, cursor_context=None,
                 open_verify_controller=None, panel_calibration=None) -> None:
        super().__init__()
        self._image = image
        self._classifier = classifier
        self._world = world
        self._source = source
        # Where "Label in Review Mode" adds this frame. None => THE canonical
        # Reviewed Dataset (dataset_store); tests may pass an isolated dir.
        self._dataset_dir = dataset_dir
        self._review = None
        # Manual one-shot cursor preview (Milestone 5A). Both optional and safe by
        # default: with no controller the section is unavailable; disabled until the
        # operator explicitly enables it for this session.
        self._cursor_controller = cursor_controller
        self._cursor_context = cursor_context
        # M6A.1 — Manual Open & Verify (one click, then read the panel). Optional and
        # safe by default: with no controller the section is unavailable; disabled
        # until the operator explicitly enables clicking for this session.
        self._open_verify_controller = open_verify_controller
        # M6A.1 — Panel Click Point Calibration (measurement only; never clicks the
        # action). Optional store of operator-marked next-button points.
        self._panel_calibration = panel_calibration
        self._scan = build_scan(image, world=world, classifier=classifier,
                                weakening_region=weakening_region, rois=rois,
                                geometry=geometry)
        self.setWindowTitle(f"Forge Vision Debugger — {source or 'scan'}  ·  OBSERVE ONLY")

        central = QWidget()
        root = QVBoxLayout(central)

        banner = QLabel(OBSERVE_ONLY_BANNER)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(
            "background:#a01818; color:white; font-weight:bold; font-size:15px; padding:6px;"
        )
        root.addWidget(banner)
        root.addWidget(self._build_ui_state_label())

        body = QHBoxLayout()
        self.view = _AnnotatedView()
        self.view.set_image(bgr_to_qimage(annotate(image, self._scan)))
        body.addWidget(self.view, stretch=3)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(self._scan.explanation())
        self.details.setMinimumWidth(320)
        body.addWidget(self.details, stretch=2)
        root.addLayout(body)

        controls = QHBoxLayout()
        self.save_button = QPushButton("Save artifacts…")
        self.save_button.clicked.connect(self._on_save)
        controls.addWidget(self.save_button)
        self.review_button = QPushButton("Label in Review Mode…")
        self.review_button.setToolTip(
            "Correct these live detections: click to add, right-click to remove, "
            "keys 1-5 set 20/40/60/80/100. Saved as live ground truth.")
        self.review_button.clicked.connect(self._on_label_review)
        controls.addWidget(self.review_button)
        self.snapshot_button = QPushButton("Save Snapshot")
        self.snapshot_button.setToolTip(
            "Freeze this exact scan into a permanent, reproducible, reviewable "
            "snapshot so the live game changing can never lose it.")
        self.snapshot_button.clicked.connect(self._on_save_snapshot)
        controls.addWidget(self.snapshot_button)
        controls.addStretch(1)
        note = QLabel("Real clicking stays disabled until you confirm these detections.")
        controls.addWidget(note)
        root.addLayout(controls)

        root.addWidget(self._build_cursor_preview_section())
        root.addWidget(self._build_open_verify_section())

        self.setCentralWidget(central)

    # --- UI state indicator: "Where am I?" (Milestone A, read-only) ----------

    def _build_ui_state_label(self) -> "QLabel":
        """A read-only line answering "which Forge screen is this?" for the current
        image. Reuses this scan's detections (no second scan); observe-only — it
        drives no automation. Failures degrade to a quiet UNKNOWN, never a crash."""
        label = QLabel("UI state: —")
        label.setStyleSheet("color:#274; padding:2px 6px;")
        try:
            from bap.forge.state.detectors import DetectContext
            from bap.forge.state.screen_state import classify_screen

            ctx = DetectContext(map_detections=list(self._scan.detections))
            r = classify_screen(self._image, context=ctx)
            cands = "  ".join(f"{s.value}:{v:.2f}" for s, v in r.candidates.items())
            label.setText(f"UI state: {r.state.value}   (confidence {r.confidence:.2f})   ·   {cands}")
            label.setToolTip(r.reason)
        except Exception:
            label.setText("UI state: UNKNOWN (detector unavailable)")
        return label

    # --- Manual Open & Verify: one click, then read the panel (M6A.1) --------

    def _build_open_verify_section(self):
        """A separate, warning-styled panel for the single Open & Verify click. One
        gated, operator-confirmed left click that opens the province panel; the panel
        percentage is then read independently and compared to the map. Then STOP —
        there is no battle, loop, retry, or next-action button here."""
        from PySide6.QtWidgets import QFrame

        box = QFrame()
        box.setObjectName("openVerifyBox")
        box.setStyleSheet("#openVerifyBox { border: 2px solid #A21C34; border-radius: 6px; }")
        lay = QVBoxLayout(box)
        title = QLabel("Open Target & Verify  —  ONE manual left click, then STOP")
        title.setStyleSheet("color:#A21C34; font-weight:bold;")
        lay.addWidget(title)

        row = QHBoxLayout()
        self.click_state_label = QLabel("Clicking: DISABLED")
        self.click_state_label.setStyleSheet("font-weight:bold;")
        row.addWidget(self.click_state_label)
        self.enable_click_button = QPushButton("Enable clicking for this session")
        self.enable_click_button.clicked.connect(self._on_enable_clicking)
        row.addWidget(self.enable_click_button)
        self.open_verify_button = QPushButton("Open Target && Verify")
        self.open_verify_button.setEnabled(False)
        self.open_verify_button.clicked.connect(self._on_open_and_verify)
        row.addWidget(self.open_verify_button)
        # Open the province, then observe the resulting UI state (expected PROVINCE_PANEL).
        self.open_observe_button = QPushButton("Open Province && Observe State")
        self.open_observe_button.setEnabled(False)
        self.open_observe_button.clicked.connect(self._on_open_province_observe)
        row.addWidget(self.open_observe_button)
        # Calibration-only tool: teach the next-action button's position. Never clicks it.
        self.calibrate_panel_button = QPushButton("Calibrate Next-Button Point…")
        self.calibrate_panel_button.setToolTip(
            "Measurement only: mark where the NEXT action button sits inside an open "
            "panel, on several Worlds/positions, to see if it is at a fixed relative "
            "spot. No action click is ever performed.")
        self.calibrate_panel_button.clicked.connect(self._on_panel_calibration)
        self.calibrate_panel_button.setEnabled(
            bool(self._panel_calibration is not None and self._cursor_context is not None))
        row.addWidget(self.calibrate_panel_button)
        row.addStretch(1)
        lay.addLayout(row)

        self.open_verify_result_label = QLabel("")
        self.open_verify_result_label.setWordWrap(True)
        lay.addWidget(self.open_verify_result_label)

        if self._open_verify_controller is None or self._cursor_context is None:
            self.enable_click_button.setEnabled(False)
            self.click_state_label.setText("Clicking: UNAVAILABLE (no click adapter / not a live scan)")
        return box

    def _on_enable_clicking(self) -> None:
        if self._open_verify_controller is None:
            return
        self._open_verify_controller.enable_for_session()
        self.click_state_label.setText("Clicking: ENABLED (this session only)")
        self.open_verify_button.setEnabled(True)
        self.open_observe_button.setEnabled(True)
        self.enable_click_button.setEnabled(False)

    def _on_open_and_verify(self) -> None:
        """Confirm, perform exactly one click, wait for the panel, read it
        independently, and report MAP vs PANEL. Then STOP."""
        ctl, ctx = self._open_verify_controller, self._cursor_context
        if ctl is None or ctx is None:
            self.open_verify_result_label.setText("Open & Verify is unavailable.")
            return
        # Show the gate/target details and require an explicit confirmation first.
        from bap.forge.cursor.preview import evaluate_preview
        req = self._build_preview_request()
        decision = evaluate_preview(_enabled_req(req))
        if not decision.ok:
            self.open_verify_result_label.setStyleSheet("color:#A21C34;")
            self.open_verify_result_label.setText(f"Blocked: {decision.reason}")
            return
        fields = self._cursor_target_fields()
        if not self._confirm_open_and_verify(decision, fields):
            self.open_verify_result_label.setStyleSheet("")
            self.open_verify_result_label.setText("Cancelled — no click.")
            return
        # Re-build NOW (fresh clock + live getters) so drift while the dialog was
        # open is caught inside the controller's own gate re-evaluation.
        res = ctl.open_and_verify(
            self._build_preview_request(),
            map_pct=fields.get("pct"), map_confidence=fields.get("confidence"),
            confirmed=True, before_image=self._image)
        self._show_open_verify_result(res)

    def _confirm_open_and_verify(self, decision, fields) -> bool:
        f = decision.fields
        lines = [
            f"World: {f.get('world')}  ({f.get('hostname')})",
            f"MAP badge: {f.get('pct')}%   confidence {f.get('confidence')}",
            f"Weakening: {f.get('weakening')}   decision {f.get('decision')}",
            f"Screen point: {f.get('screen_point')}   ·   scan age {f.get('age_s')} s",
            "",
            "ONE left click will be performed at the point above.",
            "The opened panel percentage will then be read independently and",
            "compared to the map. A mismatch or UNKNOWN is a hard STOP.",
            "There is NO battle, loop, or repeated clicking.",
        ]
        box = QMessageBox(self)
        box.setWindowTitle("Open Target & Verify — perform ONE click")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("\n".join(lines))
        go = box.addButton("Click Once && Verify", QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def _show_open_verify_result(self, res) -> None:
        from bap.forge.click.open_verify import VERIFY_MATCH
        map_line = f"MAP: {res.map_pct}%  (confidence {res.map_confidence})"
        if res.panel is not None:
            panel_line = (f"PANEL: {res.panel.pct}%  (confidence {round(res.panel.confidence, 2)}, "
                          f"colour {res.panel.color_group})")
        else:
            panel_line = "PANEL: —"
        verdict = {"MATCH": "Panel verification: MATCH ✅  — STOPPED, verification complete.",
                   "MISMATCH": "Panel verification: MISMATCH ⛔ — hard STOP.",
                   "UNKNOWN": "Panel verification: UNKNOWN ⛔ — hard STOP.",
                   "PANEL_TIMEOUT": "Panel did not open — STOP (no retry).",
                   "BLOCKED": f"Blocked: {res.reason}",
                   "NOT_CONFIRMED": "Cancelled — no click."}.get(res.state, res.reason)
        colour = "#1B7A3D" if res.state == VERIFY_MATCH else "#A21C34"
        self.open_verify_result_label.setStyleSheet(f"color:{colour}; font-weight:bold;")
        self.open_verify_result_label.setText(f"{map_line}\n{panel_line}\n{verdict}")

    def _on_open_province_observe(self) -> None:
        """Open the province with one gated click, then honestly observe the
        resulting UI state (expected PROVINCE_PANEL). Reports exactly what it saw; an
        unexpected state is saved for later review. No %-read, no retry."""
        ctl, ctx = self._open_verify_controller, self._cursor_context
        if ctl is None or ctx is None:
            self.open_verify_result_label.setText("Open & Observe is unavailable.")
            return
        from bap.forge.cursor.preview import evaluate_preview
        req = self._build_preview_request()
        decision = evaluate_preview(_enabled_req(req))
        if not decision.ok:
            self.open_verify_result_label.setStyleSheet("color:#A21C34;")
            self.open_verify_result_label.setText(f"Blocked: {decision.reason}")
            return
        if not self._confirm_open_and_verify(decision, self._cursor_target_fields()):
            self.open_verify_result_label.setStyleSheet("")
            self.open_verify_result_label.setText("Cancelled — no click.")
            return
        capture_dir = exec_context = None
        try:
            from bap.ops.paths import ensure_dirs, get_paths
            capture_dir = ensure_dirs(get_paths()).data_dir / "forge" / "captures"
        except Exception:
            capture_dir = None
        h, w = (self._image.shape[0], self._image.shape[1])
        exec_context = {"world": ctx.world_alias, "resolution": [w, h],
                        "browser_mode": ctx.browser_mode}
        res = ctl.open_province_and_observe(
            self._build_preview_request(), confirmed=True,
            capture_dir=capture_dir, exec_context=exec_context)
        self._show_open_province_result(res)

    def _show_open_province_result(self, res) -> None:
        from bap.forge.click.open_verify import BLOCKED, NOT_CONFIRMED, OBSERVED
        from bap.forge.state.screen_state import ScreenState

        if res.outcome == NOT_CONFIRMED:
            self.open_verify_result_label.setStyleSheet("")
            self.open_verify_result_label.setText("Cancelled — no click.")
            return
        if res.outcome == BLOCKED:
            self.open_verify_result_label.setStyleSheet("color:#A21C34;")
            self.open_verify_result_label.setText(f"Blocked: {res.reason}")
            return
        obs = res.observation
        confirmed = res.observed is ScreenState.PROVINCE_PANEL
        lines = [
            "Attempted: open province",
            "Expected:  PROVINCE_PANEL",
            f"Observed:  {res.observed.value}   (confidence {obs.confidence:.2f})",
        ]
        if confirmed:
            saved = f"  Panel frame saved: {obs.captured_path}" if obs.captured_path else ""
            lines.append("Result: PROVINCE_PANEL ✅  — verified. STOPPED." + saved)
        else:
            tail = f"  Saved for review: {obs.captured_path}" if obs.captured_path else ""
            lines.append(f"Result: {res.observed.value} — not the expected panel. STOPPED.{tail}")
        self.open_verify_result_label.setStyleSheet(
            f"color:{'#1B7A3D' if confirmed else '#A21C34'}; font-weight:bold;")
        self.open_verify_result_label.setText("\n".join(lines))

    # --- Panel Click Point Calibration (measurement only) -------------------

    def _on_panel_calibration(self) -> None:
        """Capture one operator-marked next-button point (after a short countdown so
        the operator can hover the intended button), store it with full context, and
        report the running variance verdict. NEVER performs an action click."""
        store, ctx = self._panel_calibration, self._cursor_context
        if store is None or ctx is None:
            return
        pos_getter = getattr(ctx, "cursor_position_getter", None)
        if pos_getter is None:
            self.open_verify_result_label.setText(
                "Calibration needs the cursor-position reader (Windows) — unavailable here.")
            return

        from PySide6.QtCore import QTimer

        box = QMessageBox(self)
        box.setWindowTitle("Calibrate Next-Button Point")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Hover the OS cursor over the NEXT action button in the open "
                    "panel.\nCapturing the cursor position in 3 seconds…\n"
                    "(This records a point only — nothing is clicked.)")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel)
        QTimer.singleShot(3000, lambda: self._capture_calibration_sample(box))
        box.exec()

    def _capture_calibration_sample(self, box) -> None:
        store, ctx = self._panel_calibration, self._cursor_context
        try:
            box.accept()
        except Exception:
            pass
        try:
            from bap.forge.click.panel_calibration import PanelClickSample

            pos = ctx.cursor_position_getter()
            geom = ctx.current_geometry_getter()
            if pos is None or geom is None:
                self.open_verify_result_label.setText(
                    "Calibration: cursor position or geometry unavailable — not stored.")
                return
            rect = geom.content_rect or geom.outer_rect
            sample = PanelClickSample(
                screen_point=(int(pos[0]), int(pos[1])),
                panel_rect=tuple(int(v) for v in rect),
                viewport=(int(geom.viewport_w), int(geom.viewport_h)),
                resolution=(int(geom.capture_w), int(geom.capture_h)),
                dpr=float(geom.device_pixel_ratio), zoom=float(geom.monitor_scale),
                browser_mode=ctx.browser_mode, world=ctx.world_alias)
            store.add(sample)
            v = store.analyze()
            nx, ny = sample.normalized
            tag = "VERIFIED ✅" if v.verified else "not yet verified"
            self.open_verify_result_label.setStyleSheet("")
            self.open_verify_result_label.setText(
                f"Calibration sample stored at normalized ({nx:.3f}, {ny:.3f}). "
                f"{v.samples} sample(s) — {tag}. {v.reason}")
        except Exception as exc:
            self.open_verify_result_label.setText(f"Calibration failed: {exc}")

    # --- Manual one-shot cursor preview (Milestone 5A) ----------------------

    def _build_cursor_preview_section(self):
        """A clearly-separated, warning-styled panel for the manual cursor preview.
        Disabled by default; there is no Run/Fight/Execute here — one gated,
        one-shot MOVE that never clicks."""
        from PySide6.QtWidgets import QFrame

        box = QFrame()
        box.setObjectName("cursorPreviewBox")
        box.setStyleSheet(
            "#cursorPreviewBox { border: 2px solid #C0563A; border-radius: 6px; }")
        lay = QVBoxLayout(box)
        title = QLabel("Cursor Preview  —  manual, one-shot MOVE only · NEVER clicks")
        title.setStyleSheet("color:#C0563A; font-weight:bold;")
        lay.addWidget(title)

        row = QHBoxLayout()
        self.cursor_state_label = QLabel("Cursor Preview: DISABLED")
        self.cursor_state_label.setStyleSheet("font-weight:bold;")
        row.addWidget(self.cursor_state_label)
        self.enable_cursor_button = QPushButton("Enable for this session")
        self.enable_cursor_button.clicked.connect(self._on_enable_cursor_preview)
        row.addWidget(self.enable_cursor_button)
        self.preview_cursor_button = QPushButton("Preview Cursor Target")
        self.preview_cursor_button.setEnabled(False)
        self.preview_cursor_button.clicked.connect(self._on_preview_cursor_target)
        row.addWidget(self.preview_cursor_button)
        # M5A.1 — measure the real content origin once, when CDP cannot.
        self.calibrate_origin_button = QPushButton("Set Browser Content Origin…")
        self.calibrate_origin_button.setToolTip(
            "Mark the top-left and bottom-right of the Forge content area so the "
            "cursor point can be mapped to the physical screen. No click is sent to Chrome.")
        self.calibrate_origin_button.clicked.connect(self._on_calibrate_content_origin)
        can_calibrate = bool(self._cursor_context and getattr(
            self._cursor_context, "calibrate_content_origin", None))
        self.calibrate_origin_button.setEnabled(can_calibrate)
        row.addWidget(self.calibrate_origin_button)
        row.addStretch(1)
        lay.addLayout(row)

        self.cursor_result_label = QLabel("")
        self.cursor_result_label.setWordWrap(True)
        lay.addWidget(self.cursor_result_label)

        if self._cursor_controller is None:
            self.enable_cursor_button.setEnabled(False)
            self.cursor_state_label.setText("Cursor Preview: UNAVAILABLE (no cursor adapter)")
        return box

    def _on_calibrate_content_origin(self) -> None:
        """Run the operator content-origin calibration (M5A.1). Persists the content
        rectangle for the current geometry key; never sends input to Chrome."""
        cb = getattr(self._cursor_context, "calibrate_content_origin", None) if self._cursor_context else None
        if cb is None:
            self.cursor_result_label.setText("Content-origin calibration is unavailable.")
            return
        try:
            ok = cb()
        except Exception as exc:
            self.cursor_result_label.setText(f"Calibration failed: {exc}")
            return
        self.cursor_result_label.setStyleSheet("")
        self.cursor_result_label.setText(
            "Browser content origin saved." if ok else "Calibration cancelled.")

    def _on_enable_cursor_preview(self) -> None:
        if self._cursor_controller is None:
            return
        self._cursor_controller.enable_for_session()
        self.cursor_state_label.setText("Cursor Preview: ENABLED (this session only)")
        self.preview_cursor_button.setEnabled(True)
        self.enable_cursor_button.setEnabled(False)

    def _cursor_target_fields(self):
        """Pull the target + safety facts from THIS scan (the other half of the
        gate; identity/geometry come from the injected context)."""
        sel = self._scan.selection.detection
        weak = self._scan.weakening
        return {
            "target_point": (int(sel.cx), int(sel.cy)) if sel is not None else None,
            "pct": sel.pct if sel is not None else None,
            "confidence": float(sel.confidence) if sel is not None else None,
            "weakening_value": weak.value if (weak is not None and weak.value is not None) else None,
            "world_limit": self._scan.world_limit,
            "decision": self._scan.decision,
        }

    def _build_preview_request(self):
        ctx = self._cursor_context
        enabled = bool(self._cursor_controller and self._cursor_controller.enabled)
        return ctx.build_request(enabled=enabled, **self._cursor_target_fields())

    def _on_preview_cursor_target(self) -> None:
        """Evaluate the strict gate and, only if it passes, show a two-step
        confirmation dialog. On confirm, move the cursor exactly once."""
        if self._cursor_controller is None or self._cursor_context is None:
            self.cursor_result_label.setText("Cursor preview is unavailable.")
            return
        req = self._build_preview_request()
        decision = self._cursor_controller.preview(req)
        if not decision.ok:
            self.cursor_result_label.setStyleSheet("color:#C0563A;")
            hint = ""
            if decision.code == "no_geometry":
                status = self._cursor_context.geometry_status_getter()
                if status:
                    hint = f"  ({status})"
            self.cursor_result_label.setText(f"Blocked: {decision.reason}{hint}")
            return
        if not self._confirm_cursor_move(decision):
            self.cursor_result_label.setStyleSheet("")
            self.cursor_result_label.setText("Cancelled — no movement.")
            return
        # Re-build the request NOW (fresh clock + live getters) so a scan that
        # expired or a World switched while the dialog was open is caught.
        result = self._cursor_controller.confirm_and_move(self._build_preview_request(),
                                                          confirmed=True)
        if result.moved:
            self.cursor_result_label.setStyleSheet("color:#C0563A; font-weight:bold;")
            self.cursor_result_label.setText(
                f"Cursor moved to {result.screen_point} — NO CLICK PERFORMED. "
                + self._after_move_verification(result))
        else:
            self.cursor_result_label.setStyleSheet("color:#C0563A;")
            self.cursor_result_label.setText(f"Blocked at move time: {result.reason}")

    def _confirm_cursor_move(self, decision) -> bool:
        """A two-step confirmation. Cancel is the default and Escape cancels; there
        is no Enter-to-move and no keyboard shortcut for Move Cursor."""
        f = decision.fields
        lines = [
            f"World: {f.get('world')}  ({f.get('hostname')})",
            f"Badge: {f.get('pct')}%   confidence {f.get('confidence')}",
            f"Weakening: {f.get('weakening')}   limit {f.get('world_limit')}   "
            f"decision {f.get('decision')}",
            "",
            f"Browser window {f.get('window_id')}  rect {f.get('window_rect')}",
            f"Content rect:   {f.get('content_rect')}   ({f.get('geometry_source')})",
            f"DPR {f.get('dpr')}   ·   Windows scaling {f.get('monitor_scale')}"
            + (f"  (DPI {f.get('windows_dpi')})" if f.get('windows_dpi') else ""),
            "",
            f"Image point:    {f.get('image_point')}",
            f"Viewport point: {f.get('viewport_point')}",
            f"Screen point:   {f.get('screen_point')}",
            f"Scan age: {f.get('age_s')} s",
            "",
            "The cursor will move once. No click will be performed.",
        ]
        box = QMessageBox(self)
        box.setWindowTitle("Move Cursor to Preview Point")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("\n".join(lines))
        move_btn = box.addButton("Move Cursor", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)     # Cancel is the default safe action
        box.setEscapeButton(cancel_btn)      # Escape cancels, never moves
        box.exec()
        return box.clickedButton() is move_btn

    def _after_move_verification(self, result) -> str:
        """Optionally re-read the cursor position and a fresh screenshot to report
        requested-vs-actual delta and whether geometry held. Never clicks."""
        ctx = self._cursor_context
        getter = getattr(ctx, "cursor_position_getter", None)
        if getter is None:
            return "(actual position not available)"
        try:
            actual = getter()
        except Exception:
            actual = None
        if actual is None or result.screen_point is None:
            return "(actual position not available)"
        dx = actual[0] - result.screen_point[0]
        dy = actual[1] - result.screen_point[1]
        return f"actual {actual}, delta ({dx},{dy})."

    def _on_label_review(self) -> None:
        """Add this live capture to THE canonical Reviewed Dataset and open it in
        Review Mode so the operator can add / correct badges (keys 1-5), remove
        false positives, and save the result as ground truth. There is exactly one
        editable dataset (dataset_store): this frame lands there, and the review
        edits that exact dataset — never a scattered scratch location (M4.15)."""
        from bap.forge import dataset_store
        from bap.forge.detection.calibration import WeakeningCalibration
        from bap.forge.detection.detector import BadgeDetector
        from bap.forge.labeling.session import LabelSession
        from bap.gui.forge_review import ForgeReviewWindow

        try:
            alias = getattr(self._world, "alias", None) or (self._source.split()[0] if self._source else None)
            name, _is_new = dataset_store.add_frame(
                self._image, alias=alias, scan=self._scan, dataset_dir=self._dataset_dir)
            if self._dataset_dir is not None:
                root = Path(self._dataset_dir)
                frames_dir = str(root / dataset_store.FRAMES_DIRNAME)
                labels_path = str(root / dataset_store.LABELS_NAME)
                calibration_path = str(root / dataset_store.CALIB_NAME)
            else:
                frames_dir, labels_path, calibration_path = dataset_store.dataset_review_paths(create=True)
            session = LabelSession.open(frames_dir, labels_path)
            for i in range(session.total):
                session.goto(i)
                if session.current_file() == name:
                    break
            cal = WeakeningCalibration.load(calibration_path)
            self._review = ForgeReviewWindow(session, frames_dir, cal, world=self._world,
                                             detector=BadgeDetector())
            self._review.resize(1360, 800)
            self._review.show()
        except Exception as exc:  # never crash the debugger over a review launch
            QMessageBox.warning(self, "Review Mode", f"Could not open Review Mode:\n{exc}")

    def _on_save_snapshot(self) -> None:
        """Freeze this scan into a reproducible snapshot (raw + annotated + trace +
        world + calibration + labels + metadata), then offer Open-in-Review /
        Import. Observe-only — it writes files, nothing more."""
        from bap.forge.detection.detector import BadgeDetector
        from bap.gui.snapshot_actions import save_snapshot_and_offer

        save_snapshot_and_offer(
            self, image=self._image, scan=self._scan, world=self._world,
            classifier=self._classifier, detector=BadgeDetector(),
            url=getattr(self._world, "last_url", None),
        )

    def _on_save(self) -> None:
        from bap.forge.detection.scan import save_scan

        out = QFileDialog.getExistingDirectory(self, "Save scan artifacts to…")
        if not out:
            return
        try:
            paths = save_scan(self._image, self._scan, out, classifier=self._classifier)
        except Exception as exc:  # never crash the UI over a save
            QMessageBox.warning(self, "Save", f"Could not save artifacts:\n{exc}")
            return
        QMessageBox.information(
            self, "Saved",
            "Saved:\n" + "\n".join(Path(p).name for p in paths.values()),
        )


def _bundled_classifier():
    """A classifier trained from the reviewed grading set **and** the reviewed
    live-browser scans, so live-scale badges have same-scale exemplars. Returns
    None if nothing is reviewed (the debugger then shows detections without %)."""
    try:
        from bap.forge.detection.classify import (
            default_assets_root,
            default_label_sources,
            train_from_sources,
        )

        root = default_assets_root()
        if root is None:
            return None
        sources = default_label_sources(root)
        return train_from_sources(sources) if sources else None
    except Exception:
        return None


def run_over_folder(frames_dir: str, world=None) -> int:
    """Offline debugger: step through the PNGs in a folder. Useful for verifying
    the detector on saved screenshots with no browser."""
    import sys

    import cv2
    from PySide6.QtWidgets import QApplication

    frames = sorted(Path(frames_dir).glob("*.png"))
    if not frames:
        raise SystemExit(f"no .png frames in {frames_dir}")
    qapp = QApplication.instance() or QApplication(sys.argv)
    clf = _bundled_classifier()
    windows = []
    for p in frames[:1]:  # open the first; Next/Prev could be added later
        img = cv2.imread(str(p))
        win = DebuggerWindow(img, world=world, classifier=clf, source=p.name)
        win.resize(1280, 760)
        win.show()
        windows.append(win)
    return int(qapp.exec())


__all__ = ["DebuggerWindow", "bgr_to_qimage", "run_over_folder"]
