"""M6A.1 — Manual Open & Verify: the single-click controller.

One operator-confirmed left click on the validated map badge, then use the opened
province/detail panel as an **independent second reading** of the percentage, then
**STOP**. No battle loop, no scheduler, no retry, no repeated clicking.

Guarantees enforced structurally here:

- **At most one click, ever, per invocation.** ``ClickPort.click_at`` is called from
  exactly one place, reached only after every gate passes and the operator
  confirmed. There is no loop or retry that clicks again.
- **No click without explicit confirmation** and without the session being enabled
  (the enable flag defaults off every launch and is never persisted — same
  discipline as the M5A cursor controller).
- **The full M5A/M6 safety spine is reused verbatim**: the 11-condition
  :func:`evaluate_preview` gate, re-evaluated with a fresh clock at click time, plus
  a tighter click-age bound and a post-move cursor-position check.
- **Fail-closed audit**: the pre-click ``CLICK_ARMED`` intent is written with
  :meth:`ClickAudit.record_or_raise`; if it cannot be persisted, the click is
  refused (a click with no trail is unacceptable).
- **Independent verification**: the panel percentage is read by an injected
  :class:`PanelReader` (its own observation + colour signal); the map result is only
  *compared*, never reused as the panel's answer. UNKNOWN or a mismatch is a hard
  STOP. Classes are never collapsed (20≠40, 80≠100).

Everything is Qt-free and driven by injected callables (capture / panel-present /
cursor-position / sleep / clock), so the whole flow is unit-testable with a fake
click port and saved screenshots.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bap.forge.click.audit import (
    EVENT_CLICK_ARMED,
    EVENT_CLICK_BLOCKED,
    EVENT_CLICK_EXECUTED,
    EVENT_PANEL_DETECTED,
    EVENT_PANEL_VERIFY_MATCH,
    EVENT_PANEL_VERIFY_MISMATCH,
    EVENT_PANEL_VERIFY_UNKNOWN,
    ClickAudit,
)
from bap.forge.click.constants import (
    CURSOR_TOLERANCE_PX,
    MAX_CLICK_AGE_S,
    PANEL_POLL_INTERVAL_S,
    PANEL_WAIT_TIMEOUT_S,
)
from bap.forge.click.panel_reader import PanelReading
from bap.forge.cursor.preview import PreviewRequest, evaluate_preview, scan_age_seconds

# Result states.
NOT_CONFIRMED = "NOT_CONFIRMED"
BLOCKED = "BLOCKED"
PANEL_TIMEOUT = "PANEL_TIMEOUT"
VERIFY_UNKNOWN = "UNKNOWN"
VERIFY_MISMATCH = "MISMATCH"
VERIFY_MATCH = "MATCH"

#: Result states that must stop the flow with no success (no further action).
STOP_STATES = frozenset({NOT_CONFIRMED, BLOCKED, PANEL_TIMEOUT, VERIFY_UNKNOWN, VERIFY_MISMATCH})

# Outcome of the leaner "open a province and observe the resulting UI state" flow.
OBSERVED = "OBSERVED"


@dataclass(frozen=True)
class ProvinceOpenResult:
    """Outcome of one "open a province, then observe the UI state" attempt. Honest:
    ``observation`` records exactly what the classifier saw (never reinterpreted)."""

    outcome: str                         # NOT_CONFIRMED | BLOCKED | OBSERVED
    clicked: bool
    reason: str
    observation: object | None = None    # ProvinceOpenObservation | None
    screen_point: tuple[int, int] | None = None
    blocked_code: str | None = None
    timing_ms: dict = field(default_factory=dict)

    @property
    def observed(self):
        return self.observation.observed if self.observation is not None else None

    @property
    def confirmed(self) -> bool:
        return bool(self.observation is not None and self.observation.confirmed)


@dataclass(frozen=True)
class OpenVerifyResult:
    """Outcome of one Open & Verify attempt. ``clicked`` is True iff the single
    click was actually emitted."""

    state: str
    clicked: bool
    reason: str
    map_pct: int | None = None
    map_confidence: float | None = None
    panel: PanelReading | None = None
    screen_point: tuple[int, int] | None = None
    blocked_code: str | None = None
    diagnostics_dir: str | None = None
    timing_ms: dict = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return self.state == VERIFY_MATCH

    @property
    def stopped(self) -> bool:
        return self.state in STOP_STATES


class OpenAndVerifyController:
    """Owns the single-click Open & Verify flow. One click max; no retry; then STOP."""

    def __init__(
        self,
        cursor,                 # CursorPreviewPort — move only
        click,                  # ClickPort — single click only
        panel_reader,           # PanelReader (or any object with .read(image))
        audit: ClickAudit,
        *,
        capture_fn,             # () -> fresh BGR capture (for panel wait)
        panel_present_fn,       # (image) -> bool (province panel open?)
        cursor_pos_fn=None,     # () -> (x, y) | None  (post-move verification)
        sleep_fn=time.sleep,
        diagnostics_dir=None,
        max_click_age_s: float = MAX_CLICK_AGE_S,
        panel_timeout_s: float = PANEL_WAIT_TIMEOUT_S,
        poll_interval_s: float = PANEL_POLL_INTERVAL_S,
        cursor_tolerance_px: int = CURSOR_TOLERANCE_PX,
    ):
        self._cursor = cursor
        self._click = click
        self._reader = panel_reader
        self._audit = audit
        self._capture = capture_fn
        self._panel_present = panel_present_fn
        self._cursor_pos = cursor_pos_fn
        self._sleep = sleep_fn
        self._diag = diagnostics_dir
        self._max_age = float(max_click_age_s)
        self._panel_timeout = float(panel_timeout_s)
        self._poll = float(poll_interval_s)
        self._tol = int(cursor_tolerance_px)
        self._enabled = False  # session flag; never persisted

    # --- session enable (resets to disabled every launch) -------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable_for_session(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    # --- the one flow -------------------------------------------------------
    def open_and_verify(
        self,
        req: PreviewRequest,
        *,
        map_pct: int | None,
        map_confidence: float | None,
        confirmed: bool,
        before_image=None,
        now: datetime | None = None,
    ) -> OpenVerifyResult:
        """Run the full flow: gate → move → cursor-verify → ONE click → wait panel →
        read panel → compare → STOP. Returns the outcome; never acts twice."""
        now = now or datetime.now(timezone.utc)

        # No confirmation → nothing happens at all. Not audited.
        if not confirmed:
            return OpenVerifyResult(NOT_CONFIRMED, False, "Not confirmed — no click.")

        # Session must be explicitly enabled.
        if not self._enabled:
            return self._block("disabled", "Clicking is disabled — enable it for this session first.",
                               req, map_pct, map_confidence)

        # Reuse the full 11-condition manual gate, fresh clock.
        decision = evaluate_preview(_with_enabled(req, True), now=now)
        if not decision.ok or decision.screen_point is None:
            return self._block(decision.code, decision.reason, req, map_pct, map_confidence)

        # Tighter click-age bound than the move preview.
        age = scan_age_seconds(req.captured_at, now)
        if age is None or age > self._max_age:
            return self._block("expired_click",
                               f"Target too old for a click ({age}s > {self._max_age:.0f}s) — re-scan.",
                               req, map_pct, map_confidence)

        # The map percentage must itself be an accepted value (gate 7 already
        # guarantees this via req.pct; double-check the value we will compare).
        if map_pct is None:
            return self._block("no_map_pct", "No accepted map percentage to verify — no click.",
                               req, map_pct, map_confidence)

        sx, sy = decision.screen_point

        # Fail-closed arm: persist intent BEFORE any click. If we cannot, do not click.
        armed = {
            "world": req.world_alias, "hostname": req.hostname,
            "browser_mode": req.browser_mode, "map_pct": map_pct,
            "map_confidence": map_confidence, "screen_point": [sx, sy],
            "image_point": list(req.target_point) if req.target_point else None,
            "scan_age_s": round(age, 3), "weakening_decision":
                req.decision.value if req.decision is not None else None,
        }
        try:
            self._audit.record_or_raise(EVENT_CLICK_ARMED, armed)
        except Exception:
            return self._block("audit_unavailable",
                               "Could not write the click-armed audit record — refusing to click.",
                               req, map_pct, map_confidence)

        # Place the cursor (move-only) and verify it actually landed on the target.
        t0 = time.perf_counter()
        self._cursor.move_to(sx, sy)
        if self._cursor_pos is not None:
            pos = self._cursor_pos()
            if pos is None or abs(pos[0] - sx) > self._tol or abs(pos[1] - sy) > self._tol:
                return self._block("cursor_moved",
                                   "Cursor is not on the target (moved?) — refusing to click.",
                                   req, map_pct, map_confidence, screen_point=(sx, sy))

        # THE single click. One call, one place, no loop, no retry.
        self._click.click_at(sx, sy)
        self._audit.record(EVENT_CLICK_EXECUTED, {
            "click": True, "screen_point": [sx, sy], "world": req.world_alias,
            "map_pct": map_pct, "map_confidence": map_confidence,
        })

        # Bounded wait for the province/detail panel. No second click ever.
        panel_image, waited_ms = self._wait_for_panel()
        timing = {"click_to_scan_ms": round(waited_ms, 1)}

        if panel_image is None:
            return OpenVerifyResult(
                PANEL_TIMEOUT, True,
                f"Province panel did not open within {self._panel_timeout:.1f}s — STOP (no retry).",
                map_pct=map_pct, map_confidence=map_confidence,
                screen_point=(sx, sy), timing_ms=timing)

        self._audit.record(EVENT_PANEL_DETECTED, {"world": req.world_alias,
                                                  "click_to_scan_ms": timing["click_to_scan_ms"]})

        # Independent panel read (never reuses the map result).
        tr = time.perf_counter()
        reading = self._reader.read(panel_image)
        timing["panel_read_ms"] = round((time.perf_counter() - tr) * 1000, 1)

        # Compare map vs panel → MATCH / MISMATCH / UNKNOWN (all but MATCH are STOP).
        if not reading.ok:
            state, event = VERIFY_UNKNOWN, EVENT_PANEL_VERIFY_UNKNOWN
            reason = f"Panel verification UNKNOWN — {reading.reason}. STOP."
        elif reading.pct == map_pct:
            state, event = VERIFY_MATCH, EVENT_PANEL_VERIFY_MATCH
            reason = f"Panel independently confirms {map_pct}% (map {map_pct}%). Verification complete."
        else:
            state, event = VERIFY_MISMATCH, EVENT_PANEL_VERIFY_MISMATCH
            reason = (f"MISMATCH — map {map_pct}% vs panel {reading.pct}% "
                      f"(colour {reading.color_group}). Hard STOP.")

        self._audit.record(event, {
            "world": req.world_alias, "map_pct": map_pct, "map_confidence": map_confidence,
            "panel": reading.to_dict(),
        })

        diag_dir = self._save_diagnostics(req, map_pct, map_confidence, reading, state,
                                          (sx, sy), before_image, panel_image, timing)

        return OpenVerifyResult(
            state, True, reason, map_pct=map_pct, map_confidence=map_confidence,
            panel=reading, screen_point=(sx, sy), diagnostics_dir=diag_dir, timing_ms=timing)

    # --- internals ----------------------------------------------------------
    def _block(self, code, reason, req, map_pct, map_confidence, screen_point=None) -> OpenVerifyResult:
        self._audit.record(EVENT_CLICK_BLOCKED, {
            "blocked_code": code, "reason": reason, "world": req.world_alias,
            "map_pct": map_pct, "screen_point": list(screen_point) if screen_point else None,
        })
        return OpenVerifyResult(BLOCKED, False, reason, map_pct=map_pct,
                                map_confidence=map_confidence, blocked_code=code,
                                screen_point=screen_point)

    def _wait_for_panel(self):
        """Poll capture_fn for the panel up to the timeout. Returns (image|None, ms)."""
        start = time.perf_counter()
        polls = max(1, int(round(self._panel_timeout / self._poll)))
        for i in range(polls + 1):
            img = self._capture()
            if img is not None and self._panel_present(img):
                return img, (time.perf_counter() - start) * 1000
            if i < polls:
                self._sleep(self._poll)
        return None, (time.perf_counter() - start) * 1000

    # --- open a province, then observe the resulting UI state (Milestone) ----
    def open_province_and_observe(
        self,
        req: PreviewRequest,
        *,
        confirmed: bool,
        now: datetime | None = None,
        detectors=None,
        detect_context=None,
        capture_dir=None,
        capture_confirmed: bool = True,
        exec_context: dict | None = None,
    ) -> ProvinceOpenResult:
        """Open a province with the SAME gated single click as Open & Verify, wait a
        bounded time for the UI to settle, then **observe** the resulting UI state and
        report it honestly (expected PROVINCE_PANEL). On any other observed state the
        screenshot + classifier signals + context are saved for later review; when
        ``capture_confirmed`` is set (default), a confirmed PROVINCE_PANEL is saved too
        — the first real open then grows the panel dataset whatever the outcome. No
        %-read, no retry, no next action — one click, one observation, STOP.
        """
        now = now or datetime.now(timezone.utc)
        if not confirmed:
            return ProvinceOpenResult(NOT_CONFIRMED, False, "Not confirmed — no click.")
        if not self._enabled:
            return self._block_observe(
                "disabled", "Clicking is disabled — enable it for this session first.", req)

        decision = evaluate_preview(_with_enabled(req, True), now=now)
        if not decision.ok or decision.screen_point is None:
            return self._block_observe(decision.code, decision.reason, req)

        age = scan_age_seconds(req.captured_at, now)
        if age is None or age > self._max_age:
            return self._block_observe(
                "expired_click",
                f"Target too old for a click ({age}s > {self._max_age:.0f}s) — re-scan.", req)

        sx, sy = decision.screen_point
        try:
            self._audit.record_or_raise(EVENT_CLICK_ARMED, {
                "world": req.world_alias, "hostname": req.hostname,
                "browser_mode": req.browser_mode, "screen_point": [sx, sy],
                "image_point": list(req.target_point) if req.target_point else None,
                "scan_age_s": round(age, 3), "purpose": "open_province_and_observe",
            })
        except Exception:
            return self._block_observe(
                "audit_unavailable",
                "Could not write the click-armed audit record — refusing to click.",
                req, screen_point=(sx, sy))

        self._cursor.move_to(sx, sy)
        if self._cursor_pos is not None:
            pos = self._cursor_pos()
            if pos is None or abs(pos[0] - sx) > self._tol or abs(pos[1] - sy) > self._tol:
                return self._block_observe(
                    "cursor_moved", "Cursor is not on the target (moved?) — refusing to click.",
                    req, screen_point=(sx, sy))

        # THE single click. One call, one place, no loop, no retry.
        self._click.click_at(sx, sy)
        self._audit.record(EVENT_CLICK_EXECUTED, {
            "click": True, "screen_point": [sx, sy], "world": req.world_alias,
            "purpose": "open_province_and_observe",
        })

        after_image, waited_ms = self._capture_after_settle()
        timing = {"click_to_scan_ms": round(waited_ms, 1)}

        from bap.forge.state.province_open import observe_province_open

        ctx = dict(exec_context or {})
        ctx.setdefault("world", req.world_alias)
        ctx.setdefault("hostname", req.hostname)
        ctx.setdefault("screen_point", [sx, sy])
        obs = observe_province_open(after_image, detectors=detectors,
                                    detect_context=detect_context,
                                    capture_dir=capture_dir,
                                    capture_confirmed=capture_confirmed,
                                    exec_context=ctx)
        self._audit.record("PROVINCE_OPEN_OBSERVED", {
            "world": req.world_alias, "expected": obs.expected.value,
            "observed": obs.observed.value, "confirmed": obs.confirmed,
            "confidence": round(obs.confidence, 4), "captured_path": obs.captured_path,
        })
        reason = (f"Attempted to open a province. Expected {obs.expected.value}; "
                  f"observed {obs.observed.value} (confidence {obs.confidence:.2f}).")
        if obs.captured_path:
            saved_what = "Panel frame saved" if obs.confirmed else "Saved for review"
            reason += f" {saved_what}: {obs.captured_path}."
        return ProvinceOpenResult(OBSERVED, True, reason, observation=obs,
                                  screen_point=(sx, sy), timing_ms=timing)

    def _block_observe(self, code, reason, req, screen_point=None) -> ProvinceOpenResult:
        self._audit.record(EVENT_CLICK_BLOCKED, {
            "blocked_code": code, "reason": reason, "world": req.world_alias,
            "purpose": "open_province_and_observe",
            "screen_point": list(screen_point) if screen_point else None,
        })
        return ProvinceOpenResult(BLOCKED, False, reason, screen_point=screen_point,
                                  blocked_code=code)

    def _capture_after_settle(self):
        """Wait a bounded time for the UI to transition, then capture whatever is on
        screen. Unlike ``_wait_for_panel`` this returns the last capture regardless of
        panel detection, so an unexpected state can be honestly observed + captured."""
        start = time.perf_counter()
        polls = max(1, int(round(self._panel_timeout / self._poll)))
        img = None
        for i in range(polls + 1):
            img = self._capture()
            if img is not None and self._panel_present(img):
                break   # panel appeared early — observe it now
            if i < polls:
                self._sleep(self._poll)
        return img, (time.perf_counter() - start) * 1000

    def _save_diagnostics(self, req, map_pct, map_confidence, reading, state, click_pt,
                          before_image, panel_image, timing) -> str | None:
        if self._diag is None:
            return None
        try:
            import json
            from pathlib import Path

            import cv2

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
            run = Path(self._diag) / f"openverify_{req.world_alias or 'W'}_{stamp}"
            run.mkdir(parents=True, exist_ok=True)
            if before_image is not None:
                cv2.imwrite(str(run / "before_click.png"), before_image)
            if panel_image is not None:
                cv2.imwrite(str(run / "after_click.png"), panel_image)
            if reading.crop_bgr is not None and getattr(reading.crop_bgr, "size", 0):
                cv2.imwrite(str(run / "panel_crop.png"), reading.crop_bgr)
            (run / "result.json").write_text(json.dumps({
                "state": state, "world": req.world_alias, "hostname": req.hostname,
                "click_point": list(click_pt),
                "map": {"pct": map_pct, "confidence": map_confidence},
                "panel": reading.to_dict(),
                "timing_ms": timing,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            }, indent=2), encoding="utf-8")
            return str(run)
        except Exception:
            return None


def _with_enabled(req: PreviewRequest, enabled: bool) -> PreviewRequest:
    if req.enabled == enabled:
        return req
    from dataclasses import replace
    return replace(req, enabled=enabled)


__all__ = [
    "OpenAndVerifyController", "OpenVerifyResult", "ProvinceOpenResult",
    "NOT_CONFIRMED", "BLOCKED", "PANEL_TIMEOUT", "OBSERVED",
    "VERIFY_UNKNOWN", "VERIFY_MISMATCH", "VERIFY_MATCH", "STOP_STATES",
]
