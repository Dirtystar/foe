"""Self-diagnosing Vision Validation (Milestone 4.11) — observe-only.

Runs the **existing** observe-only pipeline once against a single capture and
grades every stage into a structured health report so a human tester can press
one button ("Validate Vision") and immediately know whether the whole Vision
stack is healthy.

This module adds **no** behaviour: it calls the same `build_scan` stage functions
(through the M4.9 timing harness `perf.pipeline.run_tick`) and the same weakening
reader/gate, then inspects the results. It never clicks, moves the cursor, types,
retrains, or changes any threshold. Every check carries a PASS / WARNING / FAIL /
INFO status, a short human explanation, and — when not PASS — a probable reason
and a recommended operator action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from bap.forge.detection.scan import MIN_PCT_SIM
from bap.forge.detection.weakening import DEFAULT_MIN_CONFIDENCE, Decision

_BADGE_CLASSES = (20, 40, 60, 80, 100)
_SIM_BUCKETS = ((0.0, 0.5), (0.5, 0.70), (0.70, 0.85), (0.85, 1.01))


class Status(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    INFO = "INFO"


_ORDER = {Status.INFO: 0, Status.PASS: 1, Status.WARNING: 2, Status.FAIL: 3}


def _worst(statuses) -> Status:
    """The most severe status (FAIL > WARNING > PASS > INFO). Empty → INFO."""
    best = Status.INFO
    for s in statuses:
        if _ORDER[s] > _ORDER[best]:
            best = s
    return best


@dataclass
class Check:
    name: str
    status: Status
    value: str = ""
    explanation: str = ""
    reason: str | None = None       # probable cause, when not PASS
    action: str | None = None       # recommended operator action, when not PASS

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status.value, "value": self.value,
                "explanation": self.explanation, "reason": self.reason, "action": self.action}


@dataclass
class Section:
    title: str
    blurb: str
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> Status:
        # A section of only-INFO checks is INFO; otherwise the worst non-INFO.
        non_info = [c.status for c in self.checks if c.status is not Status.INFO]
        return _worst(non_info) if non_info else Status.INFO

    def to_dict(self) -> dict:
        return {"title": self.title, "blurb": self.blurb, "status": self.status.value,
                "checks": [c.to_dict() for c in self.checks]}


@dataclass
class ValidationReport:
    world_alias: str | None
    created_at: str
    sections: list[Section]
    capture_ok: bool
    live: bool = False

    @property
    def overall(self) -> Status:
        return _worst([s.status for s in self.sections])

    def counts(self) -> dict:
        out = {s.value: 0 for s in Status}
        for section in self.sections:
            for c in section.checks:
                out[c.status.value] += 1
        return out

    def to_dict(self) -> dict:
        return {
            "world": self.world_alias,
            "created_at": self.created_at,
            "live": self.live,
            "capture_ok": self.capture_ok,
            "overall": self.overall.value,
            "counts": self.counts(),
            "sections": [s.to_dict() for s in self.sections],
        }

    def to_markdown(self) -> str:
        icon = {"PASS": "✅", "WARNING": "⚠️", "FAIL": "❌", "INFO": "ℹ️"}
        lines: list[str] = []
        lines.append(f"# Vision Validation — {self.overall.value}")
        lines.append("")
        lines.append(f"- World: **{self.world_alias or '(none)'}**  ·  "
                     f"source: {'LIVE capture' if self.live else 'offline frame'}  ·  "
                     f"`{self.created_at}`")
        c = self.counts()
        lines.append(f"- Checks: ✅ {c['PASS']} PASS · ⚠️ {c['WARNING']} WARNING · "
                     f"❌ {c['FAIL']} FAIL · ℹ️ {c['INFO']} INFO")
        lines.append("")
        for section in self.sections:
            lines.append(f"## {icon[section.status.value]} {section.title} — {section.status.value}")
            lines.append("")
            lines.append(f"_{section.blurb}_")
            lines.append("")
            lines.append("| check | status | value | note |")
            lines.append("|---|---|---|---|")
            for chk in section.checks:
                note = chk.explanation
                lines.append(f"| {chk.name} | {icon[chk.status.value]} {chk.status.value} | "
                             f"{chk.value} | {note} |")
            fixes = [chk for chk in section.checks if chk.reason or chk.action]
            if fixes:
                lines.append("")
                for chk in fixes:
                    bits = []
                    if chk.reason:
                        bits.append(f"probable reason: {chk.reason}")
                    if chk.action:
                        bits.append(f"**action: {chk.action}**")
                    lines.append(f"- _{chk.name}_ — " + " · ".join(bits))
            lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Section builders — each inspects the scan/timer/system and returns a Section.
# --------------------------------------------------------------------------

def _capture_section(image, geometry, capture_latency_s, live) -> Section:
    checks: list[Check] = []
    ok = image is not None
    checks.append(Check(
        "capture successful", Status.PASS if ok else Status.FAIL,
        "yes" if ok else "no",
        "A single raw capture is the input to every downstream stage.",
        None if ok else "the capture returned no image (tab missing/closed, or no image supplied)",
        None if ok else "Open the browser and Scan && Reattach, then re-run Validate Vision.",
    ))
    if not ok:
        return Section("Capture", "The one raw capture the whole pipeline analyses.", checks)
    checks.append(Check("resolution", Status.INFO, f"{geometry.raw_w}×{geometry.raw_h}",
                        "Pixel size of the captured content viewport."))
    vp = (f"{geometry.viewport_w}×{geometry.viewport_h}"
          if geometry.viewport_w and geometry.viewport_h else "(not reported)")
    checks.append(Check("viewport", Status.INFO, vp,
                        "Browser CSS viewport; only reported by a live CDP capture."))
    checks.append(Check("DPR", Status.INFO,
                        f"{geometry.device_pixel_ratio:g}" if geometry.device_pixel_ratio else "(not reported)",
                        "Device-pixel-ratio; affects calibration keying."))
    checks.append(Check("zoom", Status.INFO,
                        f"{geometry.zoom:g}" if geometry.zoom else "(not reported)",
                        "Page zoom; a zoom change invalidates a calibrated ROI."))
    if capture_latency_s is None:
        checks.append(Check("capture latency", Status.INFO, "(offline)",
                            "Time to obtain the capture; measured only for live captures."))
    else:
        ms = capture_latency_s * 1000.0
        st = Status.PASS if ms < 800 else Status.WARNING
        checks.append(Check("capture latency", st, f"{ms:.0f} ms",
                            "Round-trip to obtain the read-only screenshot.",
                            None if st is Status.PASS else "capture is slow (busy tab / large surface)",
                            None if st is Status.PASS else "Retry; if persistent, reduce other tab load."))
    return Section("Capture", "The one raw capture the whole pipeline analyses.", checks)


def _weakening_section(scan, tracker, world_id, min_conf) -> Section:
    checks: list[Check] = []
    rois = scan.rois
    weak_present = rois is not None and rois.weakening is not None
    checks.append(Check(
        "ROI present", Status.PASS if weak_present else Status.FAIL,
        "yes" if weak_present else "no",
        "The weakening ROI is the safety gate's only input.",
        None if weak_present else "no weakening region is defined for this capture geometry",
        None if weak_present else "Run Set Weakening Region on the current top bar.",
    ))
    calibrated = bool(rois and rois.weakening_calibrated)
    checks.append(Check(
        "ROI calibrated", Status.PASS if calibrated else Status.WARNING,
        "yes" if calibrated else "no (default/uncalibrated)",
        "A calibrated ROI is keyed to this exact capture geometry.",
        None if calibrated else "the ROI is a default guess, not calibrated for this resolution",
        None if calibrated else "Run Set Weakening Region so the gate reads the real number.",
    ))
    read = scan.weakening
    val = read.value if read is not None else None
    conf = read.confidence if read is not None else 0.0
    if val is None:
        checks.append(Check("OCR confidence", Status.WARNING, f"{conf:.2f}",
                            "The reader could not confidently read a number.",
                            "unreadable region (uncalibrated ROI, glare, or no number visible)",
                            "Run Set Weakening Region; confirm the number is visible in the top bar."))
        checks.append(Check("human-readable value", Status.INFO, "UNKNOWN",
                            "No confident value → treated as UNKNOWN (fail-safe)."))
    else:
        st = Status.PASS if conf >= min_conf else Status.WARNING
        checks.append(Check("OCR confidence", st, f"{conf:.2f}",
                            f"Confidence vs the gate's minimum {min_conf:.2f}.",
                            None if st is Status.PASS else "read below the confidence bar",
                            None if st is Status.PASS else "Re-capture; recalibrate the ROI if it persists."))
        checks.append(Check("human-readable value", Status.INFO, str(val),
                            "The number the reader extracted (operator should confirm it matches the screen)."))
    # History consistency (per-World; only meaningful with a tracker).
    if tracker is not None and world_id is not None and read is not None:
        status_obj = tracker.observe(world_id, read)
        if status_obj.suspicious:
            checks.append(Check("history consistency", Status.WARNING, "suspicious drop",
                                "This read is a large, unexplained change from the confirmed value.",
                                "likely a misread (glare/animation) — not confirmed into history",
                                "Take several consecutive reads; the gate ignores lone suspicious drops."))
        else:
            checks.append(Check("history consistency", Status.PASS,
                                f"confirmed={status_obj.confirmed}",
                                "Per-World consensus history; Worlds never share a history."))
    else:
        checks.append(Check("history consistency", Status.INFO, "single frame",
                            "No prior reads for this World in this run — nothing to compare yet."))
    dec = scan.decision
    dstatus = {Decision.CONTINUE: Status.PASS, Decision.STOP: Status.INFO,
               Decision.UNKNOWN: Status.WARNING}.get(dec, Status.INFO)
    checks.append(Check("gate result", dstatus, dec.value,
                        "UNKNOWN → no action; ≥ limit → STOP; confident below-limit → CONTINUE.",
                        "weakening unreadable → fail-safe UNKNOWN" if dec is Decision.UNKNOWN else None,
                        "Calibrate the ROI so the gate can read." if dec is Decision.UNKNOWN else None))
    return Section("Weakening", "The per-World safety gate that decides whether any target is actionable.", checks)


def _battle_map_section(scan, geometry) -> Section:
    checks: list[Check] = []
    bm = scan.battle_map_roi
    w, h = geometry.raw_w, geometry.raw_h
    checks.append(Check("battle ROI", Status.INFO, f"({bm.x},{bm.y},{bm.w},{bm.h})",
                        "The analysed map region, in full-capture pixels."))
    checks.append(Check("size", Status.INFO, f"{bm.w}×{bm.h}", "Width × height of the map ROI."))
    area_frac = (bm.w * bm.h) / float(max(1, w * h))
    cov_ok = bm.w >= w * 0.5 and area_frac >= 0.3
    checks.append(Check("coverage", Status.PASS if cov_ok else Status.WARNING,
                        f"{area_frac*100:.0f}% of frame",
                        "The ROI should cover the usable map, not a sub-rectangle.",
                        None if cov_ok else "map ROI is small — likely a mis-calibrated battle-map region",
                        None if cov_ok else "Recalibrate the battle-map region (or clear it to use the whole-map default)."))
    # The pipeline clamps crops to the image, so a small edge overrun is benign
    # (a calibration overhang), while a negative origin or a non-intersecting ROI
    # is a real geometry mismatch.
    fully_inside = w > 0 and h > 0 and bm.x >= 0 and bm.y >= 0 and bm.x + bm.w <= w and bm.y + bm.h <= h
    origin_ok = w > 0 and h > 0 and bm.x >= 0 and bm.y >= 0 and bm.x < w and bm.y < h
    overrun = max(0, bm.x + bm.w - w) + max(0, bm.y + bm.h - h)
    if fully_inside:
        checks.append(Check("geometry validity", Status.PASS, "valid",
                            "The ROI lies fully inside the capture."))
    elif origin_ok and overrun <= 8:
        checks.append(Check("geometry validity", Status.WARNING, f"{overrun}px overhang",
                            "The ROI extends a few px past the edge; the pipeline clamps it.",
                            "calibration slightly larger than the capture (harmless — crops are clamped)",
                            "Recalibrate the battle-map region to remove the overhang."))
    else:
        checks.append(Check("geometry validity", Status.FAIL, "out of bounds",
                            "The ROI origin is off-image or does not intersect the capture.",
                            "ROI does not match this capture geometry",
                            "Recapture; recalibrate for this exact geometry."))
    # Coordinate mapping: every reported coordinate must be full-image, in-bounds.
    pts = [(d.x, d.y, d.w, d.h) for d in scan.detections]
    in_full = all(0 <= x and 0 <= y and x + bw <= w and y + bh <= h for x, y, bw, bh in pts)
    checks.append(Check("coordinate mapping", Status.PASS if in_full else Status.FAIL,
                        "full-image" if in_full else "out of range",
                        "Detector boxes are mapped back to full-capture pixels (ROI offset applied once).",
                        None if in_full else "a detection box fell outside the image — offset applied twice?",
                        None if in_full else "File a regression frame; this is a coordinate-contract bug."))
    return Section("Battle Map", "Where badges are detected — the whole usable battleground.", checks)


def _badge_section(scan, timer) -> Section:
    checks: list[Check] = []
    counts = scan.counts
    cand = counts["stage1_candidates"]
    accepted = counts["final_detections"]
    rejected = counts["rejected"]
    checks.append(Check("candidate count", Status.INFO, str(cand),
                        "Stage-1 colour-prior candidates before template confirmation."))
    if accepted == 0 and cand == 0:
        checks.append(Check("accepted count", Status.WARNING, "0",
                            "No badges detected in this frame.",
                            "no battle badges currently visible (or none on screen)",
                            "Capture during an active battle with visible weakened sectors."))
    else:
        checks.append(Check("accepted count", Status.INFO, str(accepted),
                            "Candidates confirmed as badges after template + NMS."))
    checks.append(Check("rejected count", Status.INFO, str(rejected),
                        "Candidates dropped (below template threshold or NMS-suppressed)."))
    panel = scan.panel_result
    present = bool(panel and panel.get("present"))
    checks.append(Check("false panel detection", Status.PASS if not present else Status.INFO,
                        "none" if not present else "panel corroborated open",
                        "Guards against drawing a province-panel overlay on the map.",
                        None, None))
    det_ms = timer.stages.get("detection", 0.0) * 1000.0
    checks.append(Check("per-stage timing (detection)", Status.INFO, f"{det_ms:.0f} ms",
                        "Detection dominates the tick; measurement only."))
    return Section("Badge Detection", "Locating weakened-sector badges on the map.", checks)


def _classification_section(scan) -> Section:
    checks: list[Check] = []
    by_class = {c: 0 for c in _BADGE_CLASSES}
    unknown = 0
    for d in scan.detections:
        if d.pct in by_class:
            by_class[d.pct] += 1
        else:
            unknown += 1
    for cls in _BADGE_CLASSES:
        note = "No labelled exemplars exist for this class yet." if cls in (80,) else \
               "Classified badges at this percentage."
        checks.append(Check(f"{cls}%", Status.INFO, str(by_class[cls]), note))
    # UNKNOWN + overall classification health.
    has_det = bool(scan.detections)
    all_unknown = has_det and unknown == len(scan.detections)
    ust = Status.WARNING if all_unknown else Status.INFO
    checks.append(Check("UNKNOWN", ust, str(unknown),
                        "Badges whose percentage stayed UNKNOWN (fail-safe, never guessed).",
                        "no exemplar cleared the similarity bar" if all_unknown else None,
                        "Collect more reviewed live frames covering these classes." if all_unknown else None))
    # Confidence histogram + nearest similarities from the classify trace.
    sims = [d.get("similarity") for d in scan.classify_diag if d.get("similarity") is not None]
    hist = {f"{lo:.2f}-{hi:.2f}": sum(1 for s in sims if lo <= s < hi) for lo, hi in _SIM_BUCKETS}
    hist_str = " ".join(f"[{k}]{v}" for k, v in hist.items()) or "(no candidates)"
    checks.append(Check("confidence histogram", Status.INFO, hist_str,
                        f"Nearest-exemplar similarity buckets; accept bar = {MIN_PCT_SIM:.2f}."))
    nearest = sorted((round(s, 3) for s in sims), reverse=True)[:6]
    checks.append(Check("nearest exemplar similarities", Status.INFO,
                        ", ".join(f"{s:.2f}" for s in nearest) or "(none)",
                        "Top nearest-exemplar cosine similarities across candidates."))
    return Section("Classification", "Reading each badge's percentage — accepted only above the similarity bar.", checks)


def _decision_section(scan) -> Section:
    checks: list[Check] = []
    dec = scan.decision
    checks.append(Check("decision", Status.INFO, dec.value,
                        "The per-World gate outcome for this frame."))
    sel = scan.selection.detection
    if sel is not None:
        val = f"{sel.pct}%" if sel.pct is not None else "?"
        checks.append(Check("selected badge", Status.INFO, f"{val} @ ({sel.cx},{sel.cy})",
                            "The badge a deterministic strategy would engage (lowest allowed %, then confidence, then nearest)."))
    else:
        checks.append(Check("selected badge", Status.INFO, "none",
                            "No eligible badge — nothing would be selected."))
    ignored = scan.selection.ignored
    checks.append(Check("ignored badges", Status.INFO, str(len(ignored)),
                        "Badges skipped (unknown % or disabled for this World), with recorded reasons."))
    reasons = " ".join(scan.selection.reasons) or "(none)"
    checks.append(Check("decision explanation", Status.INFO, reasons[:120],
                        "Human-readable reason for the selection."))
    click = scan.selection.click_point
    actionable = scan.weakening is None or dec is Decision.CONTINUE
    if click is None:
        checks.append(Check("would-click point", Status.INFO, "none", "No target → no would-click point."))
    else:
        checks.append(Check("would-click point", Status.INFO, f"({click[0]},{click[1]})",
                            "The point a strategy WOULD click — computed, drawn, never performed (observe-only)."))
    gate_txt = "actionable (CONTINUE)" if (click and actionable) else \
               ("blocked by gate" if click else "no target")
    checks.append(Check("gate status", Status.INFO, gate_txt,
                        "Whether the would-click is gate-actionable. Nothing is ever clicked."))
    return Section("Decision", "The deterministic, observe-only target choice and its safety gating.", checks)


def _performance_section(timer, system) -> Section:
    checks: list[Check] = []
    def ms(name):
        return timer.stages.get(name, 0.0) * 1000.0
    checks.append(Check("capture", Status.INFO, f"{ms('capture'):.0f} ms", "Frame decode / obtain."))
    checks.append(Check("detector", Status.INFO, f"{ms('detection'):.0f} ms", "Badge localization (dominant cost)."))
    checks.append(Check("classifier", Status.INFO, f"{ms('classification'):.0f} ms", "Percentage classification + panel check."))
    checks.append(Check("OCR", Status.INFO, f"{ms('weakening_ocr'):.0f} ms", "Weakening reader."))
    checks.append(Check("decision", Status.INFO, f"{ms('decision'):.0f} ms", "Gate + target selection."))
    checks.append(Check("total", Status.INFO, f"{timer.resolved_total()*1000.0:.0f} ms", "Whole validation tick."))
    if system is not None:
        cpu = system.get("cpu_percent")
        ram = system.get("rss_mb")
        checks.append(Check("CPU", Status.INFO, f"{cpu:.0f}%" if cpu is not None else "(n/a)",
                            "Process CPU over the validation window."))
        checks.append(Check("RAM", Status.INFO, f"{ram:.0f} MB" if ram is not None else "(n/a)",
                            "Process resident memory."))
    return Section("Performance", "Per-stage timing of this validation (measurement only — no optimisation).", checks)


def validate_vision(
    image,
    *,
    world=None,
    world_alias: str | None = None,
    detector=None,
    classifier=None,
    rois=None,
    calibration=None,
    geometry=None,
    capture_latency_s: float | None = None,
    live: bool = False,
    weakening_tracker=None,
    min_ocr_confidence: float = DEFAULT_MIN_CONFIDENCE,
    sample_system: bool = True,
) -> ValidationReport:
    """Run the full observe-only pipeline once against `image` and grade every
    stage. Returns a structured `ValidationReport`. No behaviour is changed —
    this only observes and reports."""
    from bap.forge.detection.detector import BadgeDetector
    from bap.forge.detection.geometry import CaptureGeometry, derive_rois
    from bap.perf.pipeline import run_tick

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    alias = world_alias or getattr(world, "alias", None)

    if image is None:
        cap = _capture_section(None, None, capture_latency_s, live)
        return ValidationReport(alias, created, [cap], capture_ok=False, live=live)

    detector = detector or BadgeDetector()
    geometry = geometry or CaptureGeometry.from_image(image)
    if rois is None:
        rois = derive_rois(geometry, calibration)

    system0 = None
    sampler = None
    if sample_system:
        try:
            from bap.perf.system import SystemSampler

            sampler = SystemSampler()
        except Exception:
            sampler = None

    scan, timer = run_tick(image, world=world, detector=detector, classifier=classifier,
                           rois=rois, geometry=geometry)

    system = None
    if sampler is not None:
        try:
            snap = sampler.sample()
            system = {"cpu_percent": snap.cpu_percent, "rss_mb": snap.rss_mb}
        except Exception:
            system = None

    world_id = alias
    sections = [
        _capture_section(image, geometry, capture_latency_s, live),
        _weakening_section(scan, weakening_tracker, world_id, min_ocr_confidence),
        _battle_map_section(scan, geometry),
        _badge_section(scan, timer),
        _classification_section(scan),
        _decision_section(scan),
        _performance_section(timer, system),
    ]
    return ValidationReport(alias, created, sections, capture_ok=True, live=live)


__all__ = ["Status", "Check", "Section", "ValidationReport", "validate_vision"]
