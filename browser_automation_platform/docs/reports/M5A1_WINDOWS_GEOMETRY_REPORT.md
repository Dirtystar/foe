# M5A.1 — Real Windows Browser Geometry (Implementation Report)

M5A shipped the cursor-preview safety gate, coordinate contract, confirmation,
audit, and move-only adapter, but `MainWindow._window_geometry` returned `None`, so
the gate always blocked with *"window geometry unavailable"*. This milestone closes
that exact gap: it measures the real geometry of the attached Chrome/Chromium
window and its web-content viewport so the existing transform can map a raw
screenshot point to a physical screen pixel **without guessing**.

> **Clicking remains unimplemented.** Nothing in this milestone clicks, presses,
> drags, scrolls, or types. The only output remains `CursorPreviewPort.move_to`.
> The calibration overlay reads two operator clicks on **BAP's own window** and
> sends nothing to Chrome.

## Geometry source

Two evidence sources, combined deterministically in
`forge/cursor/window_geometry.py`:

1. **CDP measurement** (`measure_via_cdp`) — `Browser.getWindowForTarget` +
   `Browser.getWindowBounds` give the outer window rectangle, identity, and
   window state (normal/maximized); `Page.getLayoutMetrics` gives the CSS layout
   viewport; **DPR is derived** from capture ÷ viewport (no `Runtime.evaluate` —
   measurement stays a pure read); zoom comes from the visual viewport scale. This
   yields everything except the on-screen **content origin**, which CDP does not
   expose (Chrome draws its tab strip/toolbar inside the client area, so no CDP or
   generic Win32 call gives the web-content top-left reliably).
2. **Content origin** — resolved from the native window's client area (Win32, when
   `resolve_native_window` uniquely identifies it) or, reliably, from a one-time
   **operator calibration** (see below). The content rectangle is stored in
   **physical screen pixels**, so the transform maps by direct linear interpolation
   across it — absorbing DPR, title bar, toolbar, and monitor scale with no assumed
   constants.

`build_window_geometry` merges a measurement with the content origin and returns
`(None, "content_origin_unavailable")` when the origin is unknown, so the caller
blocks with a precise reason and offers **Set Browser Content Origin**.

## Fallback / calibration method

**Set Browser Content Origin** (`gui/cursor_calibration.py`): a translucent,
BAP-owned, full-screen overlay on which the operator clicks the **top-left** then
**bottom-right** corner of the Forge content area. The two clicks are converted to
physical pixels via each screen's device-pixel-ratio and persisted as the content
rectangle. It is keyed (`CalibrationKey`) by **browser mode, endpoint/profile,
capture size, viewport, DPR, zoom, monitor scale, and monitor** — and is **never
reused when any key changes** (`ContentOriginCalibration.get` misses on any
difference), so a different zoom/DPR/monitor forces a fresh calibration. The
overlay sends no input to Chrome and clicks nothing in the game.

## Native-window association

`resolve_native_window(cdp_bounds, candidates)` uniquely matches the CDP window to
a native window within a pixel tolerance. Exactly one match → that window; **zero
or more than one → block** with the exact reason (never "first matching title" or
process-name guess).

## Transformation example (real numbers)

Operator calibrates the Forge content area at **125 % Windows scaling** on the
primary monitor; the capture is 1000×750 device px; the operator marks the content
rectangle at physical `(200, 100)`–`(1200, 850)`:

```
content_rect = (200, 100, 1200, 850)   # physical px, 1000×750
badge at raw image (500, 375)          # centre of the capture
fx = 500/1000 = 0.5   fy = 375/750 = 0.5
screen_x = 200 + 0.5 × (1200−200) = 700
screen_y = 100 + 0.5 × (850−100)  = 475
→ move_to(700, 475)   # physical screen px; 125 % scaling absorbed by the rect
```

A window on a **second monitor to the left** with content rect
`(-1920, -100, -920, 700)` maps the same raw point to `(-1420, 300)` — negative
coordinates preserved.

## Staleness rules

At scan time the complete `WindowGeometry` (including `content_rect`, window rect,
DPR, zoom, viewport, capture, monitor scale, and native window id) is stored.
Immediately before moving, the geometry is **re-read** and its `identity()`
compared. Any change to the native window id, outer position/size, content rect,
viewport, DPR, zoom, or monitor scale **invalidates the target** →
`geometry_changed` → *"run Test Scan again"*. A re-measurement that returns nothing
→ `no_geometry`. The move never proceeds on stale geometry.

## External Chrome lifecycle (preserved)

BAP never launches Chrome in External mode, never closes it, only reads geometry
and moves the OS cursor after manual confirmation, and disconnect/exit never move
the cursor. Geometry measurement is read-only CDP + a read of the operator's own
clicks.

## Tests

`QT_QPA_PLATFORM=offscreen pytest` — **72 cursor tests pass** (M5A 47 + M5A.1 25):

- `test_window_geometry.py` (14) — CDP measurement + derived DPR + maximized state;
  calibration persistence + invalidation on every key change + degenerate-rect
  rejection; `build_window_geometry` blocks without origin / uses calibration;
  native-window association (unique / ambiguous / missing); calibrated transform at
  **100 %/125 %/150 %**, second monitor, and negative coordinates.
- `test_geometry_move.py` (8) — one valid calibrated request reaches `move_to`
  exactly once (External **and** Managed); window moved / resized / viewport /
  DPR / zoom change after scan each block; lost geometry blocks; the confirmation
  fields expose the geometry diagnostics.
- `test_cursor_geometry_ui.py` (3) — the debugger's Set-Content-Origin action runs
  calibration; MainWindow builds a calibrated `WindowGeometry` from the persisted
  origin; a changed key invalidates it.
- Plus the M5A suite (47) and the Vision Debugger suite (10) still pass. The full
  non-GUI unit suite result is recorded with the commit.

Injectable fake CDP (`send`) and fake geometry providers keep the suite
Chrome-free. **No real Chrome window** exists in this headless Linux container, so
the live CDP/Win32 measurement path and the calibration overlay were **not**
exercised against a real browser — see limitations.

## Real Windows checklist

1. Start External Chrome and attach BAP.
2. Open one Forge World with one obvious badge.
3. Run Test Scan; confirm the annotated Would-Click marker.
4. In the Vision Debugger, **Set Browser Content Origin** → click the top-left and
   bottom-right of the Forge content area once (saved for this setup).
5. Inspect the measured Browser and Content rectangles in the confirmation dialog.
6. Enable Cursor Preview → **Preview Cursor Target** → review coordinates.
7. Confirm **Move Cursor**; verify the cursor lands on the badge.
8. Verify **no click** occurs.
9. Move Chrome by 100 px and try again with the same scan — it must be **rejected**
   (window moved).
10. Re-scan and confirm again.
11. Repeat on a second monitor and at 125 % scaling if available (re-calibrate —
    the key changed).

## Limitations

- **Live CDP/Win32 measurement is integration-only and unverified here.**
  `measure_via_cdp` (the parser) is unit-tested with a fake `send`, but the
  RuntimeService→CDP session plumbing that feeds it a real browser was not run in
  this container. The **operator content-origin calibration is the reliable,
  tested content-origin path** and is what makes the feature functional on Windows.
- **Window-move staleness needs re-measurement.** In the current wiring the
  geometry is rebuilt from the persisted calibration, which detects viewport / DPR /
  zoom / key changes but not a pure window drag without a live re-measurement.
  Wiring the CDP/Win32 re-measurement into the move-time getter is the natural next
  step; the staleness *logic* (identity comparison, including window rect and
  content rect) is complete and tested.
- **Overlay placement is best-effort across DPI.** The calibration overlay converts
  logical clicks to physical pixels via per-screen DPR; on exotic per-monitor DPI
  layouts this is approximate — but because the operator marks the *actual* content
  corners, the resulting rectangle is measured, not assumed. A live desktop
  **target overlay** (drawing a marker at the computed point) was intentionally
  **omitted**: placing a Qt top-level at an absolute physical point is subject to
  the same scaling the feature is validating, so a mis-placed marker would mislead;
  the confirmation-dialog coordinates + the after-move actual-cursor delta are the
  verification instead.

## Explicit statement

**Clicking remains unimplemented.** No code path performs a click; the single
output action is a manual, confirmed, one-shot cursor *move*.
