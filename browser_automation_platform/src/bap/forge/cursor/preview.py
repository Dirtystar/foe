"""The strict manual gate for the cursor preview (Milestone 5A).

Every condition the milestone requires before the cursor may move once, evaluated
in a fixed order and returning the **exact** blocking reason on the first failure.
There is no fallback to a guessed coordinate: if anything is missing, stale, or
mismatched, the answer is "do not move" plus a precise reason.

Pure and Qt-free — the GUI builds a ``PreviewRequest`` from the current live scan
and window geometry, calls :func:`evaluate_preview`, and (only on success) shows a
confirmation dialog. On confirm it re-evaluates with a fresh clock so a scan that
expired, or a World the operator switched away from, while the dialog was open is
caught and blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from bap.forge.cursor.geometry import (
    CoordinateTrace,
    WindowGeometry,
    image_to_screen,
    point_in_capture,
)
from bap.forge.detection.weakening import Decision
from bap.forge.labeling.model import VALID_PCTS

DEFAULT_MAX_SCAN_AGE_S = 5.0


@dataclass(frozen=True)
class PreviewRequest:
    """An immutable snapshot of everything the gate needs. The ``*_at_scan`` fields
    are captured when the live scan ran; the ``current_*`` fields reflect the state
    *right now* (at button/confirm time), so drift is detected by comparison."""

    enabled: bool                      # cursor preview enabled for this session
    live: bool                         # came from a fresh live scan (not offline/stale file)
    browser_mode: str | None           # "managed_chromium" | "external_chrome"
    window_owned: bool                 # a known owned/attached browser window exists

    world_alias: str | None
    hostname: str | None
    selected_alias: str | None         # World currently selected in the UI
    tab_id_at_scan: str | None         # tab the World was mapped to when scanned
    current_tab_id: str | None         # tab the World is mapped to now

    # Target + safety, from the scan.
    target_point: tuple[int, int] | None   # would-click point in raw image px
    pct: int | None
    confidence: float | None
    weakening_value: int | None
    world_limit: int | None
    decision: Decision | None

    capture_w: int
    capture_h: int
    captured_at: datetime | None

    geometry_at_scan: WindowGeometry | None
    current_geometry: WindowGeometry | None

    max_age_s: float = DEFAULT_MAX_SCAN_AGE_S


@dataclass(frozen=True)
class PreviewDecision:
    """The gate's answer. ``ok`` means every condition passed and the cursor may
    move once to ``screen_point``. Otherwise ``reason`` is the exact blocker."""

    ok: bool
    code: str
    reason: str
    screen_point: tuple[int, int] | None = None
    trace: CoordinateTrace | None = None
    age_s: float | None = None
    fields: dict = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def scan_age_seconds(captured_at: datetime | None, now: datetime | None = None) -> float | None:
    if captured_at is None:
        return None
    now = now or _now()
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return (now - captured_at).total_seconds()


def evaluate_preview(req: PreviewRequest, *, now: datetime | None = None) -> PreviewDecision:
    """Return whether the cursor may move, and if not, exactly why. Conditions are
    checked in a safety-first order; the first failure wins."""
    now = now or _now()
    age = scan_age_seconds(req.captured_at, now)

    def block(code: str, reason: str) -> PreviewDecision:
        return PreviewDecision(ok=False, code=code, reason=reason, age_s=age)

    # 1. explicit session enable
    if not req.enabled:
        return block("disabled", "Cursor Preview is disabled — enable it for this session first.")
    # 2. a known, owned/attached browser window
    if req.browser_mode not in ("managed_chromium", "external_chrome") or not req.window_owned:
        return block("no_window",
                     "No owned/attached browser window — open (Managed) or attach (External) first.")
    # 3. fresh live scan (never an offline/loaded image)
    if not req.live:
        return block("not_live", "Target must come from a fresh live Test Scan, not an offline image.")
    # 4. World still selected and mapped to the same tab
    if req.selected_alias != req.world_alias:
        return block("world_switched", "World selection changed — run Test Scan on the current World.")
    if req.current_tab_id is None or req.current_tab_id != req.tab_id_at_scan:
        return block("tab_changed", "The World's browser tab changed since the scan — run Test Scan again.")
    # 5. a target badge exists
    if req.target_point is None:
        return block("no_target", "No target badge in this scan — nothing to preview.")
    # 6. percentage confidently classified (wrong-accepted gate: only accepted % have a value)
    if req.pct is None or req.pct not in VALID_PCTS:
        return block("unknown_pct",
                     "Target percentage is UNKNOWN (below the acceptance bar) — no move.")
    # 7. weakening decision must be CONTINUE
    if req.decision is not Decision.CONTINUE:
        d = req.decision.value if req.decision is not None else "UNKNOWN"
        return block("weakening_blocked", f"Weakening decision is {d} — the World would not act. No move.")
    # 8. target inside the captured viewport
    if not point_in_capture(req.target_point, req.capture_w, req.capture_h):
        return block("out_of_viewport", "Target lies outside the current Forge viewport — no move.")
    # 9. coordinates not stale
    if age is None:
        return block("no_timestamp", "Scan has no capture time — run Test Scan again.")
    if age > req.max_age_s:
        return block("expired", f"Target expired ({age:.1f}s old > {req.max_age_s:.0f}s) — run Test Scan again.")
    # 10. window geometry available
    if req.geometry_at_scan is None or req.current_geometry is None:
        return block("no_geometry",
                     "Browser window geometry is unavailable — calibrate the window before preview.")
    # 11. geometry unchanged since the scan (window not moved/resized; DPR/zoom/viewport match)
    if req.geometry_at_scan.identity() != req.current_geometry.identity():
        return block("geometry_changed",
                     "Browser window moved/resized or DPR/zoom changed since the scan — run Test Scan again.")

    geom = req.current_geometry
    trace = image_to_screen(req.target_point, geom)
    return PreviewDecision(
        ok=True, code="ok", reason="All manual-gate conditions pass.",
        screen_point=trace.screen_physical, trace=trace, age_s=age,
        fields={
            "world": req.world_alias, "hostname": req.hostname,
            "pct": req.pct, "confidence": req.confidence,
            "weakening": req.weakening_value, "world_limit": req.world_limit,
            "decision": req.decision.value,
            "image_point": list(req.target_point),
            "viewport_point": [round(v, 1) for v in trace.viewport_css],
            "screen_point": list(trace.screen_physical),
            "age_s": round(age, 2),
            # M5A.1 geometry diagnostics for the confirmation dialog.
            "window_id": geom.native_window_id or geom.window_id,
            "window_rect": list(geom.outer_rect),
            "content_rect": list(geom.content_rect) if geom.content_rect else None,
            "dpr": geom.device_pixel_ratio,
            "monitor_scale": geom.monitor_scale,
            "windows_dpi": geom.windows_dpi,
            "geometry_source": ("operator-calibrated" if geom.is_calibrated else "measured"),
        },
    )


__all__ = [
    "DEFAULT_MAX_SCAN_AGE_S",
    "PreviewRequest",
    "PreviewDecision",
    "evaluate_preview",
    "scan_age_seconds",
]
