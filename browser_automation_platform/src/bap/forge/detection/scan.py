"""Observe-only Vision Debugger core.

Turns one captured frame into a `DebugScan`: the detected map badges (centre,
bbox, %, confidence), the fixed side-panel pill reported separately, the sector a
strategy *would* select for a World, a proposed click point, and a
human-readable explanation. It renders an annotated image and can save the
artifacts. It never clicks — the proposed click point is drawn, never performed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bap.core.domain.models import Rect
from bap.forge.detection.classify import PercentClassifier, percent_patch
from bap.forge.detection.detector import (
    DEFAULT_REGION,
    PANEL_PILL_CENTER,
    BadgeDetector,
    Detection,
)
from bap.forge.detection.weakening import Decision, WeakeningRead, decide, read_ocr

OBSERVE_ONLY_BANNER = "OBSERVE ONLY — NO CLICK PERFORMED"


@dataclass
class Selection:
    detection: Detection | None
    reasons: list[str] = field(default_factory=list)
    considered: list[Detection] = field(default_factory=list)     # eligible (allowed %) badges
    ignored: list[tuple[Detection, str]] = field(default_factory=list)  # (badge, reason)

    @property
    def click_point(self) -> tuple[int, int] | None:
        return self.detection.center if self.detection is not None else None


@dataclass
class DebugScan:
    detections: list[Detection]
    panel: Detection | None
    region: tuple[int, int, int, int]
    selection: Selection
    world_alias: str | None = None
    width: int = 0
    height: int = 0
    created_at: str = ""
    # Current-weakening safety gate.
    weakening: WeakeningRead | None = None
    weakening_region: Rect | None = None
    world_limit: int | None = None
    decision: Decision = Decision.UNKNOWN

    def explanation(self) -> str:
        """The full per-World decision, in the order the pipeline runs it."""
        lines = [OBSERVE_ONLY_BANNER, ""]
        lines.append(f"World: {self.world_alias or '(none)'}")

        # 1-2. Safety gate — decides whether badges are even considered.
        if self.weakening is not None:
            val = self.weakening.value if self.weakening.value is not None else "unreadable"
            lines.append(f"Weakening: {val}   (confidence {self.weakening.confidence:.2f})")
            lines.append(f"Limit: {self.world_limit if self.world_limit is not None else '(none)'}")
            lines.append(f"Decision: {self.decision.value}")
            if self.decision is Decision.STOP:
                lines.append("  → at/over the limit: this World would STOP (no target)")
            elif self.decision is Decision.UNKNOWN:
                lines.append("  → weakening not confidently read: NO ACTION (fail-safe)")

        # 3-4. Detected + ignored badges.
        detected = "  ".join(f"{d.pct}%" if d.pct is not None else "?" for d in self.detections) or "none"
        lines.append(f"Detected: {detected}")
        if self.selection.ignored:
            for d, reason in self.selection.ignored:
                pct = f"{d.pct}%" if d.pct is not None else "?"
                lines.append(f"Ignored: {pct} ({reason})")
        else:
            lines.append("Ignored: none")

        # 5-6. Selected target + reason + would-click (gated by the safety gate).
        sel = self.selection.detection
        if sel is not None:
            lines.append(f"Selected: {sel.pct}%  confidence {sel.confidence:.2f}")
            lines.append("Reason: " + " ".join(self.selection.reasons))
            if self.weakening is None:
                lines.append(f"Would click: x={sel.cx} y={sel.cy}   "
                             "(weakening region not calibrated — gate not evaluated)")
            elif self.decision is Decision.CONTINUE:
                lines.append(f"Would click: x={sel.cx} y={sel.cy}")
            else:
                lines.append(f"Would click: BLOCKED by gate ({self.decision.value}) — no action.  "
                             f"candidate x={sel.cx} y={sel.cy}")
        else:
            lines.append("Selected: none")
            if self.selection.reasons:
                lines.append("Reason: " + " ".join(self.selection.reasons))
            lines.append("Would click: (nothing — no target)")

        lines.append("")
        lines.append(OBSERVE_ONLY_BANNER)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        wr = self.weakening_region
        return {
            "observe_only": True,
            "created_at": self.created_at,
            "world": self.world_alias,
            "size": [self.width, self.height],
            "analyzed_region": list(self.region),
            "weakening": {
                "read": self.weakening.to_dict() if self.weakening else None,
                "region": [wr.x, wr.y, wr.w, wr.h] if wr else None,
                "world_limit": self.world_limit,
                "decision": self.decision.value,
            },
            "detections": [d.to_dict() for d in self.detections],
            "panel_pill": self.panel.to_dict() if self.panel else None,
            "selection": {
                "click_point": list(self.selection.click_point) if self.selection.click_point else None,
                "detection": self.selection.detection.to_dict() if self.selection.detection else None,
                "reasons": self.selection.reasons,
                "considered": [d.to_dict() for d in self.selection.considered],
                "ignored": [{**d.to_dict(), "ignored_reason": r} for d, r in self.selection.ignored],
            },
        }


def select_target(detections: list[Detection], world=None,
                  frame_center: tuple[int, int] | None = None) -> Selection:
    """Which weakened sector a deterministic strategy would engage — computed,
    never clicked.

    Filter to the world's allowed percentages, then pick the **lowest allowed
    weakening** (cheapest fight), breaking ties by **highest confidence** and
    then **nearest to the frame centre**. Unclassified badges and disabled
    percentages are recorded in `ignored` with a reason so the debugger can show
    exactly what was skipped and why.
    """
    if not detections:
        return Selection(None, ["no weakening badges detected"])

    alias = getattr(world, "alias", "?") if world is not None else None
    allowed = set(getattr(world, "allowed_pcts", ())) if world is not None else None

    considered: list[Detection] = []
    ignored: list[tuple[Detection, str]] = []
    for d in detections:
        if d.pct is None:
            ignored.append((d, "percentage unknown"))
        elif allowed is not None and d.pct not in allowed:
            ignored.append((d, "disabled in settings"))
        else:
            considered.append(d)

    if not considered:
        if all(d.pct is None for d in detections):
            reasons = ["percentages not available (classifier could not read them)",
                       "detections shown for verification only"]
        else:
            reasons = [f"no detected badge percentage is enabled for World "
                       f"'{alias}' (allowed {sorted(allowed or ())})"]
        return Selection(None, reasons, considered=[], ignored=ignored)

    cx0, cy0 = frame_center or (960, 540)

    def key(d: Detection):
        dist = ((d.cx - cx0) ** 2 + (d.cy - cy0) ** 2) ** 0.5
        return (d.pct, -d.confidence, dist)  # lowest %, then highest conf, then nearest

    best = min(considered, key=key)
    reasons = ["Lowest allowed weakening with highest confidence."]
    if allowed is None:
        reasons = ["No world settings — lowest weakening with highest confidence."]
    return Selection(best, reasons, considered=considered, ignored=ignored)


def build_scan(image, *, world=None, detector: BadgeDetector | None = None,
               classifier: PercentClassifier | None = None,
               weakening_region: Rect | None = None) -> DebugScan:
    """Run the safety gate (weakening) + detection (+ optional classification) +
    strategy over one image. If the weakening gate is not CONTINUE, no badge
    target is selected — the gate is checked before badges are considered."""
    import cv2

    img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image
    detector = detector or BadgeDetector()
    detections = detector.detect(img)
    panel = detector.detect_panel(img)

    if classifier is not None and len(classifier) and img is not None:
        classified = []
        for d in detections:
            guess, _sim = classifier.predict(percent_patch(img, d.cx, d.cy))
            classified.append(d.with_pct(guess))
        detections = classified
        if panel is not None:
            pguess, _ = classifier.predict(percent_patch(img, panel.cx, panel.cy))
            panel = panel.with_pct(pguess)

    # Weakening safety gate.
    weak_read = None
    decision = Decision.UNKNOWN
    world_limit = getattr(world, "max_weakening", None) if world is not None else None
    if weakening_region is not None and img is not None:
        weak_read = read_ocr(img, weakening_region)
        decision = decide(weak_read, world)

    h, w = (img.shape[0], img.shape[1]) if img is not None else (0, 0)

    # Always run the strategy so the debugger can show the full analysis and the
    # best candidate. Whether that candidate is ACTIONABLE is governed by the
    # weakening gate (decision) — the explanation/annotation make that explicit,
    # and nothing is ever clicked.
    selection = select_target(detections, world, frame_center=(w // 2, h // 2))
    return DebugScan(
        detections=detections,
        panel=panel,
        region=DEFAULT_REGION,
        selection=selection,
        world_alias=getattr(world, "alias", None),
        width=w, height=h,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        weakening=weak_read,
        weakening_region=weakening_region,
        world_limit=world_limit,
        decision=decision,
    )


def annotate(image, scan: DebugScan):
    """Return a BGR copy of `image` with the region, detections, panel pill,
    proposed click cross, and OBSERVE-ONLY banner drawn on it."""
    import cv2

    vis = image.copy()
    x0, y0, x1, y1 = scan.region
    cv2.rectangle(vis, (x0, y0), (x1, y1), (90, 90, 90), 1)

    selected = scan.selection.detection
    ignored_ids = {id(d) for d, _ in scan.selection.ignored}
    for d in scan.detections:
        if selected is not None and d is selected:
            color = (60, 90, 240)      # selected target — red
        elif id(d) in ignored_ids:
            color = (140, 140, 140)    # ignored — grey
        else:
            color = (60, 200, 90)      # considered — green
        cv2.rectangle(vis, (d.x, d.y), (d.x + d.w, d.y + d.h), color, 2)
        label = f"{d.pct}%" if d.pct is not None else "?"
        cv2.putText(vis, f"{label} {d.confidence:.2f}", (d.x, d.y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    if scan.panel is not None:
        p = scan.panel
        cv2.rectangle(vis, (p.x, p.y), (p.x + p.w, p.y + p.h), (235, 170, 40), 2)
        cv2.putText(vis, "panel", (p.x, p.y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (235, 170, 40), 2, cv2.LINE_AA)

    # Weakening region + decision.
    wr = scan.weakening_region
    if wr is not None:
        cv2.rectangle(vis, (wr.x, wr.y), (wr.x + wr.w, wr.y + wr.h), (40, 220, 235), 2)
        val = scan.weakening.value if (scan.weakening and scan.weakening.value is not None) else "?"
        cv2.putText(vis, f"weak={val} {scan.decision.value}", (wr.x, wr.y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 220, 235), 2, cv2.LINE_AA)

    click = scan.selection.click_point
    if click is not None:
        cx, cy = click
        actionable = scan.weakening is None or scan.decision is Decision.CONTINUE
        color = (0, 0, 255) if actionable else (0, 190, 235)  # red vs amber (gated)
        label = (f"Would click x={cx} y={cy}" if actionable
                 else f"candidate x={cx} y={cy} (gate {scan.decision.value})")
        cv2.drawMarker(vis, (cx, cy), color, cv2.MARKER_CROSS, 44, 3)
        cv2.circle(vis, (cx, cy), 24, color, 2)
        cv2.putText(vis, label, (cx + 26, cy + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    cv2.rectangle(vis, (0, 0), (vis.shape[1], 40), (0, 0, 160), -1)
    cv2.putText(vis, OBSERVE_ONLY_BANNER, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (255, 255, 255), 2, cv2.LINE_AA)
    return vis


def save_scan(image, scan: DebugScan, out_dir: Path | str, *, stem: str = "scan") -> dict:
    """Save the original screenshot, annotated screenshot, detection JSON, and
    calibration metadata. Returns the written paths."""
    import cv2

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image
    paths = {
        "original": out / f"{stem}_original.png",
        "annotated": out / f"{stem}_annotated.png",
        "detections": out / f"{stem}_detections.json",
        "calibration": out / f"{stem}_calibration.json",
    }
    cv2.imwrite(str(paths["original"]), img)
    cv2.imwrite(str(paths["annotated"]), annotate(img, scan))
    paths["detections"].write_text(json.dumps(scan.to_dict(), indent=2), encoding="utf-8")
    paths["calibration"].write_text(json.dumps({
        "analyzed_region": list(scan.region),
        "panel_pill_center": list(PANEL_PILL_CENTER),
        "size": [scan.width, scan.height],
        "created_at": scan.created_at,
        "observe_only": True,
    }, indent=2), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


__all__ = [
    "OBSERVE_ONLY_BANNER", "DebugScan", "Selection",
    "build_scan", "annotate", "save_scan", "select_target",
]
