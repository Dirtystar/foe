"""Read the current-weakening number and decide the safety gate.

Kept entirely separate from badge percentage classification — this is the
attrition counter in the top bar (an integer that can exceed 100), and it gates
whether a world may act at all.

Two readers are provided for the spike:
  - `read_ocr`   — preprocess (grayscale, upscale, Otsu, invert) then Tesseract
                   with a digits-only whitelist; confidence from Tesseract.
  - `read_template` — deterministic: segment digit blobs, match each against
                   digit glyph templates (0-9), assemble; confidence is the
                   weakest per-digit match.

The fail-safe policy is deliberately conservative: anything not confidently read
yields UNKNOWN (no action); at or above the world limit yields STOP; only a
confident value below the limit yields CONTINUE. It never continues blindly.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from bap.core.domain.models import Rect

try:
    import cv2
    import numpy as np

    _CV = True
except Exception:  # pragma: no cover
    _CV = False

# Minimum reader confidence to treat a value as usable by the safety gate.
DEFAULT_MIN_CONFIDENCE = 0.60


class Decision(str, Enum):
    CONTINUE = "CONTINUE"
    STOP = "STOP"
    UNKNOWN = "UNKNOWN"


@dataclass
class WeakeningRead:
    value: int | None
    confidence: float
    method: str
    raw_crop: object = None        # BGR ndarray of the region
    processed_crop: object = None  # binarised/upscaled ndarray fed to the reader

    def to_dict(self) -> dict:
        return {"value": self.value, "confidence": round(self.confidence, 4), "method": self.method}


def _crop(image, rect: Rect):
    h, w = image.shape[:2]
    x0, y0 = max(0, rect.x), max(0, rect.y)
    x1, y1 = min(w, rect.x + rect.w), min(h, rect.y + rect.h)
    if x1 <= x0 or y1 <= y0:
        return None
    return image[y0:y1, x0:x1]


def _preprocess(crop, scale: int = 6):
    """Grayscale, upscale, Otsu-threshold to dark-digits-on-light."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _t, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if binary.mean() > 127:  # digits are light on dark → invert
        binary = 255 - binary
    return binary


def read_ocr(image, rect: Rect) -> WeakeningRead:
    if not _CV:  # pragma: no cover
        return WeakeningRead(None, 0.0, "ocr")
    crop = _crop(image, rect)
    if crop is None:
        return WeakeningRead(None, 0.0, "ocr")
    processed = _preprocess(crop)
    try:
        import pytesseract

        data = pytesseract.image_to_data(
            processed, config="--psm 7 -c tessedit_char_whitelist=0123456789",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return WeakeningRead(None, 0.0, "ocr", raw_crop=crop, processed_crop=processed)
    digits, confs = "", []
    for text, conf in zip(data["text"], data["conf"]):
        text = text.strip()
        if text.isdigit():
            digits += text
            try:
                confs.append(float(conf))
            except (TypeError, ValueError):
                pass
    value = int(digits) if digits else None
    confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return WeakeningRead(value, confidence, "ocr", raw_crop=crop, processed_crop=processed)


def read_template(image, rect: Rect, digit_templates: dict) -> WeakeningRead:
    """Deterministic digit matching. `digit_templates` maps digit int -> a binary
    glyph ndarray. Returns a low confidence when templates are missing."""
    if not _CV or not digit_templates:
        return WeakeningRead(None, 0.0, "template")
    crop = _crop(image, rect)
    if crop is None:
        return WeakeningRead(None, 0.0, "template")
    processed = _preprocess(crop)
    # Segment digit blobs left-to-right.
    count, _lbl, stats, _cent = cv2.connectedComponentsWithStats(processed, connectivity=8)
    boxes = []
    H = processed.shape[0]
    for i in range(1, count):
        x, y, w, h, area = (int(stats[i, k]) for k in range(5))
        if h < 0.4 * H or area < 8:
            continue  # ignore specks and short noise
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])
    if not boxes:
        return WeakeningRead(None, 0.0, "template", raw_crop=crop, processed_crop=processed)

    digits, scores = "", []
    for (x, y, w, h) in boxes:
        glyph = processed[y:y + h, x:x + w]
        best_d, best_s = None, -1.0
        for d, tpl in digit_templates.items():
            g = cv2.resize(glyph, (tpl.shape[1], tpl.shape[0]))
            r = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
            s = float(np.nan_to_num(r).max())
            if s > best_s:
                best_s, best_d = s, d
        digits += str(best_d)
        scores.append(best_s)
    value = int(digits) if digits else None
    confidence = min(scores) if scores else 0.0  # weakest digit governs
    return WeakeningRead(value, max(0.0, confidence), "template", raw_crop=crop, processed_crop=processed)


def decide(read: WeakeningRead, world, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> Decision:
    """Fail-safe gate. Unreadable / low-confidence → UNKNOWN (no action);
    value ≥ world.max_weakening → STOP; a confident value below → CONTINUE."""
    if read.value is None or read.confidence < min_confidence:
        return Decision.UNKNOWN
    limit = getattr(world, "max_weakening", 100) if world is not None else 100
    return Decision.STOP if read.value >= limit else Decision.CONTINUE


@dataclass
class WorldWeakeningStatus:
    """Result of feeding one read into a World's tracker."""

    world_id: str
    confirmed: int | None       # the World's currently-confirmed weakening, or None
    accepted: bool              # did this read confirm/update the value?
    reason: str
    suspicious: bool = False     # a large, unexplained change (likely a misread)


class WeakeningTracker:
    """Per-World temporal validation of weakening reads at runtime.

    Weakening is only meaningful as a series *within a single World* — the value
    for World H and the value for World Farm are unrelated and must never be
    compared. This tracker keeps one independent history per ``world_id`` and
    confirms a value only when consecutive confident reads agree (consensus),
    treating a large unexplained drop (e.g. 86 → 36 from an OCR misread) as
    suspicious so it does not become the confirmed value.

    It holds no global history across tabs. The grading dataset is NOT fed
    through this — those 15 frames are independent snapshots, not a series.
    """

    def __init__(self, *, consensus: int = 2, max_plausible_drop: int = 20,
                 reset_threshold: int = 5, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
        self._consensus = max(1, consensus)
        self._max_drop = max_plausible_drop
        self._reset_threshold = reset_threshold
        self._min_conf = min_confidence
        self._confirmed: dict[str, int] = {}
        self._streak: dict[str, list[int]] = defaultdict(list)

    @property
    def last_confirmed_by_world(self) -> dict[str, int]:
        """last_confirmed_weakening_by_world — a copy, keyed by World id."""
        return dict(self._confirmed)

    def last_confirmed(self, world_id: str) -> int | None:
        return self._confirmed.get(world_id)

    def _is_suspicious(self, world_id: str, value: int) -> bool:
        prev = self._confirmed.get(world_id)
        if prev is None:
            return False
        # A big decrease that is not a plausible round reset (toward ~0).
        return value < prev - self._max_drop and value > self._reset_threshold

    def observe(self, world_id: str, read: WeakeningRead) -> WorldWeakeningStatus:
        """Feed one read for `world_id`; return the World's validated status.

        A read is confirmed only once `consensus` consecutive confident reads
        agree. A suspicious drop requires twice that many, so a lone misread never
        flips the confirmed value — it yields UNKNOWN and leaves the prior value."""
        confirmed = self._confirmed.get(world_id)
        if read.value is None or read.confidence < self._min_conf:
            self._streak[world_id] = []  # a bad read breaks the run
            return WorldWeakeningStatus(world_id, confirmed, False, "unreadable/low-confidence")

        streak = self._streak[world_id]
        if streak and streak[-1] != read.value:
            streak = []  # value changed — restart the agreement run
        streak.append(read.value)
        self._streak[world_id] = streak

        suspicious = self._is_suspicious(world_id, read.value)
        needed = self._consensus * (2 if suspicious else 1)
        if len(streak) >= needed:
            self._confirmed[world_id] = read.value
            return WorldWeakeningStatus(world_id, read.value, True,
                                        "confirmed by consensus", suspicious=suspicious)
        reason = ("suspicious drop — awaiting stronger consensus" if suspicious
                  else "awaiting consensus")
        return WorldWeakeningStatus(world_id, confirmed, False, reason, suspicious=suspicious)

    def decide(self, world_id: str, world) -> Decision:
        """Fail-safe decision for a World from its CONFIRMED value (not a raw
        read). No confirmed value → UNKNOWN; ≥ limit → STOP; below → CONTINUE."""
        confirmed = self._confirmed.get(world_id)
        if confirmed is None:
            return Decision.UNKNOWN
        limit = getattr(world, "max_weakening", 100) if world is not None else 100
        return Decision.STOP if confirmed >= limit else Decision.CONTINUE


def build_digit_templates(samples: list[tuple[object, int]]) -> dict:
    """Build digit glyph templates from labelled (region_crop_bgr, value) samples:
    segment each sample's digits left-to-right and pair them with the value's
    digits. One glyph per digit is kept (first seen). Returns {digit: binary}."""
    if not _CV:  # pragma: no cover
        return {}
    templates: dict[int, object] = {}
    for crop, value in samples:
        if crop is None or value is None:
            continue
        processed = _preprocess(crop)
        count, _lbl, stats, _cent = cv2.connectedComponentsWithStats(processed, connectivity=8)
        H = processed.shape[0]
        boxes = []
        for i in range(1, count):
            x, y, w, h, area = (int(stats[i, k]) for k in range(5))
            if h < 0.4 * H or area < 8:
                continue
            boxes.append((x, y, w, h))
        boxes.sort(key=lambda b: b[0])
        digits = str(int(value))
        if len(boxes) != len(digits):
            continue  # segmentation disagreed with the label — skip, don't guess
        for (x, y, w, h), ch in zip(boxes, digits):
            d = int(ch)
            if d not in templates:
                templates[d] = processed[y:y + h, x:x + w]
    return templates


__all__ = [
    "Decision", "WeakeningRead", "DEFAULT_MIN_CONFIDENCE",
    "read_ocr", "read_template", "decide", "build_digit_templates",
    "WeakeningTracker", "WorldWeakeningStatus",
]
