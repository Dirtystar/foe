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

from bap.forge.detection.classify import PercentClassifier, percent_patch
from bap.forge.detection.detector import (
    DEFAULT_REGION,
    PANEL_PILL_CENTER,
    BadgeDetector,
    Detection,
)

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

    def explanation(self) -> str:
        lines = [OBSERVE_ONLY_BANNER, ""]
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
        return {
            "observe_only": True,
            "created_at": self.created_at,
            "world": self.world_alias,
            "size": [self.width, self.height],
            "analyzed_region": list(self.region),
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

    allowed = set(getattr(world, "allowed_pcts", ()))
    max_weak = getattr(world, "max_weakening_pct", 100)
    eligible = [d for d in classified if d.pct in allowed and d.pct <= max_weak]
    if not eligible:
        return Selection(None, [
            f"no badge is both enabled for World '{getattr(world, 'alias', '?')}' "
            f"(allowed {sorted(allowed)}) and ≤ max weakening {max_weak}%",
        ])
    best = max(eligible, key=lambda d: d.pct)
    return Selection(best, [
        f"{best.pct}% is enabled for World '{getattr(world, 'alias', '?')}'",
        f"current weakening {best.pct}% ≤ world limit {max_weak}%",
        f"confidence {best.confidence:.2f}",
        "highest allowed weakening among candidates",
    ])


def build_scan(image, *, world=None, detector: BadgeDetector | None = None,
               classifier: PercentClassifier | None = None) -> DebugScan:
    """Run detection (+ optional classification) and strategy over one image."""
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

    h, w = (img.shape[0], img.shape[1]) if img is not None else (0, 0)
    return DebugScan(
        detections=detections,
        panel=panel,
        region=DEFAULT_REGION,
        selection=select_target(detections, world),
        world_alias=getattr(world, "alias", None),
        width=w, height=h,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
