"""FoE-Helper-free map calibration and province ordering — the core of dropping the extension.

Two pure, testable helpers plus one live driver:

- :func:`probe_points` — a spread of on-screen points to click, centre-out, avoiding the edges and
  the right-hand UI strip. The live driver clicks these; each that lands on a sector opens a
  province window whose ``getArmyPreview.provinceId`` tells us *which* one — a calibration sample
  with no FoE Helper marker needed.
- :func:`centrality` — rank provinces by distance from the map centroid, replacing the
  Helper-name-based centre-ring priority (central sectors first) straight from ``map/data`` flags.
- :func:`native_solve` — the live glue: probe, collect (id, screen) samples via the existing
  ``CalibrationCollector``, and fit the transform with ``solve_uniform``. ``no-cover``.

See ``docs/DEHELPER_PLAN.md``.
"""

from __future__ import annotations

import time


def probe_points(vw: int, vh: int, *, cols: int = 5, rows: int = 4, margin: int = 110,
                 right_ui: int = 120, bottom_ui: int = 90) -> list[tuple[int, int]]:
    """A grid of click points across the map area, ordered centre-outward.

    Keeps clear of the window edges (``margin``), the right-hand game toolbar (``right_ui``) and
    the bottom bar (``bottom_ui``). Centre-out ordering hits the dense central sectors first (more
    likely to open a province, and well spread for a stable fit)."""
    x0, x1 = margin, max(margin + 1, vw - right_ui - margin)
    y0, y1 = margin, max(margin + 1, vh - bottom_ui - margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pts = []
    for r in range(rows):
        fy = 0.5 if rows == 1 else r / (rows - 1)
        for c in range(cols):
            fx = 0.5 if cols == 1 else c / (cols - 1)
            pts.append((int(x0 + fx * (x1 - x0)), int(y0 + fy * (y1 - y0))))
    pts.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)   # centre first
    # de-dup while keeping order
    seen, out = set(), []
    for p in pts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def centrality(flags: dict) -> dict:
    """Map ``{province_id: (x, y)}`` → ``{province_id: distance_from_centroid}``. Lower = more
    central = fight first. Replaces the FoE-Helper name-based ring (A1/B1 before …4)."""
    pts = [(pid, xy) for pid, xy in (flags or {}).items() if xy is not None]
    if not pts:
        return {}
    cx = sum(xy[0] for _, xy in pts) / len(pts)
    cy = sum(xy[1] for _, xy in pts) / len(pts)
    return {pid: ((xy[0] - cx) ** 2 + (xy[1] - cy) ** 2) ** 0.5 for pid, xy in pts}


def native_solve(page, layout, latest, hover_click, escape, vw, vh, *,
                 need=3, per_wait=2.2, min_samples=2):  # pragma: no cover - live
    """Calibrate the map→screen transform WITHOUT FoE Helper: click probe points, read which
    province each opens (``latest['pid']``), and fit ``solve_uniform``. Returns a MapTransform or
    None. ``hover_click(page,x,y)`` and ``escape(page)`` are the caller's live primitives."""
    from bap.forge.gbg_data.calibration import CalibrationCollector, residual, solve_uniform

    collector = CalibrationCollector(need=need)
    for (x, y) in probe_points(vw, vh):
        latest["pid"] = None
        hover_click(page, x, y)
        collector.on_click(x, y)
        deadline = time.time() + per_wait
        while latest["pid"] is None and time.time() < deadline:
            page.wait_for_timeout(120)
        pid = latest["pid"]
        if pid is not None and layout.flag(int(pid)) is not None:
            collector.on_province(pid)
            print(f"[native-calib] point ({x},{y}) → province {pid}", flush=True)
        escape(page)                                   # close the province window before the next
        # need ≥2 samples AND some spread on both axes for a stable solve
        if len(collector.samples) >= max(min_samples, 2):
            xs = {s.screen[0] for s in collector.samples}
            ys = {s.screen[1] for s in collector.samples}
            if len(xs) >= 2 and len(ys) >= 2 and collector.done:
                break
    if len(collector.samples) < min_samples:
        print(f"[native-calib] only {len(collector.samples)} samples — cannot solve "
              "(are we on the GBG map with open sectors?).", flush=True)
        return None
    try:
        t = solve_uniform(layout, collector.samples)
    except ValueError as exc:
        print(f"[native-calib] solve failed: {exc}", flush=True)
        return None
    print(f"[native-calib] solved from {len(collector.samples)} clicks: scale={t.scale_x:.4f} "
          f"offset=({t.off_x:.0f},{t.off_y:.0f}) residual={residual(layout, t, collector.samples):.1f}px",
          flush=True)
    return t


__all__ = ["probe_points", "centrality", "native_solve"]
