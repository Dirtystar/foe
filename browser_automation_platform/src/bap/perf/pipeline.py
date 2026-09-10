"""Timed measurement harness over the real observe-only pipeline (Milestone 4.9).

This does NOT reimplement or alter the pipeline. It calls the exact same stage
functions `build_scan` calls, in the same order, wrapping each in a `StageTimer`
so every stage's cost is measured separately. The `DebugScan` it returns is
byte-for-byte equivalent to `build_scan(...)` for the same inputs (guarded by a
drift test), so the numbers describe the production path — measurement only, no
behaviour change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bap.core.domain.models import Rect
from bap.forge.detection.geometry import CaptureGeometry, ScanRois, default_battle_map
from bap.forge.detection.scan import (
    DebugScan,
    _classify,
    _panel_state,
    _rect_to_box,
    select_target,
)
from bap.forge.detection.weakening import Decision, decide, read_ocr
from bap.perf.timing import StageTimer


def run_tick(
    image,
    *,
    world=None,
    detector,
    classifier=None,
    rois: ScanRois | None = None,
    weakening_region: Rect | None = None,
    geometry: CaptureGeometry | None = None,
    persist: bool = False,
    gui_sink=None,
) -> tuple[DebugScan, StageTimer]:
    """Run one full tick, timing each stage. Mirrors `scan.build_scan` exactly.

    `image` may be a decoded array or a path (a path is decoded in the timed
    ``capture`` stage). `detector` is required and should be reused across ticks
    (constructing it per tick would measure setup, not steady-state cost).
    `persist`/`gui_sink` add representative persistence and GUI-update stages when
    a benchmark wants them measured.
    """
    import cv2

    timer = StageTimer()
    with timer.tick():
        # capture — decode the frame (a live capture would produce the array here).
        with timer.stage("capture"):
            img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image

        geometry = geometry or (CaptureGeometry.from_image(img) if img is not None
                                else CaptureGeometry(0, 0))
        if rois is None:
            battle = default_battle_map(geometry, weakening_region)
            rois = ScanRois(battle_map=battle, weakening=weakening_region,
                            weakening_calibrated=weakening_region is not None,
                            battle_map_calibrated=False)
        weak_roi = rois.weakening

        # detection — badge candidates over the battle-map ROI.
        with timer.stage("detection"):
            result = detector.scan(img, region=_rect_to_box(rois.battle_map))
        detections = result.detections

        # classification — percentage classifier + province-panel corroboration.
        classify_diag: list[dict] = []
        panel_result, panel = (None, None)
        with timer.stage("classification"):
            if classifier is not None and len(classifier) and img is not None:
                detections, classify_diag = _classify(img, detections, classifier)
            if img is not None:
                panel_result, panel = _panel_state(img, detector, classifier)

        # weakening_ocr — the per-World safety gate read.
        weak_read = None
        with timer.stage("weakening_ocr"):
            if weak_roi is not None and img is not None:
                weak_read = read_ocr(img, weak_roi)

        # decision — gate decision + deterministic target selection.
        world_limit = getattr(world, "max_weakening", None) if world is not None else None
        bm = rois.battle_map
        center = (bm.x + bm.w // 2, bm.y + bm.h // 2)
        with timer.stage("decision"):
            decision = decide(weak_read, world) if (weak_read is not None) else Decision.UNKNOWN
            selection = select_target(detections, world, frame_center=center)

        h, w = (img.shape[0], img.shape[1]) if img is not None else (0, 0)
        scan = DebugScan(
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

        # persistence — representative serialization cost (no disk I/O by default).
        if persist:
            with timer.stage("persistence"):
                json.dumps(scan.to_dict())

        # gui_update — representative marshaling cost, if a sink is supplied.
        if gui_sink is not None:
            with timer.stage("gui_update"):
                gui_sink(scan)

    return scan, timer


__all__ = ["run_tick"]
