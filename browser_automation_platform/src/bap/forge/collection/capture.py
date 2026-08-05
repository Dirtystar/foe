"""One-click capture → canonical dataset, with provenance (Milestone 5D).

The caller hands us a raw read-only screenshot (already captured — this module
never talks to a browser). We run the EXISTING detector/classifier for *suggestions
only*, file the frame into the canonical reviewed dataset via
:func:`bap.forge.dataset_store.add_frame` (image-hash dedup, unreviewed seed), and
write a provenance record so the frame can always be traced back to its World,
capture geometry, and collection session. No threshold/classifier/detector change,
no clicking, no cursor movement.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from bap.forge.dataset_store import (
    FRAMES_DIRNAME,
    LABELS_NAME,
    add_frame,
    reviewed_dataset_dir,
)

META_DIRNAME = "imported_meta"


@dataclass
class CaptureProvenance:
    """Everything needed to trace a captured frame back to its origin."""
    frame: str
    md5: str
    alias: str | None
    hostname: str | None
    url: str | None
    capture_w: int
    capture_h: int
    viewport_w: int | None
    viewport_h: int | None
    dpr: float | None
    zoom: float | None
    browser_mode: str
    timestamp: str
    session_id: str | None
    source: str = "live_collection"
    detected: int = 0
    classified: int = 0
    unknown: int = 0


@dataclass
class CaptureResult:
    frame: str
    is_new: bool
    md5: str
    detected: int
    classified: int
    unknown: int
    path: str


def _md5_bytes(image) -> str:
    import hashlib

    import cv2
    ok, buf = cv2.imencode(".png", image)
    return hashlib.md5(buf.tobytes()).hexdigest() if ok else ""


def default_classifier():
    """The bundled reviewed classifier (grading + live), Qt-free. None if nothing
    reviewed / OpenCV missing. Used only to *suggest* percentages."""
    try:
        from bap.forge.detection.classify import (
            default_assets_root,
            default_label_sources,
            train_from_sources,
        )
        root = default_assets_root()
        if root is None:
            return None
        sources = default_label_sources(root)
        return train_from_sources(sources) if sources else None
    except Exception:
        return None


def _write_provenance(dataset: Path, prov: CaptureProvenance) -> None:
    meta_dir = dataset / META_DIRNAME
    meta_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(prov.frame).stem
    tmp = meta_dir / f"{stem}.json.tmp"
    tmp.write_text(json.dumps(asdict(prov), indent=2))
    os.replace(tmp, meta_dir / f"{stem}.json")


def capture_frame(image, *, world=None, geometry=None, session=None,
                  detector=None, classifier=None, dataset_dir=None,
                  timestamp: datetime | None = None) -> CaptureResult:
    """Import one already-captured screenshot into the canonical dataset.

    ``world`` may be a :class:`bap.forge.worlds.World` (or any object with
    ``alias``/``hostname``/``last_url``). ``geometry`` may carry viewport/DPR/zoom
    (e.g. a cursor ``WindowGeometry``); missing fields are recorded as null.
    Returns the :class:`CaptureResult`; a duplicate image is detected by hash and
    **not** re-added (``is_new=False``). Also updates the session's counters."""
    from bap.forge.detection.detector import BadgeDetector
    from bap.forge.detection.scan import build_scan

    ts = timestamp or datetime.now()
    alias = getattr(world, "alias", None)
    detector = detector or BadgeDetector()
    classifier = classifier if classifier is not None else default_classifier()

    scan = build_scan(image, world=world, detector=detector, classifier=classifier)
    detected = len(scan.detections)
    classified = sum(1 for d in scan.detections if getattr(d, "pct", None) is not None)
    unknown = detected - classified

    frame_name, is_new = add_frame(image, alias=alias, scan=scan,
                                   dataset_dir=dataset_dir, source="live_collection",
                                   timestamp=ts)
    dataset = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir()

    if is_new:
        vw = getattr(geometry, "viewport_w", None) if geometry is not None else None
        vh = getattr(geometry, "viewport_h", None) if geometry is not None else None
        prov = CaptureProvenance(
            frame=frame_name, md5=_md5_bytes(image), alias=alias,
            hostname=getattr(world, "hostname", None),
            url=getattr(world, "last_url", None) or None,
            capture_w=int(image.shape[1]), capture_h=int(image.shape[0]),
            viewport_w=vw, viewport_h=vh,
            dpr=getattr(geometry, "device_pixel_ratio", None) if geometry is not None else None,
            zoom=getattr(geometry, "zoom", None) if geometry is not None else None,
            browser_mode=getattr(session, "browser_mode", "unknown") if session else "unknown",
            timestamp=ts.isoformat(timespec="seconds"),
            session_id=getattr(session, "session_id", None) if session else None,
            detected=detected, classified=classified, unknown=unknown,
        )
        _write_provenance(dataset, prov)

    if session is not None:
        session.record_capture(frame_name, is_new=is_new)

    return CaptureResult(
        frame=frame_name, is_new=is_new, md5=_md5_bytes(image),
        detected=detected, classified=classified, unknown=unknown,
        path=str(dataset / FRAMES_DIRNAME / frame_name),
    )


def provenance_for(frame_name: str, *, dataset_dir=None) -> dict | None:
    """Read the provenance record for a frame (imported_meta/<stem>.json), or None.
    Falls back to a snapshot-import metadata shape if that is what is present."""
    dataset = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir()
    p = dataset / META_DIRNAME / f"{Path(frame_name).stem}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


__all__ = ["capture_frame", "CaptureResult", "CaptureProvenance",
           "provenance_for", "default_classifier", "META_DIRNAME"]
