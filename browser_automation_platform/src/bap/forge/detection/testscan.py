"""Forge Test-Scan orchestration — observe-only, Qt-free, testable.

Resolves *which* World a Test Scan runs against and captures *its* live tab,
with no implicit fallback to another World and no offline substitution. The tab
handle is resolved fresh from the assignment at scan time, so a stale first-World
closure or a removed World can never silently redirect the scan.

Two entry points:

  * ``scan_world``        — capture + analyze one explicitly named World.
  * ``scan_all_attached`` — capture + analyze every attached World independently
                            and sequentially, one summary row each. It never
                            compares state across Worlds and never clicks.

The GUI layer renders these results; all decision/rendering logic lives in
``scan`` / ``geometry``. Nothing here moves the mouse or sends keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bap.forge.detection.geometry import CaptureGeometry, derive_rois
from bap.forge.detection.scan import DebugScan, build_scan


@dataclass
class TargetInfo:
    """What a Test Scan would run against — for display before capture."""

    alias: str
    hostname: str | None = None
    attached: bool = False
    tab_id: str | None = None
    tab_title: str | None = None
    tab_url: str | None = None
    error: str | None = None

    def summary(self) -> str:
        if self.error:
            return f"Test Scan target: {self.alias} — {self.error}"
        return (f"Test Scan target:\n  Alias: {self.alias}\n  Hostname: {self.hostname}\n"
                f"  Tab title: {self.tab_title or '(unknown)'}\n  Tab URL: {self.tab_url or '(unknown)'}")


@dataclass
class WorldScanResult:
    """One World's Test-Scan outcome, associated with its own alias/host/tab."""

    alias: str
    hostname: str | None = None
    tab_id: str | None = None
    capture_ok: bool = False
    error: str | None = None
    scan: DebugScan | None = None

    def row(self) -> dict:
        """A summary-table row (one per World) — no cross-World comparison."""
        s = self.scan
        weak = decision = None
        counts = {}
        selected = None
        if s is not None:
            counts = s.counts
            if s.weakening is not None:
                weak = s.weakening.value
            decision = s.decision.value
            if s.selection.detection is not None:
                d = s.selection.detection
                selected = f"{d.pct}% @ ({d.cx},{d.cy})" if d.pct is not None else f"? @ ({d.cx},{d.cy})"
        rejected = _rejected_candidates(s)
        return {
            "alias": self.alias,
            "hostname": self.hostname,
            "tab_id": self.tab_id,
            "capture": "ok" if self.capture_ok else "FAILED",
            "weakening": "unreadable" if (self.capture_ok and weak is None) else weak,
            "decision": decision,
            "stage1_candidates": counts.get("stage1_candidates"),
            "accepted_detections": counts.get("final_detections"),
            "unknown_percentages": counts.get("percentage_unknown"),
            "rejected_candidates": rejected,
            "selected": selected,
            "error": self.error,
        }


def _rejected_candidates(scan: DebugScan | None) -> int | None:
    if scan is None:
        return None
    return sum(1 for c in scan.stage1_candidates if not c.get("kept"))


def resolve_target(alias, *, world_store, assignment, browser_open: bool) -> TargetInfo:
    """Resolve a World's live-scan target from stable identity (alias/hostname)
    and the *current* assignment — never a cached tab handle."""
    if not alias:
        return TargetInfo(alias="(none)", error="no World selected")
    world = world_store.get(alias) if world_store is not None else None
    if world is None:
        return TargetInfo(alias=alias, error="World not found")
    hostname = getattr(world, "hostname", None)
    tab = assignment.get(alias) if assignment is not None else None
    if not browser_open:
        return TargetInfo(alias=alias, hostname=hostname, attached=False,
                          error="browser is not open")
    if tab is None:
        return TargetInfo(alias=alias, hostname=hostname, attached=False,
                          error="World is not attached to a live tab (Scan && Reattach first)")
    return TargetInfo(alias=alias, hostname=hostname, attached=True, tab_id=tab.tab_id,
                      tab_title=getattr(tab, "title", None), tab_url=getattr(tab, "url", None))


def capture_world_image(alias, *, world_store, assignment, browser_open, capture_callback):
    """Capture the selected World's current tab (read-only). Returns
    ``(image_or_None, error_or_None)``. Never falls back to another World or to an
    offline image — a broken live mapping is reported, not papered over."""
    target = resolve_target(alias, world_store=world_store, assignment=assignment,
                            browser_open=browser_open)
    if target.error is not None:
        return None, target.error
    if capture_callback is None:
        return None, "no live capture available (browser not wired)"
    try:
        png = capture_callback(target.tab_id)
    except Exception as exc:  # surfaced, never silently swallowed
        return None, f"live capture failed: {exc}"
    if not png:
        return None, "live capture returned no image (tab missing or closed?)"
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None, "captured bytes could not be decoded as an image"
    return img, None


def scan_world(alias, *, world_store, assignment, browser_open, capture_callback,
               classifier=None, calibration=None) -> WorldScanResult:
    """Capture + analyze one explicitly named World. The result is tagged with
    that World's alias/hostname and the exact tab id used."""
    world = world_store.get(alias) if world_store is not None else None
    hostname = getattr(world, "hostname", None)
    target = resolve_target(alias, world_store=world_store, assignment=assignment,
                            browser_open=browser_open)
    img, err = capture_world_image(alias, world_store=world_store, assignment=assignment,
                                   browser_open=browser_open, capture_callback=capture_callback)
    if img is None:
        return WorldScanResult(alias=alias, hostname=hostname, tab_id=target.tab_id,
                               capture_ok=False, error=err)
    geometry = CaptureGeometry.from_image(img)
    rois = derive_rois(geometry, calibration)
    scan = build_scan(img, world=world, classifier=classifier, rois=rois, geometry=geometry)
    return WorldScanResult(alias=alias, hostname=hostname, tab_id=target.tab_id,
                           capture_ok=True, scan=scan)


def attached_aliases(*, world_store, assignment, browser_open: bool) -> list[str]:
    """Aliases whose World currently has a live tab — the only ones a live Test
    Scan or Scan-All will touch."""
    if world_store is None or assignment is None or not browser_open:
        return []
    return [a for a in world_store.aliases() if assignment.get(a) is not None]


def scan_all_attached(*, world_store, assignment, browser_open, capture_callback,
                      classifier=None, calibration=None) -> list[WorldScanResult]:
    """Scan every attached World independently and sequentially. Each World uses
    its own freshly-resolved tab; no World's result depends on another's."""
    results = []
    for alias in attached_aliases(world_store=world_store, assignment=assignment,
                                  browser_open=browser_open):
        results.append(scan_world(alias, world_store=world_store, assignment=assignment,
                                   browser_open=browser_open, capture_callback=capture_callback,
                                   classifier=classifier, calibration=calibration))
    return results


SCAN_ALL_COLUMNS = [
    ("alias", "Alias"), ("hostname", "Hostname"), ("capture", "Capture"),
    ("weakening", "Weakening"), ("decision", "Decision"),
    ("stage1_candidates", "Stage-1"), ("accepted_detections", "Accepted"),
    ("unknown_percentages", "Unknown %"), ("rejected_candidates", "Rejected"),
    ("selected", "Selected"), ("error", "Error"),
]


__all__ = [
    "TargetInfo", "WorldScanResult", "resolve_target", "capture_world_image",
    "scan_world", "scan_all_attached", "attached_aliases", "SCAN_ALL_COLUMNS",
]
