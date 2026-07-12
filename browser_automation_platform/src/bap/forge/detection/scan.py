"""Observe-only Vision Debugger core.

Turns ONE unmodified full raw capture into a `DebugScan`. The capture contains
the whole Forge top bar (current weakening) AND the whole visible battleground
map at once. Two ROIs — both in full-capture pixels — are derived from it:

  * ``weakening_roi``  → the safety gate (current weakening).
  * ``battle_map_roi`` → the whole usable map, where badges are detected.

The scan reports, for every badge candidate, its ROI-local box, its full-image
box and centre, and the click point a strategy *would* choose — all in
full-capture coordinates, with the ROI offset applied exactly once. It renders an
annotated copy (ROIs, badges, weakening, would-click) under a permanent OBSERVE
ONLY banner and can save the full artifact set. It never clicks — the proposed
click point is drawn, never performed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bap.core.domain.models import Rect
from bap.forge.detection.classify import PercentClassifier, percent_patch
from bap.forge.detection.detector import (
    PANEL_PILL_CENTER,
    BadgeDetector,
    Detection,
)
from bap.forge.detection.geometry import (
    CaptureGeometry,
    ScanRois,
    default_battle_map,
)
from bap.forge.detection.weakening import Decision, WeakeningRead, decide, read_ocr

OBSERVE_ONLY_BANNER = "OBSERVE ONLY — NO CLICK PERFORMED"

# A percentage guess is only accepted when the nearest-exemplar cosine similarity
# clears this bar; below it the badge stays UNKNOWN with a recorded reason rather
# than being silently treated as a valid percentage.
MIN_PCT_SIM = 0.55
# The province-detail panel is reported open only when the fixed pill spot both
# scores as an emblem AND classifies as a confident percentage — a bare emblem
# score at a fixed point is not evidence the panel is open (it false-positived on
# empty terrain in the Windows review).
PANEL_SCORE_MIN = 0.55


def _rect_to_box(rect: Rect) -> tuple[int, int, int, int]:
    return (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h)


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
    # Capture geometry + the two analysis ROIs (full-capture pixels).
    geometry: CaptureGeometry | None = None
    rois: ScanRois | None = None
    # Per-candidate classification trace and the panel-open result.
    classify_diag: list[dict] = field(default_factory=list)
    panel_result: dict | None = None
    stage1_candidates: list[dict] = field(default_factory=list)

    @property
    def battle_map_roi(self) -> Rect:
        if self.rois is not None:
            return self.rois.battle_map
        x0, y0, x1, y1 = self.region
        return Rect(x=x0, y=y0, w=x1 - x0, h=y1 - y0)

    @property
    def counts(self) -> dict:
        """The detector pipeline stage counts, for the debugger summary."""
        stage1 = len(self.stage1_candidates)
        confirmed = sum(1 for c in self.stage1_candidates if c.get("confirmed"))
        accepted = len(self.detections)
        classified = sum(1 for d in self.detections if d.pct is not None)
        return {
            "stage1_candidates": stage1,
            "template_confirmed": confirmed,
            "rejected": stage1 - accepted,
            "final_detections": accepted,
            "percentage_classified": classified,
            "percentage_unknown": accepted - classified,
        }

    def explanation(self) -> str:
        """The full per-World decision, in the order the pipeline runs it."""
        lines = [OBSERVE_ONLY_BANNER, ""]
        lines.append(f"World: {self.world_alias or '(none)'}")

        # Capture + ROI context — the analyzed area is explicit, not implied.
        bm = self.battle_map_roi
        wr = self.weakening_region
        bm_cal = self.rois.battle_map_calibrated if self.rois else False
        wr_cal = self.rois.weakening_calibrated if self.rois else (wr is not None)
        lines.append(f"Map ROI: x={bm.x} y={bm.y} w={bm.w} h={bm.h}"
                     f"{'' if bm_cal else '  (default — whole map below top bar; not calibrated)'}")
        if wr is not None:
            lines.append(f"Weakening ROI: x={wr.x} y={wr.y} w={wr.w} h={wr.h}"
                         f"{'' if wr_cal else '  (uncalibrated)'}")
        else:
            lines.append("Weakening ROI: (not calibrated — set it before the gate can read)")

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

        # Detector pipeline stage counts — where every candidate went.
        c = self.counts
        lines.append(
            f"Pipeline: stage-1 {c['stage1_candidates']} · template-confirmed "
            f"{c['template_confirmed']} · rejected {c['rejected']} · accepted "
            f"{c['final_detections']} (classified {c['percentage_classified']}, "
            f"unknown {c['percentage_unknown']})")

        # 3-4. Detected + ignored badges.
        detected = "  ".join(f"{d.pct}%" if d.pct is not None else "?" for d in self.detections) or "none"
        lines.append(f"Detected: {detected}")
        if self.selection.ignored:
            for d, reason in self.selection.ignored:
                pct = f"{d.pct}%" if d.pct is not None else "?"
                lines.append(f"Ignored: {pct} ({reason})")
        else:
            lines.append("Ignored: none")

        # Province-panel state is diagnostic only — kept in scan.json, not shown
        # in the main debugger text (unused by the current decision slice).

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

    def _detection_dict(self, d: Detection) -> dict:
        """Detection serialized in the coordinate contract: full-image box/centre
        plus the ROI-local box (offset removed exactly once)."""
        bm = self.battle_map_roi
        base = d.to_dict()
        base["center_full"] = [d.cx, d.cy]
        base["bbox_full"] = [d.x, d.y, d.w, d.h]
        base["bbox_roi"] = [d.x - bm.x, d.y - bm.y, d.w, d.h]
        return base

    def to_dict(self) -> dict:
        wr = self.weakening_region
        click = self.selection.click_point
        return {
            "observe_only": True,
            "created_at": self.created_at,
            "world": self.world_alias,
            "size": [self.width, self.height],
            "geometry": self.geometry.to_dict() if self.geometry else None,
            "rois": self.rois.to_dict() if self.rois else {
                "battle_map_roi": list(self.region), "weakening_roi":
                    [wr.x, wr.y, wr.w, wr.h] if wr else None,
            },
            "analyzed_region": _rect_to_box(self.battle_map_roi),
            "weakening": {
                "read": self.weakening.to_dict() if self.weakening else None,
                "region": [wr.x, wr.y, wr.w, wr.h] if wr else None,
                "world_limit": self.world_limit,
                "decision": self.decision.value,
            },
            "counts": self.counts,
            "stage1_candidates": self.stage1_candidates,
            "detections": [self._detection_dict(d) for d in self.detections],
            "classifier_min_similarity": MIN_PCT_SIM,
            "classification": self.classify_diag,
            "panel": self.panel_result,
            "selection": {
                "click_point_full": list(click) if click else None,
                "click_point": list(click) if click else None,
                "detection": self._detection_dict(self.selection.detection)
                    if self.selection.detection else None,
                "reasons": self.selection.reasons,
                "considered": [self._detection_dict(d) for d in self.selection.considered],
                "ignored": [{**self._detection_dict(d), "ignored_reason": r}
                            for d, r in self.selection.ignored],
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


def _classify(img, detections, classifier) -> tuple[list[Detection], list[dict]]:
    """Classify each detection's percentage, accepting a guess only when its
    similarity clears MIN_PCT_SIM. Returns the pct-annotated detections and a
    per-candidate diagnostic trace: crop centre, prediction, similarity, the top-5
    nearest labelled exemplars, whether accepted, and the rejection reason when
    unknown."""
    topk = getattr(classifier, "predict_topk", None)
    out, diag = [], []
    for d in detections:
        patch = percent_patch(img, d.cx, d.cy)
        if patch is None:
            out.append(d.with_pct(None))
            diag.append({"cx": d.cx, "cy": d.cy, "predicted": None, "similarity": None,
                         "top5": [], "accepted": False,
                         "reason": "classifier crop fell outside the image / uniform (crop invalid)"})
            continue
        guess, sim = classifier.predict(patch)
        nearest = [[p, round(float(s), 4)] for p, s in topk(patch, 5)] if topk else []
        accepted = guess is not None and sim >= MIN_PCT_SIM
        if accepted:
            reason = f"nearest exemplar {guess}% at similarity {sim:.2f} >= {MIN_PCT_SIM:.2f}"
        elif guess is None:
            reason = "classifier returned no match"
        else:
            reason = (f"best match {guess}% but similarity {sim:.2f} < {MIN_PCT_SIM:.2f} "
                      "— left UNKNOWN (not treated as valid)")
        out.append(d.with_pct(guess if accepted else None))
        diag.append({"cx": d.cx, "cy": d.cy, "predicted": guess,
                     "similarity": round(float(sim), 4), "top5": nearest,
                     "accepted": accepted, "reason": reason})
    return out, diag


def _panel_state(img, detector: BadgeDetector, classifier) -> tuple[dict, Detection | None]:
    """Report the province-detail panel as open only when the fixed pill spot
    both scores as an emblem and classifies as a confident percentage. Otherwise
    ``present=False`` and no box is drawn — the raw score is still recorded for
    diagnosis."""
    px, py = PANEL_PILL_CENTER
    ox, oy = detector._offset
    ax, ay = px - ox, py - oy
    score = detector.score_at(img, ax, ay)
    pct, sim = (None, 0.0)
    if classifier is not None and len(classifier):
        pct, sim = classifier.predict(percent_patch(img, px, py))
    present = score >= PANEL_SCORE_MIN and pct is not None and sim >= MIN_PCT_SIM
    if present:
        reason = f"emblem {score:.2f} + {pct}% at similarity {sim:.2f} — panel corroborated open"
    elif score < PANEL_SCORE_MIN:
        reason = f"emblem score {score:.2f} < {PANEL_SCORE_MIN:.2f} — no panel pill here"
    else:
        reason = (f"emblem {score:.2f} but no confident percentage "
                  "— province-detail panel not corroborated as open")
    result = {"center": [px, py], "score": round(float(score), 4), "pct": pct,
              "pct_similarity": round(float(sim), 4), "present": present, "reason": reason}
    panel = None
    if present:
        panel = Detection(cx=px, cy=py, x=px - 20, y=py - 12, w=40, h=24,
                          confidence=min(1.0, score), pct=pct, kind="panel")
    return result, panel


def build_scan(image, *, world=None, detector: BadgeDetector | None = None,
               classifier: PercentClassifier | None = None,
               weakening_region: Rect | None = None,
               rois: ScanRois | None = None,
               geometry: CaptureGeometry | None = None) -> DebugScan:
    """Run the whole observe-only pipeline over one full raw capture: derive the
    two ROIs, read the weakening gate, detect + classify badges inside the
    battle-map ROI, decide the panel-open state, and compute the strategy's best
    candidate. Actionability is governed by the weakening gate — nothing clicks."""
    import cv2

    img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image
    detector = detector or BadgeDetector()

    geometry = geometry or (CaptureGeometry.from_image(img) if img is not None
                            else CaptureGeometry(0, 0))
    if rois is None:
        battle = default_battle_map(geometry, weakening_region)
        rois = ScanRois(battle_map=battle, weakening=weakening_region,
                        weakening_calibrated=weakening_region is not None,
                        battle_map_calibrated=False)
    weak_roi = rois.weakening

    # Detection over the battle-map ROI (whole usable map), with the full trace.
    result = detector.scan(img, region=_rect_to_box(rois.battle_map))
    detections = result.detections

    # Percentage classification with an acceptance threshold + per-candidate trace.
    classify_diag: list[dict] = []
    if classifier is not None and len(classifier) and img is not None:
        detections, classify_diag = _classify(img, detections, classifier)

    # Province-detail panel — corroborated, never a bare fixed-point box.
    panel_result, panel = (None, None)
    if img is not None:
        panel_result, panel = _panel_state(img, detector, classifier)

    # Weakening safety gate.
    weak_read = None
    decision = Decision.UNKNOWN
    world_limit = getattr(world, "max_weakening", None) if world is not None else None
    if weak_roi is not None and img is not None:
        weak_read = read_ocr(img, weak_roi)
        decision = decide(weak_read, world)

    h, w = (img.shape[0], img.shape[1]) if img is not None else (0, 0)

    # Always compute the best candidate over the map ROI centre; the weakening
    # gate governs whether that candidate is ACTIONABLE (explanation/annotation
    # make it explicit) and nothing is ever clicked.
    bm = rois.battle_map
    center = (bm.x + bm.w // 2, bm.y + bm.h // 2)
    selection = select_target(detections, world, frame_center=center)
    return DebugScan(
        detections=detections,
        panel=panel,
        region=_rect_to_box(bm),
        selection=selection,
        world_alias=getattr(world, "alias", None),
        width=w, height=h,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        weakening=weak_read,
        weakening_region=weak_roi,
        world_limit=world_limit,
        decision=decision,
        geometry=geometry,
        rois=rois,
        classify_diag=classify_diag,
        panel_result=panel_result,
        stage1_candidates=result.candidates,
    )


def annotate(image, scan: DebugScan):
    """Return a BGR copy of `image` with BOTH ROIs, the detections, the weakening
    region, and the proposed click cross drawn on it.

    Deliberately draws **no** OBSERVE-ONLY banner over the image: the banner used
    to cover the top ~40 px — exactly where the Forge top bar (current weakening)
    sits — hiding it from view and calibration. Observe-only status lives in the
    window title, the side text panel, and the GUI chrome instead. The input image
    is never modified: analysis runs on the raw capture, drawing on a copy."""
    import cv2

    vis = image.copy()

    # Battle-map ROI (the analyzed map area) + weakening ROI, drawn on output only.
    bm = scan.battle_map_roi
    cv2.rectangle(vis, (bm.x, bm.y), (bm.x + bm.w, bm.y + bm.h), (90, 180, 90), 1)
    cv2.putText(vis, "battle map ROI", (bm.x + 6, bm.y + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (90, 180, 90), 2, cv2.LINE_AA)

    # Rejected stage-1 candidates: thin red markers (not badges — shown for
    # verification). Detected badge centres are drawn as boxes below.
    detected_pts = {(d.cx, d.cy) for d in scan.detections}
    for cand in scan.stage1_candidates:
        if cand.get("kept"):
            continue
        pt = (int(cand["cx"]), int(cand["cy"]))
        if pt in detected_pts:
            continue
        cv2.drawMarker(vis, pt, (0, 0, 210), cv2.MARKER_TILTED_CROSS, 12, 1)

    selected = scan.selection.detection
    for d in scan.detections:
        color = (60, 200, 90) if d.pct is not None else (0, 190, 235)  # accepted green / unknown amber
        cv2.rectangle(vis, (d.x, d.y), (d.x + d.w, d.y + d.h), color, 2)
        label = f"{d.pct}%" if d.pct is not None else "?"
        cv2.putText(vis, f"{label} {d.confidence:.2f}", (d.x, d.y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    # Province panel is diagnostic-only (kept in scan.json); it is not drawn on
    # the map — a fixed-point pill box was noise on the main debugger view.

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
        cyan = (255, 255, 0)  # selected target — cyan cross
        actionable = scan.weakening is None or scan.decision is Decision.CONTINUE
        label = (f"Would click x={cx} y={cy}" if actionable
                 else f"candidate x={cx} y={cy} (gate {scan.decision.value})")
        cv2.drawMarker(vis, (cx, cy), cyan, cv2.MARKER_CROSS, 44, 3)
        cv2.circle(vis, (cx, cy), 24, cyan, 2)
        cv2.putText(vis, label, (cx + 26, cy + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, cyan, 2, cv2.LINE_AA)

    return vis


def _crop(img, rect: Rect):
    """Safe crop of a Rect from a full-capture image, clamped to bounds."""
    if img is None or rect is None:
        return None
    h, w = img.shape[:2]
    x0, y0 = max(0, rect.x), max(0, rect.y)
    x1, y1 = min(w, rect.x + rect.w), min(h, rect.y + rect.h)
    if x1 <= x0 or y1 <= y0:
        return None
    return img[y0:y1, x0:x1].copy()


def _classifier_contact_sheet(img, detections, classifier):
    """A stacked side-by-side: each candidate's normalized live %-crop next to its
    top-5 nearest grading exemplars (with predicted % + similarity), so a live vs
    training scale/offset mismatch is visible at a glance."""
    import cv2
    import numpy as np

    nearest = getattr(classifier, "nearest", None)
    if nearest is None or not detections:
        return None
    cell_w, cell_h, pad = 80, 56, 4
    rows = []
    for i, d in enumerate(detections):
        patch = percent_patch(img, d.cx, d.cy)
        if patch is None:
            continue
        from bap.forge.detection.classify import vec_to_image

        cells = [("live", None, vec_to_image(patch))]
        for pct, sim, ex_img in nearest(patch, 5):
            cells.append((f"{pct}%", sim, ex_img))
        strip = np.full((cell_h, cell_w * len(cells), 3), 30, np.uint8)
        for j, (label, sim, cimg) in enumerate(cells):
            g = cv2.resize(cimg, (cell_w - 2 * pad, cell_h - 20), interpolation=cv2.INTER_NEAREST)
            bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
            x0 = j * cell_w + pad
            strip[16:16 + bgr.shape[0], x0:x0 + bgr.shape[1]] = bgr
            txt = label if sim is None else f"{label} {sim:.2f}"
            cv2.putText(strip, txt, (j * cell_w + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (230, 230, 230), 1, cv2.LINE_AA)
        cv2.putText(strip, f"#{i} ({d.cx},{d.cy})", (2, cell_h - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (140, 200, 255), 1, cv2.LINE_AA)
        rows.append(strip)
    if not rows:
        return None
    width = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, width - r.shape[1]), (0, 0)), constant_values=30) for r in rows]
    return np.vstack(rows)


def save_scan(image, scan: DebugScan, out_dir: Path | str, *, stem: str = "scan",
              classifier=None) -> dict:
    """Save the full Test-Scan artifact set for review: the unmodified full raw
    capture, both weakening crops (raw + processed), the battle-map ROI crop, a
    candidate overlay, per-candidate classifier crops (raw / emblem / percent /
    normalized input), a live-vs-exemplar contact sheet, the final annotated
    output, and scan.json with the whole trace."""
    import cv2
    import numpy as np

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image
    paths: dict[str, Path] = {}

    def write(name: str, arr) -> None:
        p = out / name
        if arr is not None:
            cv2.imwrite(str(p), arr)
            paths[name] = p

    # 01 — the unmodified full raw capture (top bar + full map, no overlays).
    write("01_full_raw_capture.png", img)

    # 02/03 — weakening ROI raw + processed OCR crop.
    write("02_weakening_roi_raw.png", _crop(img, scan.weakening_region))
    if scan.weakening is not None and scan.weakening.processed_crop is not None:
        write("03_weakening_roi_processed.png", scan.weakening.processed_crop)

    # 04 — the battle-map ROI (the whole analyzed map area).
    write("04_battle_map_roi_raw.png", _crop(img, scan.battle_map_roi))

    # 05 — badge candidates only (no decision), for locating verification.
    if img is not None:
        overlay = img.copy()
        bm = scan.battle_map_roi
        cv2.rectangle(overlay, (bm.x, bm.y), (bm.x + bm.w, bm.y + bm.h), (90, 180, 90), 1)
        for c in scan.stage1_candidates:
            col = (60, 200, 90) if c.get("kept") else (120, 120, 120)
            cv2.circle(overlay, (int(c["cx"]), int(c["cy"])), 16, col, 2)
        write("05_badge_candidate_overlay.png", overlay)

    # 06 — per-candidate crops: raw / emblem / percent-only / normalized input.
    crops_dir = out / "06_badge_classifier_crops"
    if img is not None and scan.detections:
        crops_dir.mkdir(parents=True, exist_ok=True)
        for i, d in enumerate(scan.detections):
            for suffix, rect in (
                ("raw", Rect(d.cx - 24, d.cy - 20, 94, 40)),
                ("emblem", Rect(d.cx - 20, d.cy - 20, 40, 40)),
                ("percent", Rect(d.cx + 16, d.cy - 16, 54, 32)),
            ):
                crop = _crop(img, rect)
                if crop is not None:
                    cv2.imwrite(str(crops_dir / f"cand{i:02d}_{suffix}.png"), crop)
            patch = percent_patch(img, d.cx, d.cy)
            if patch is not None:
                vis = patch - patch.min()
                span = float(vis.max()) or 1.0
                cv2.imwrite(str(crops_dir / f"cand{i:02d}_classifier_input.png"),
                            (vis / span * 255).astype(np.uint8))
        paths["06_badge_classifier_crops"] = crops_dir

    # 07 — the final annotated output.
    write("07_final_annotated_output.png", annotate(img, scan) if img is not None else None)

    # 08 — live-vs-exemplar contact sheet (why the % reads UNKNOWN).
    if img is not None and classifier is not None:
        write("08_classifier_contact_sheet.png",
              _classifier_contact_sheet(img, scan.detections, classifier))

    scan_json = out / "scan.json"
    scan_json.write_text(json.dumps(scan.to_dict(), indent=2), encoding="utf-8")
    paths["scan.json"] = scan_json
    return {k: str(v) for k, v in paths.items()}


__all__ = [
    "OBSERVE_ONLY_BANNER", "MIN_PCT_SIM", "PANEL_SCORE_MIN", "DebugScan", "Selection",
    "build_scan", "annotate", "save_scan", "select_target",
]
