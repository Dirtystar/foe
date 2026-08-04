"""Forge Test-Scan capture geometry and analysis regions (ROIs).

Every Test Scan starts from ONE unmodified full raw capture — the browser
*content viewport*, containing the whole Forge top bar (with the current
weakening) AND the whole visible battleground map at once. Two ROIs are derived
from that single capture, both expressed in **full-raw-capture pixels**:

  * ``weakening_roi``  — the top-bar attrition counter (the safety gate).
  * ``battle_map_roi`` — the whole usable battleground map below the top bar.

Nothing is cropped away before analysis: the weakening reader looks at the
weakening ROI, the badge detector looks at the battle-map ROI, and every
coordinate the detector reports is mapped back to full-capture pixels.

Calibration is keyed by the **exact capture geometry** (raw size, and — when the
browser can report them — viewport size, device-pixel-ratio and zoom). A region
calibrated for one capture setup is therefore never silently reused for a
different one (for example a full-desktop screenshot vs. a page-content
capture, which have completely different layouts at the same pixel size).
"""

from __future__ import annotations

from dataclasses import dataclass

from bap.core.domain.models import Rect

# Fraction of the capture height treated as "top bar" when nothing is calibrated,
# so the fallback battle-map ROI starts just below it rather than over it.
_DEFAULT_TOP_BAR_FRACTION = 0.06


@dataclass(frozen=True)
class CaptureGeometry:
    """Exact geometry of one raw capture. ``raw_w``/``raw_h`` are the pixel size
    of the capture itself; the rest describe how the browser produced it and are
    ``None`` when unavailable (e.g. an offline screenshot).

    ``browser_mode`` / ``cdp_endpoint`` record the capture *provenance* (which
    browser produced the pixels). External-Chrome captures contribute the mode to
    the calibration ``key`` so an External-Chrome layout is never silently
    calibrated against a Managed-Chromium one; Managed keys are unchanged, so
    existing calibrations keep matching."""

    raw_w: int
    raw_h: int
    viewport_w: int | None = None
    viewport_h: int | None = None
    device_pixel_ratio: float | None = None
    zoom: float | None = None
    browser_mode: str | None = None
    cdp_endpoint: str | None = None

    @classmethod
    def from_image(cls, image, **meta) -> "CaptureGeometry":
        h, w = image.shape[:2]
        return cls(raw_w=int(w), raw_h=int(h), **meta)

    def key(self) -> str:
        """A stable key that includes every geometry field we know, so distinct
        capture setups never collide (raw size alone is not enough). External
        Chrome adds a ``ext`` marker so its calibration is kept separate from a
        Managed-Chromium capture of the same pixel size; Managed adds nothing, so
        keys predating this field are byte-identical."""
        parts = [f"{self.raw_w}x{self.raw_h}"]
        if self.viewport_w and self.viewport_h:
            parts.append(f"vp{self.viewport_w}x{self.viewport_h}")
        if self.device_pixel_ratio:
            parts.append(f"dpr{self.device_pixel_ratio:g}")
        if self.zoom:
            parts.append(f"z{self.zoom:g}")
        if self.browser_mode and self.browser_mode != "managed_chromium":
            parts.append(f"ext:{self.browser_mode}")
        return "|".join(parts)

    def to_dict(self) -> dict:
        return {
            "raw_w": self.raw_w,
            "raw_h": self.raw_h,
            "viewport_w": self.viewport_w,
            "viewport_h": self.viewport_h,
            "device_pixel_ratio": self.device_pixel_ratio,
            "zoom": self.zoom,
            "browser_mode": self.browser_mode,
            "cdp_endpoint": self.cdp_endpoint,
            "key": self.key(),
        }


@dataclass(frozen=True)
class ScanRois:
    """The two analysis regions for one capture, in full-capture pixels."""

    battle_map: Rect
    weakening: Rect | None = None
    weakening_calibrated: bool = False
    battle_map_calibrated: bool = False

    def to_dict(self) -> dict:
        def r(rect: Rect | None):
            return None if rect is None else [rect.x, rect.y, rect.w, rect.h]

        return {
            "weakening_roi": r(self.weakening),
            "weakening_calibrated": self.weakening_calibrated,
            "battle_map_roi": r(self.battle_map),
            "battle_map_calibrated": self.battle_map_calibrated,
        }


def default_battle_map(geometry: CaptureGeometry, weakening: Rect | None = None) -> Rect:
    """The whole usable map when it has not been calibrated: full capture width,
    from just below the top bar down to the bottom. If the weakening ROI is
    known, the top bar is assumed to end at its lower edge; otherwise a thin band
    at the top is skipped."""
    w, h = geometry.raw_w, geometry.raw_h
    if weakening is not None:
        top = min(h - 1, max(0, weakening.y + weakening.h))
    else:
        top = int(round(h * _DEFAULT_TOP_BAR_FRACTION))
    return Rect(x=0, y=top, w=w, h=max(1, h - top))


def derive_rois(geometry: CaptureGeometry, calibration=None) -> ScanRois:
    """Resolve the two ROIs for a capture from the user's calibration, filling in
    a whole-map fallback for the battle map so the analyzed area always covers
    the visible map rather than an arbitrary sub-rectangle."""
    weakening = None
    battle_map = None
    weak_cal = bmap_cal = False
    if calibration is not None:
        weakening = calibration.get(geometry.raw_w, geometry.raw_h)
        weak_cal = weakening is not None
        getter = getattr(calibration, "get_battle_map", None)
        if getter is not None:
            battle_map = getter(geometry.raw_w, geometry.raw_h)
            bmap_cal = battle_map is not None
    if battle_map is None:
        battle_map = default_battle_map(geometry, weakening)
    return ScanRois(
        battle_map=battle_map,
        weakening=weakening,
        weakening_calibrated=weak_cal,
        battle_map_calibrated=bmap_cal,
    )


__all__ = ["CaptureGeometry", "ScanRois", "default_battle_map", "derive_rois"]
