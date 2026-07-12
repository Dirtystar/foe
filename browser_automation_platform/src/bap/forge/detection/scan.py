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
        lines = [OBSERVE_ONLY_BANNER, ""]
        # Safety gate first — it decides whether badges are even considered.
        if self.weakening is not None:
            val = self.weakening.value if self.weakening.value is not None else "unreadable"
            lines.append(
                f"Current weakening: {val} (conf {self.weakening.confidence:.2f}, "
                f"{self.weakening.method})   limit: {self.world_limit}"
            )
            lines.append(f"Safety decision: {self.decision.value}")
            if self.decision is Decision.STOP:
                lines.append("  → at/over the limit: this World would STOP (no badges considered)")
            elif self.decision is Decision.UNKNOWN:
                lines.append("  → weakening not confidently read: NO ACTION (fail-safe)")
            lines.append("")
        lines.append(f"Badges detected: {len(self.detections)}")
        if self.panel is not None:
            pct = f"{self.panel.pct}%" if self.panel.pct is not None else "unknown %"
            lines.append(f"Side panel: province selected (pill {pct}, conf {self.panel.confidence:.2f})")
        else:
            lines.append("Side panel: no province selected")
        for d in self.detections:
            pct = f"{d.pct}%" if d.pct is not None else "?"
            lines.append(f"  • {pct} at ({d.cx},{d.cy})  conf {d.confidence:.2f}")
        lines.append("")
        if self.selection.detection is not None:
            d = self.selection.detection
            lines.append(f"Strategy would select: {d.pct}% at ({d.cx},{d.cy})")
        else:
            lines.append("Strategy would select: none")
        lines.extend(f"  - {r}" for r in self.selection.reasons)
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
                "click_point": self.selection.click_point,
                "detection": self.selection.detection.to_dict() if self.selection.detection else None,
                "reasons": self.selection.reasons,
            },
        }


def select_target(detections: list[Detection], world=None) -> Selection:
    """Which weakened sector a strategy would engage — computed, never clicked.

    A world's rules: only percentages the world enables, and only at or below its
    max weakening. Among eligible badges, prefer the highest allowed percentage
    (most weakened → easiest fight). Explains itself either way.
    """
    if not detections:
        return Selection(None, ["no weakening badges detected"])

    classified = [d for d in detections if d.pct is not None]
    if not classified:
        return Selection(None, [
            "percentages not available (classifier not trained yet)",
            "detections shown for verification only",
        ])

    if world is None:
        best = max(classified, key=lambda d: d.pct)
        return Selection(best, [
            "no world settings supplied — picked the most-weakened badge",
            f"{best.pct}% at ({best.cx},{best.cy})",
        ])

    # Badge eligibility is purely the world's allowed percentages. The current-
    # weakening safety gate is applied separately (before badges are considered)
    # — it is NOT a filter on badge percentage.
    allowed = set(getattr(world, "allowed_pcts", ()))
    eligible = [d for d in classified if d.pct in allowed]
    if not eligible:
        return Selection(None, [
            f"no detected badge percentage is enabled for World "
            f"'{getattr(world, 'alias', '?')}' (allowed {sorted(allowed)})",
        ])
    best = max(eligible, key=lambda d: d.pct)
    return Selection(best, [
        f"{best.pct}% is enabled for World '{getattr(world, 'alias', '?')}'",
        f"confidence {best.confidence:.2f}",
        "highest allowed badge percentage among candidates",
    ])


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

    # Badges are only selectable when the gate says CONTINUE.
    if decision is Decision.CONTINUE or weakening_region is None:
        selection = select_target(detections, world)
    else:
        why = ("weakening at/over the limit — World would STOP"
               if decision is Decision.STOP else
               "weakening not confidently read — fail-safe, no action")
        selection = Selection(None, [why])

    h, w = (img.shape[0], img.shape[1]) if img is not None else (0, 0)
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

    for d in scan.detections:
        color = (60, 200, 90)
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
        cv2.drawMarker(vis, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
        cv2.circle(vis, (cx, cy), 22, (0, 0, 255), 2)

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
