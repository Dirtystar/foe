"""The session-scoped cursor-preview controller (Milestone 5A).

Ties together the strict manual gate, the one-and-only cursor adapter, and the
append-only audit log, and owns the session **enable** flag. It exists so the whole
two-step flow — evaluate → (operator confirms) → move exactly once → audit — is
testable without Qt.

Safety properties enforced here:
- **Disabled by default**, per process. Nothing persists the enabled flag, so it
  resets to disabled on every app launch; ``enable_for_session`` turns it on only
  for the current session.
- Movement happens **only** through :meth:`confirm_and_move`, and only when the
  gate passes at move time AND the operator confirmed. It re-evaluates with a fresh
  clock, so a scan that expired — or a World switched — while the confirmation
  dialog was open is caught and blocked.
- **At most one move per confirmation**; no queue, no retry-that-moves-again, no
  background repetition. A blocked move performs no movement and is audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bap.forge.cursor.audit import CursorPreviewAudit
from bap.forge.cursor.port import CursorPreviewPort
from bap.forge.cursor.preview import PreviewDecision, PreviewRequest, evaluate_preview


@dataclass(frozen=True)
class MoveResult:
    """Outcome of a confirm-and-move attempt."""

    moved: bool
    reason: str
    screen_point: tuple[int, int] | None = None
    decision: PreviewDecision | None = None
    audit: dict = field(default_factory=dict)


class CursorPreviewController:
    def __init__(self, cursor: CursorPreviewPort, audit: CursorPreviewAudit | None = None):
        self._cursor = cursor
        self._audit = audit
        self._enabled = False  # disabled by default; never persisted

    # --- session enable (resets to disabled every launch) -------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable_for_session(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    # --- two-step flow ------------------------------------------------------

    def preview(self, req: PreviewRequest, *, now: datetime | None = None) -> PreviewDecision:
        """Evaluate the gate WITHOUT moving — used to populate the confirmation
        dialog. Reflects the live enabled flag."""
        return evaluate_preview(self._with_enabled(req), now=now)

    def confirm_and_move(
        self, req: PreviewRequest, *, confirmed: bool, now: datetime | None = None
    ) -> MoveResult:
        """Move the cursor exactly once, iff the operator confirmed AND the gate
        still passes at this instant. Always audits the attempt. Never clicks."""
        if not confirmed:
            # Cancel / no confirmation → never move. Not audited (nothing happened).
            return MoveResult(moved=False, reason="Not confirmed — no movement.")

        decision = evaluate_preview(self._with_enabled(req), now=now)
        if not decision.ok or decision.screen_point is None:
            entry = self._audit_entry(req, decision, moved=False)
            self._write(entry)
            return MoveResult(moved=False, reason=decision.reason, decision=decision, audit=entry)

        # The single, one-shot move. No loop, no retry, no queue.
        sx, sy = decision.screen_point
        self._cursor.move_to(sx, sy)

        entry = self._audit_entry(req, decision, moved=True)
        self._write(entry)
        return MoveResult(moved=True, reason="Cursor moved — NO CLICK PERFORMED.",
                          screen_point=(sx, sy), decision=decision, audit=entry)

    # --- internals ----------------------------------------------------------

    def _with_enabled(self, req: PreviewRequest) -> PreviewRequest:
        # The gate reads enablement from the request; keep it in sync with the
        # controller's live flag so a mid-flow disable is honoured.
        if req.enabled == self._enabled:
            return req
        from dataclasses import replace

        return replace(req, enabled=self._enabled)

    def _write(self, entry: dict) -> None:
        if self._audit is not None:
            try:
                self._audit.record(entry)
            except Exception:  # never let an audit-write failure affect safety
                pass

    def _audit_entry(self, req: PreviewRequest, decision: PreviewDecision, *, moved: bool) -> dict:
        geom = req.current_geometry.to_dict() if req.current_geometry is not None else None
        return {
            "moved": moved,
            "result": decision.reason,
            "blocked_code": None if decision.ok else decision.code,
            "operator_confirmed": True,
            "world": req.world_alias,
            "hostname": req.hostname,
            "browser_mode": req.browser_mode,
            "scan_captured_at": req.captured_at.isoformat() if req.captured_at else None,
            "scan_age_s": round(decision.age_s, 3) if decision.age_s is not None else None,
            "target_pct": req.pct,
            "confidence": req.confidence,
            "weakening_value": req.weakening_value,
            "world_limit": req.world_limit,
            "weakening_decision": req.decision.value if req.decision is not None else None,
            "image_point": list(req.target_point) if req.target_point else None,
            "coordinate_trace": decision.trace.to_dict() if decision.trace is not None else None,
            "window_geometry": geom,
            "requested_screen_point": list(decision.screen_point) if decision.screen_point else None,
        }


__all__ = ["CursorPreviewController", "MoveResult"]
