"""Optional CV pre-suggester for badge centres.

Every weakening badge carries a small, bright **red down-arrow** in its emblem.
Segmenting saturated-red blobs of badge size inside the game area proposes
candidate centres, so the labeller mostly *confirms* clicks instead of hunting
for every badge. This is assistive only — it is expected to miss some and
over-propose a few (the human corrects), and it is deliberately NOT the detector.

OpenCV is optional: without it (or on a decode error) `suggest_badges` returns
an empty list and `available()` is False, so the tool still works for fully
manual labelling.
"""

from __future__ import annotations

from pathlib import Path

try:  # OpenCV/NumPy are optional (the 'vision' extra)
    import cv2
    import numpy as np

    _CV = True
except Exception:  # pragma: no cover - environment dependent
    _CV = False

# Game-content region for a 1920x1080 Forge capture: below the browser chrome,
# right of the left black band. Keeps chrome's red icons out of the candidates.
_X0, _X1 = 440, 1915
_Y0, _Y1 = 500, 1075

# A weakening arrow blob is small (~30-60 px) and very compact. Tight bounds
# keep the arrow while dropping the larger, duller-red province name banners.
_MIN_AREA, _MAX_AREA = 12, 90
_MAX_SIDE = 24


def available() -> bool:
    """True when CV-based suggestions can run (OpenCV present)."""
    return _CV


def suggest_badges(image) -> list[tuple[int, int]]:
    """Return candidate badge centres (cx, cy) in original-image pixels.

    `image` is a path or a BGR ndarray. Returns [] if OpenCV is unavailable or
    the image cannot be read. Results are sorted top-to-bottom, left-to-right for
    a stable review order.
    """
    if not _CV:
        return []
    img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image
    if img is None or getattr(img, "size", 0) == 0:
        return []

    h, w = img.shape[:2]
    x0, x1 = min(_X0, w), min(_X1, w)
    y0, y1 = min(_Y0, h), min(_Y1, h)
    if x1 <= x0 or y1 <= y0:
        return []

    roi = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # Bright, saturated red (hue wraps around 0/180) — the attrition arrow.
    red = (((hue <= 8) | (hue >= 172)) & (sat >= 160) & (val >= 120)).astype("uint8")
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), "uint8"))

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(red, connectivity=8)
    out: list[tuple[int, int]] = []
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        if not (_MIN_AREA <= area <= _MAX_AREA) or bw > _MAX_SIDE or bh > _MAX_SIDE:
            continue
        cx, cy = centroids[i]
        out.append((int(cx) + x0, int(cy) + y0))
    out.sort(key=lambda p: (p[1], p[0]))
    return out


__all__ = ["available", "suggest_badges"]
