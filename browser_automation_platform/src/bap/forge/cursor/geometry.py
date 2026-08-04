"""The image → screen coordinate contract for the cursor preview (Milestone 5A).

The single, explicit transformation from a would-click point in raw capture pixels
to a Windows physical-screen pixel, through the four stages the milestone names:

    raw image pixels
      → captured viewport (CSS) pixels        [divide out the capture/DPR scale]
      → browser content (CSS) pixels          [add any scroll offset]
      → screen logical (CSS/DIP) pixels        [add window origin + content offset]
      → Windows physical-screen pixels         [multiply by the monitor scale]

Every factor is explicit and every intermediate point is recorded in a
``CoordinateTrace`` for diagnostics and the audit log. Nothing here assumes the
browser content begins at screen (0, 0); negative screen coordinates (a monitor
left of / above the primary) are preserved. CSS pixels and device pixels are never
mixed silently — the DPR / capture ratio is applied exactly once, and the monitor
scale exactly once.

This module is pure math with no I/O, Qt, or Playwright, so the whole contract is
unit-testable across 100 %/125 % scaling, multiple monitors, and negative origins.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WindowGeometry:
    """Everything needed to place a viewport point on the physical screen, plus the
    identity used to detect that the window moved/resized between scan and move.

    Positions are in **logical (CSS/DIP) screen coordinates** — what Chrome's
    window bounds report and what is stable across DPI. ``monitor_scale`` converts
    those to physical pixels for the OS cursor API (1.0 at 100 %, 1.25 at 125 %)."""

    # Browser window top-left, logical screen coords (may be negative on a
    # secondary monitor to the left/above the primary).
    window_x: int
    window_y: int
    window_w: int
    window_h: int
    # Offset of the content area (top-left of the rendered page) from the window
    # top-left: the OS frame + title bar + tab strip + toolbars, in logical px.
    content_offset_x: int
    content_offset_y: int
    # Rendering parameters (must match the capture the point came from).
    device_pixel_ratio: float = 1.0
    zoom: float = 1.0
    viewport_w: int | None = None
    viewport_h: int | None = None
    capture_w: int | None = None
    capture_h: int | None = None
    # Windows display scaling for the monitor this window is on.
    monitor_scale: float = 1.0
    # Content scroll offset (the Forge battleground canvas is not scrolled → 0).
    scroll_x: int = 0
    scroll_y: int = 0
    # Stable identity of the window, so a different/rearranged window is rejected.
    window_id: str | None = None
    monitor_id: str | None = None

    def identity(self) -> tuple:
        """The fields whose change between scan and move must block a move: the
        window/monitor identity and every geometry factor that would shift where a
        point lands."""
        return (
            self.window_id, self.monitor_id,
            self.window_x, self.window_y, self.window_w, self.window_h,
            self.content_offset_x, self.content_offset_y,
            round(self.device_pixel_ratio, 4), round(self.zoom, 4),
            self.viewport_w, self.viewport_h, self.capture_w, self.capture_h,
            round(self.monitor_scale, 4),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CoordinateTrace:
    """Every stage of one image→screen transform, persisted for diagnostics."""

    image: tuple[int, int]
    viewport_css: tuple[float, float]
    content_css: tuple[float, float]
    screen_logical: tuple[float, float]
    screen_physical: tuple[int, int]
    scale_x: float
    scale_y: float
    device_pixel_ratio: float
    zoom: float
    monitor_scale: float
    window_origin: tuple[int, int]
    content_offset: tuple[int, int]

    def to_dict(self) -> dict:
        return {
            "image": list(self.image),
            "viewport_css": list(self.viewport_css),
            "content_css": list(self.content_css),
            "screen_logical": list(self.screen_logical),
            "screen_physical": list(self.screen_physical),
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "device_pixel_ratio": self.device_pixel_ratio,
            "zoom": self.zoom,
            "monitor_scale": self.monitor_scale,
            "window_origin": list(self.window_origin),
            "content_offset": list(self.content_offset),
        }


def _capture_to_viewport_scale(geom: WindowGeometry) -> tuple[float, float]:
    """CSS-pixels-per-capture-pixel for each axis. Prefer the exact capture↔viewport
    ratio when both are known (it already folds in DPR *and* any capture rescale);
    otherwise fall back to 1/DPR. Applied exactly once — image px are device px, the
    viewport is CSS px."""
    if geom.viewport_w and geom.capture_w and geom.viewport_h and geom.capture_h:
        return geom.viewport_w / geom.capture_w, geom.viewport_h / geom.capture_h
    dpr = geom.device_pixel_ratio or 1.0
    return 1.0 / dpr, 1.0 / dpr


def image_to_screen(image_point: tuple[int, int], geom: WindowGeometry) -> CoordinateTrace:
    """Transform a raw-capture pixel to a Windows physical-screen pixel, returning
    the full stage-by-stage trace. Pure; performs no movement."""
    ix, iy = int(image_point[0]), int(image_point[1])

    # 1. raw image px → captured viewport CSS px (divide out capture/DPR scale once)
    sx, sy = _capture_to_viewport_scale(geom)
    vp_x, vp_y = ix * sx, iy * sy

    # 2. viewport CSS → browser content CSS (account for any scroll; Forge = 0)
    content_x, content_y = vp_x + geom.scroll_x, vp_y + geom.scroll_y

    # 3. content CSS → screen logical CSS (window origin + frame/title/toolbar)
    screen_log_x = geom.window_x + geom.content_offset_x + content_x
    screen_log_y = geom.window_y + geom.content_offset_y + content_y

    # 4. screen logical → Windows physical (monitor scale once; preserve sign)
    scale = geom.monitor_scale or 1.0
    screen_x = int(round(screen_log_x * scale))
    screen_y = int(round(screen_log_y * scale))

    return CoordinateTrace(
        image=(ix, iy),
        viewport_css=(vp_x, vp_y),
        content_css=(content_x, content_y),
        screen_logical=(screen_log_x, screen_log_y),
        screen_physical=(screen_x, screen_y),
        scale_x=sx, scale_y=sy,
        device_pixel_ratio=geom.device_pixel_ratio,
        zoom=geom.zoom,
        monitor_scale=scale,
        window_origin=(geom.window_x, geom.window_y),
        content_offset=(geom.content_offset_x, geom.content_offset_y),
    )


def point_in_capture(image_point: tuple[int, int], capture_w: int, capture_h: int) -> bool:
    """True when the point lies inside the captured viewport bounds."""
    ix, iy = image_point
    return 0 <= ix < capture_w and 0 <= iy < capture_h


__all__ = ["WindowGeometry", "CoordinateTrace", "image_to_screen", "point_in_capture"]
