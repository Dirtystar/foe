"""Panel Click Point Calibration (Milestone 6A.1) — **measurement only, no action**.

Lets the operator *teach* BAP where the next action button sits inside an opened
province/detail panel, by clicking the intended point once on several real panels
(across Worlds / window positions / resolutions). It stores each sample with full
context and computes the **normalized** position of the click inside the panel
rectangle, then reports the variance across samples.

Acceptance: if the normalized point is stable across samples it is marked
**VERIFIED** (a fixed relative point can be used later); if it drifts materially, it
is **not** verified and the reason is reported. This tool **never clicks the action**
— it only records where a future click *would* go, and (via the GUI overlay) draws
that predicted point on newly opened panels. The actual action click is a later
milestone and is out of scope here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: A normalized-coordinate std at or below this (fraction of the panel dimension) is
#: considered stable enough to use a fixed relative point.
NORM_STD_THRESHOLD = 0.02
#: Minimum samples before a VERIFIED verdict is meaningful.
MIN_SAMPLES_FOR_VERDICT = 3


@dataclass(frozen=True)
class PanelClickSample:
    """One operator-marked future-action point inside an opened panel."""

    screen_point: tuple[int, int]        # absolute physical screen pixel
    panel_rect: tuple[int, int, int, int]  # x, y, w, h (screen px)
    viewport: tuple[int, int]            # CSS viewport w, h
    resolution: tuple[int, int]          # capture w, h
    dpr: float
    zoom: float
    browser_mode: str | None
    world: str | None
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def normalized(self) -> tuple[float, float]:
        """Click position as a fraction of the panel rectangle (0..1)."""
        x, y, w, h = self.panel_rect
        sx, sy = self.screen_point
        nx = (sx - x) / w if w else 0.0
        ny = (sy - y) / h if h else 0.0
        return (nx, ny)

    def to_dict(self) -> dict:
        d = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(self).items()}
        d["normalized"] = list(self.normalized)
        return d


@dataclass(frozen=True)
class CalibrationVerdict:
    verified: bool
    reason: str
    samples: int
    mean_normalized: tuple[float, float] | None
    std_normalized: tuple[float, float] | None

    def to_dict(self) -> dict:
        return {
            "verified": self.verified, "reason": self.reason, "samples": self.samples,
            "mean_normalized": list(self.mean_normalized) if self.mean_normalized else None,
            "std_normalized": list(self.std_normalized) if self.std_normalized else None,
        }


def _mean_std(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / n
    return (m, var ** 0.5)


def analyze(samples: list[PanelClickSample], *,
            std_threshold: float = NORM_STD_THRESHOLD,
            min_samples: int = MIN_SAMPLES_FOR_VERDICT) -> CalibrationVerdict:
    """VERIFIED iff enough samples agree on a normalized point (std ≤ threshold on
    both axes); otherwise not verified, with the reason."""
    n = len(samples)
    if n == 0:
        return CalibrationVerdict(False, "No samples collected yet.", 0, None, None)
    nxs = [s.normalized[0] for s in samples]
    nys = [s.normalized[1] for s in samples]
    mx, sx = _mean_std(nxs)
    my, sy = _mean_std(nys)
    mean, std = (mx, my), (sx, sy)
    if n < min_samples:
        return CalibrationVerdict(
            False, f"Need ≥ {min_samples} samples on different Worlds/positions "
                   f"(have {n}) before a fixed point can be trusted.", n, mean, std)
    if sx <= std_threshold and sy <= std_threshold:
        return CalibrationVerdict(
            True, f"Stable across {n} samples (std x={sx:.3f}, y={sy:.3f} ≤ "
                  f"{std_threshold:.3f}). A fixed relative point is safe to use.", n, mean, std)
    return CalibrationVerdict(
        False, f"Drifts across samples (std x={sx:.3f}, y={sy:.3f} > {std_threshold:.3f}) "
               "— do NOT use a fixed point; the button is not at an invariant relative "
               "position across these conditions.", n, mean, std)


def predict_point(panel_rect: tuple[int, int, int, int],
                  mean_normalized: tuple[float, float]) -> tuple[int, int]:
    """Absolute screen point a verified normalized position maps to for a given
    panel rectangle (used by the overlay to draw the predicted future-click point)."""
    x, y, w, h = panel_rect
    nx, ny = mean_normalized
    return (int(round(x + nx * w)), int(round(y + ny * h)))


class PanelClickCalibrationStore:
    """Persistent store of calibration samples + on-demand analysis. No action ever."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._samples: list[PanelClickSample] = []
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def samples(self) -> list[PanelClickSample]:
        return list(self._samples)

    def add(self, sample: PanelClickSample) -> None:
        self._samples.append(sample)
        self._save()

    def clear(self) -> None:
        self._samples = []
        self._save()

    def analyze(self, **kw) -> CalibrationVerdict:
        return analyze(self._samples, **kw)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for r in raw.get("samples", []):
            try:
                self._samples.append(PanelClickSample(
                    screen_point=tuple(r["screen_point"]),
                    panel_rect=tuple(r["panel_rect"]),
                    viewport=tuple(r["viewport"]),
                    resolution=tuple(r["resolution"]),
                    dpr=float(r["dpr"]), zoom=float(r["zoom"]),
                    browser_mode=r.get("browser_mode"), world=r.get("world"),
                    recorded_at=r.get("recorded_at", ""),
                ))
            except Exception:
                continue

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"samples": [s.to_dict() for s in self._samples],
                   "verdict": self.analyze().to_dict()}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)


def draw_prediction(image_bgr, panel_rect, mean_normalized, *, verified: bool):
    """Return a copy of ``image_bgr`` with the predicted future-click point drawn as
    a crosshair (green when VERIFIED, amber otherwise). Pure/observational — this
    never performs a click. ``panel_rect``/``mean_normalized`` are in image pixels."""
    try:
        import cv2
    except Exception:  # pragma: no cover
        return image_bgr
    if image_bgr is None or mean_normalized is None:
        return image_bgr
    out = image_bgr.copy()
    px, py = predict_point(panel_rect, mean_normalized)
    color = (60, 170, 60) if verified else (40, 170, 220)  # BGR: green / amber
    cv2.drawMarker(out, (px, py), color, markerType=cv2.MARKER_CROSS,
                   markerSize=26, thickness=2)
    cv2.circle(out, (px, py), 14, color, 2)
    label = "predicted next-button (VERIFIED)" if verified else "predicted next-button (unverified)"
    cv2.putText(out, label, (px + 18, py - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                cv2.LINE_AA)
    return out


def default_calibration_path():
    """Per-user calibration store (``<data>/forge/panel_click_calibration.json``)."""
    from bap.ops.paths import ensure_dirs, get_paths

    return ensure_dirs(get_paths()).data_dir / "forge" / "panel_click_calibration.json"


__all__ = [
    "PanelClickSample", "CalibrationVerdict", "PanelClickCalibrationStore",
    "analyze", "predict_point", "draw_prediction", "default_calibration_path",
    "NORM_STD_THRESHOLD", "MIN_SAMPLES_FOR_VERDICT",
]
