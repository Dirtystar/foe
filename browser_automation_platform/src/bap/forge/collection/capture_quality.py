"""Capture-quality pre-flight checks (Milestone 5D UX).

Warns the operator *before they waste time* on unusable data: a browser that
detached, a duplicate or nearly-identical frame, an unexpected resolution, an
unsupported browser zoom, or a resolution with no calibration. Pure analysis — it
reads the candidate image and the dataset, and never captures, labels, or mutates
anything. Each warning explains **what/why/how-to-fix**.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from bap.forge.dataset_store import CALIB_NAME, FRAMES_DIRNAME, reviewed_dataset_dir

# Resolutions the vision slice has been calibrated/validated against. Anything else
# still captures, but the operator is warned it may need a calibration.
SUPPORTED_HEIGHTS = {1080, 952, 912, 900}
NEAR_DUP_BITS = 4          # aHash Hamming distance treated as "nearly identical"
ZOOM_TOLERANCE = 0.02      # |zoom - 1.0| above this is "unsupported"


@dataclass
class Warning:
    level: str        # "error" | "warning"
    code: str
    message: str
    fix: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _ahash(gray8) -> int:
    import cv2
    small = cv2.resize(gray8, (8, 8), interpolation=cv2.INTER_AREA)
    bits = (small > small.mean()).flatten()
    h = 0
    for b in bits:
        h = (h << 1) | int(b)
    return h


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _calibrated_resolutions(dataset: Path) -> set[str]:
    import json
    p = dataset / CALIB_NAME
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
    except Exception:
        return set()
    out = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and "x" in k and k[:1].isdigit():
                out.add(k)
            if isinstance(v, dict):
                out |= {kk for kk in v if isinstance(kk, str) and "x" in kk and kk[:1].isdigit()}
    return out


def assess_capture(image, *, world=None, geometry=None, dataset_dir=None,
                   capture_error: str | None = None) -> list[Warning]:
    """Return quality warnings for a candidate capture. An empty list means the
    frame looks good to collect."""
    warnings: list[Warning] = []

    # 1. Browser detached / capture failed — nothing to assess.
    if capture_error:
        warnings.append(Warning(
            "error", "browser_detached",
            f"Capture failed: {capture_error}",
            "Re-attach the World (World Manager → Scan & Reattach) and check the tab "
            "is still open, then capture again."))
        return warnings
    if image is None:
        warnings.append(Warning(
            "error", "no_image", "No image was captured.",
            "Confirm the World is attached to a live tab, then retry."))
        return warnings

    import cv2
    import numpy as np

    h, w = image.shape[:2]
    dataset = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir()
    res = f"{w}x{h}"

    # 2. Unexpected resolution.
    if h not in SUPPORTED_HEIGHTS:
        warnings.append(Warning(
            "warning", "wrong_resolution",
            f"Unusual capture resolution {res} (height {h} not in "
            f"{sorted(SUPPORTED_HEIGHTS, reverse=True)}).",
            "Maximise the Chrome window / reset zoom to 100%. The frame still saves, "
            "but set a calibration for this resolution before relying on detections."))

    # 3. Unsupported zoom.
    zoom = getattr(geometry, "zoom", None) if geometry is not None else None
    if zoom is not None and abs(float(zoom) - 1.0) > ZOOM_TOLERANCE:
        warnings.append(Warning(
            "warning", "unsupported_zoom",
            f"Browser zoom is {float(zoom) * 100:.0f}% (not 100%).",
            "Press Ctrl+0 in Chrome to reset zoom to 100% for consistent scale."))

    # 4. Calibration missing for this resolution.
    if res not in _calibrated_resolutions(dataset):
        warnings.append(Warning(
            "warning", "calibration_missing",
            f"No calibration stored for {res}.",
            "Open a frame of this resolution in Review and set the weakening / "
            "battle-map region once; it then applies to every capture at this size."))

    # 5. Exact duplicate + nearly-identical frame.
    frames_dir = dataset / FRAMES_DIRNAME
    if frames_dir.is_dir():
        ok, buf = cv2.imencode(".png", image)
        digest = hashlib.md5(buf.tobytes()).hexdigest() if ok else None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cand_hash = _ahash(gray)
        exact = None
        near = None
        for existing in sorted(frames_dir.glob("*.png")):
            data = existing.read_bytes()
            if digest is not None and hashlib.md5(data).hexdigest() == digest:
                exact = existing.name
                break
            img2 = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img2 is not None and _hamming(cand_hash, _ahash(img2)) <= NEAR_DUP_BITS:
                near = near or existing.name
        if exact:
            warnings.append(Warning(
                "warning", "duplicate",
                f"This exact screenshot already exists ({exact}).",
                "Move the battle map (scroll/select a different province) before "
                "capturing again — a duplicate adds no new data."))
        elif near:
            warnings.append(Warning(
                "warning", "near_identical",
                f"This frame is nearly identical to {near}.",
                "Change the view (different province / scroll position) to capture "
                "genuinely new badges."))
    return warnings


def summarize(warnings: list[Warning]) -> str:
    if not warnings:
        return "OK — good to collect."
    return "  ·  ".join(f"[{w.level}] {w.message}" for w in warnings)


__all__ = ["assess_capture", "Warning", "summarize",
           "SUPPORTED_HEIGHTS", "ZOOM_TOLERANCE", "NEAR_DUP_BITS"]
