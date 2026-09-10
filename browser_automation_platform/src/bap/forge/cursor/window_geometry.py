"""Real Windows browser-geometry acquisition for the cursor preview (M5A.1).

M5A shipped the coordinate contract and safety gate but left ``WindowGeometry``
unmeasured, so the gate always blocked with "window geometry unavailable". This
module closes that gap by measuring the real geometry of the attached
Chrome/Chromium window and its web-content viewport, so the existing transform can
map raw-screenshot px → physical screen px **without guessing**.

Two evidence sources, combined deterministically:

* **CDP measurement** (``measure_via_cdp``) — ``Browser.getWindowForTarget`` +
  ``Browser.getWindowBounds`` give the outer window rectangle and identity;
  ``Page.getLayoutMetrics`` gives the CSS viewport; DPR is *derived* from
  capture÷viewport (no ``Runtime.evaluate``); zoom from the visual viewport. This
  yields everything except the exact on-screen **content origin** — CDP does not
  expose where the rendered page begins on the physical screen.
* **Content-origin** — resolved either from the native window's client area
  (Win32, when uniquely identifiable) or from a one-time **operator calibration**
  ("Set Browser Content Origin"), persisted and keyed by every factor that would
  move the content (browser mode, endpoint/profile, capture, viewport, DPR, zoom,
  monitor scale). It is never silently reused when any key changes.

Everything here is pure/O-free except the thin real providers; the CDP/Win32
calls are injected so the whole combination is unit-testable with fakes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bap.forge.cursor.geometry import WindowGeometry


# --------------------------------------------------------------------------- #
# Calibration key + persistence
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CalibrationKey:
    """Every factor that changes where the captured content sits on screen. A
    calibrated content origin is valid only for the exact key it was set under."""

    browser_mode: str
    endpoint: str            # CDP endpoint (External) or profile dir (Managed)
    capture_w: int
    capture_h: int
    viewport_w: int
    viewport_h: int
    device_pixel_ratio: float
    zoom: float
    monitor_scale: float
    monitor_id: str = ""

    def key_str(self) -> str:
        return (f"{self.browser_mode}|{self.endpoint}|cap{self.capture_w}x{self.capture_h}"
                f"|vp{self.viewport_w}x{self.viewport_h}|dpr{self.device_pixel_ratio:g}"
                f"|z{self.zoom:g}|ms{self.monitor_scale:g}|mon{self.monitor_id}")


class ContentOriginCalibration:
    """Persisted map of CalibrationKey → content rectangle (physical screen px,
    ``[left, top, right, bottom]``). Missing/changed key → not found (never reused)."""

    def __init__(self, path: Path | str | None = None, entries: dict | None = None):
        self._path = Path(path) if path is not None else None
        self._entries: dict[str, list[int]] = dict(entries or {})

    @property
    def path(self) -> Path | None:
        return self._path

    def get(self, key: CalibrationKey) -> tuple[int, int, int, int] | None:
        rect = self._entries.get(key.key_str())
        return tuple(rect) if rect is not None else None  # type: ignore[return-value]

    def set(self, key: CalibrationKey, content_rect: tuple[int, int, int, int]) -> None:
        left, top, right, bottom = (int(v) for v in content_rect)
        if right <= left or bottom <= top:
            raise ValueError("content rectangle must have positive width and height")
        self._entries[key.key_str()] = [left, top, right, bottom]
        self.save()

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "content_origins": self._entries}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    @classmethod
    def load(cls, path: Path | str) -> "ContentOriginCalibration":
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls(path=path)
        return cls(path=path, entries=dict((data or {}).get("content_origins", {})))


def default_calibration_path():
    from bap.ops.paths import ensure_dirs, get_paths

    return ensure_dirs(get_paths()).data_dir / "forge" / "content_origin_calibration.json"


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GeometryMeasurement:
    """The raw geometry read from the browser (CDP) and, when available, the native
    window. Everything the transform + staleness need except the operator-supplied
    content origin (which is merged in separately)."""

    native_window_id: str | None
    window_x: int
    window_y: int
    window_w: int
    window_h: int
    window_state: str                 # "normal" | "maximized" | "minimized" | "fullscreen"
    viewport_w: int
    viewport_h: int
    capture_w: int
    capture_h: int
    device_pixel_ratio: float
    zoom: float
    monitor_id: str
    monitor_scale: float
    windows_dpi: int | None
    content_rect: tuple[int, int, int, int] | None = None   # physical px, when measured (Win32)
    measured_at: str | None = None


def measure_via_cdp(send: Callable[[str, dict], dict], *, capture_w: int, capture_h: int,
                    monitor_scale: float = 1.0, monitor_id: str = "primary",
                    windows_dpi: int | None = None,
                    native_window_id: str | None = None) -> GeometryMeasurement:
    """Measure window + viewport via CDP. ``send(method, params) -> dict`` is the
    only I/O and is injected (fake in tests; a real CDP session in production).

    DPR is DERIVED from capture÷viewport — no ``Runtime.evaluate`` — so measurement
    stays a pure read of already-available data."""
    win = send("Browser.getWindowForTarget", {})
    window_id = win.get("windowId")
    bounds = win.get("bounds") or send("Browser.getWindowBounds", {"windowId": window_id}).get("bounds", {})
    metrics = send("Page.getLayoutMetrics", {})
    css = metrics.get("cssLayoutViewport") or metrics.get("layoutViewport") or {}
    vp_w = int(css.get("clientWidth") or capture_w)
    vp_h = int(css.get("clientHeight") or capture_h)
    visual = metrics.get("visualViewport") or {}
    zoom = float(visual.get("scale") or 1.0)
    dpr = round(capture_w / vp_w, 4) if vp_w else 1.0
    return GeometryMeasurement(
        native_window_id=native_window_id if native_window_id is not None else (
            str(window_id) if window_id is not None else None),
        window_x=int(bounds.get("left", 0)), window_y=int(bounds.get("top", 0)),
        window_w=int(bounds.get("width", 0)), window_h=int(bounds.get("height", 0)),
        window_state=str(bounds.get("windowState", "normal")),
        viewport_w=vp_w, viewport_h=vp_h, capture_w=capture_w, capture_h=capture_h,
        device_pixel_ratio=dpr, zoom=zoom, monitor_id=monitor_id, monitor_scale=monitor_scale,
        windows_dpi=windows_dpi,
        measured_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )


def resolve_native_window(cdp_bounds: tuple[int, int, int, int],
                          candidates: list[dict], *, tolerance: int = 4):
    """Uniquely associate the CDP window with a native window (Win32 fallback).

    ``candidates`` are ``{"hwnd", "rect": (x,y,w,h), "client_rect": (l,t,r,b)}``.
    Returns ``(candidate, None)`` when exactly one matches the CDP outer bounds
    within ``tolerance`` px, else ``(None, reason)`` — an ambiguous or missing match
    blocks the preview rather than guessing."""
    bx, by, bw, bh = cdp_bounds

    def matches(rect):
        x, y, w, h = rect
        return (abs(x - bx) <= tolerance and abs(y - by) <= tolerance
                and abs(w - bw) <= tolerance and abs(h - bh) <= tolerance)

    hits = [c for c in candidates if matches(c.get("rect", (0, 0, 0, 0)))]
    if not hits:
        return None, "no native window matches the CDP window bounds"
    if len(hits) > 1:
        return None, f"{len(hits)} native windows match the CDP bounds — ambiguous, cannot choose"
    return hits[0], None


def build_window_geometry(
    measurement: GeometryMeasurement,
    *,
    browser_mode: str,
    endpoint: str,
    calibration: ContentOriginCalibration | None = None,
) -> tuple[WindowGeometry | None, str]:
    """Combine a measurement with a content origin (measured Win32 client area, or
    persisted operator calibration for the exact key) into a usable WindowGeometry.

    Returns ``(geometry, source)``. When the content origin is unknown, returns
    ``(None, "content_origin_unavailable")`` so the caller blocks with a precise
    reason and offers "Set Browser Content Origin"."""
    key = CalibrationKey(
        browser_mode=browser_mode, endpoint=endpoint,
        capture_w=measurement.capture_w, capture_h=measurement.capture_h,
        viewport_w=measurement.viewport_w, viewport_h=measurement.viewport_h,
        device_pixel_ratio=measurement.device_pixel_ratio, zoom=measurement.zoom,
        monitor_scale=measurement.monitor_scale, monitor_id=measurement.monitor_id,
    )
    content_rect = measurement.content_rect
    source = "measured"
    if content_rect is None and calibration is not None:
        content_rect = calibration.get(key)
        source = "operator_calibrated"
    if content_rect is None:
        return None, "content_origin_unavailable"

    geom = WindowGeometry(
        window_x=measurement.window_x, window_y=measurement.window_y,
        window_w=measurement.window_w, window_h=measurement.window_h,
        content_offset_x=content_rect[0] - measurement.window_x,
        content_offset_y=content_rect[1] - measurement.window_y,
        device_pixel_ratio=measurement.device_pixel_ratio, zoom=measurement.zoom,
        viewport_w=measurement.viewport_w, viewport_h=measurement.viewport_h,
        capture_w=measurement.capture_w, capture_h=measurement.capture_h,
        monitor_scale=measurement.monitor_scale,
        window_id=measurement.native_window_id, monitor_id=measurement.monitor_id,
        content_rect=tuple(content_rect), source=source,
        native_window_id=measurement.native_window_id, windows_dpi=measurement.windows_dpi,
        measured_at=measurement.measured_at,
    )
    return geom, source


class WindowGeometryProvider:
    """Protocol: measure the current geometry for a mapped tab. Real providers do
    CDP/Win32 I/O; tests inject a fake that returns a canned measurement."""

    def measure(self, *, capture_w: int, capture_h: int) -> GeometryMeasurement | None:
        raise NotImplementedError


class FakeWindowGeometryProvider(WindowGeometryProvider):
    """Returns a pre-set measurement (or a sequence, to model geometry changing
    between scan and move) — for tests, no real browser."""

    def __init__(self, measurement, *, sequence: list | None = None):
        self._measurement = measurement
        self._sequence = list(sequence) if sequence else None

    def measure(self, *, capture_w: int, capture_h: int) -> GeometryMeasurement | None:
        if self._sequence:
            return self._sequence.pop(0)
        return self._measurement


__all__ = [
    "CalibrationKey",
    "ContentOriginCalibration",
    "default_calibration_path",
    "GeometryMeasurement",
    "measure_via_cdp",
    "resolve_native_window",
    "build_window_geometry",
    "WindowGeometryProvider",
    "FakeWindowGeometryProvider",
]
