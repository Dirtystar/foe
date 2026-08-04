# M5A — Manual Move Cursor Preview (Implementation Report)

The first real **output** action in the product: on an explicit operator
confirmation, the OS cursor moves **once** to the validated would-click point.

> **Clicking is not implemented.** There is no click, double-click, mouse-down,
> mouse-up, drag, scroll, or keyboard method anywhere in this milestone. The only
> output operation that exists is `CursorPreviewPort.move_to(screen_x, screen_y)`,
> and it changes cursor position only — it cannot press a button. This is a
> coordinate-contract and safety-validation milestone, not gameplay automation.

## Safety model

Movement is impossible unless **every** condition below holds, checked in a
fixed, safety-first order; the first failure returns the exact blocking reason and
**no** coordinate is guessed (`forge/cursor/preview.py`):

1. Cursor Preview explicitly **enabled for this session** (disabled by default).
2. A known **owned/attached** browser window (Managed Chromium or External Chrome).
3. The target comes from a **fresh live** Test Scan (never an offline image).
4. The **selected World is unchanged** and still mapped to the **same tab**.
5. A **target badge** exists.
6. Its **percentage is confidently classified** (UNKNOWN — below the acceptance
   bar — blocks; the wrong-accepted gate is unchanged).
7. The **weakening decision is CONTINUE** (STOP/UNKNOWN block).
8. The target lies **inside the current viewport**.
9. The scan is **not stale** (≤ the max age, default 5 s).
10. **Window geometry is available**.
11. **Window geometry is unchanged** since the scan (position/size/DPR/zoom/viewport).

Two-step confirmation: pressing **Preview Cursor Target** evaluates the gate and,
only on success, shows a dialog listing World/hostname, %, confidence, weakening,
limit, image/viewport/screen points, and scan age, plus the literal text *"The
cursor will move once. No click will be performed."* **Cancel is the default and
Escape cancels**; there is no Enter-to-move and no keyboard shortcut. On **Move
Cursor**, the gate is **re-evaluated with a fresh clock** (so a scan that expired,
or a World switched, while the dialog was open is caught), then the cursor moves
**exactly once**. No queue, no retry-that-moves-again, no background repetition.

Emergency safety: disabled by default and **never persisted**, so it resets to
disabled on every app launch; enable is session-only; movement executes at most
once per confirmation. Scan All, the scheduler, offline review, and app exit have
no path to movement (they construct the debugger without a cursor controller, or
never call it).

## Coordinate transformation (`forge/cursor/geometry.py`)

One explicit transform, image → screen, with every factor applied exactly once and
every stage recorded in a `CoordinateTrace`:

```
raw image px
  → viewport CSS px      : × (viewport/capture) per axis (folds DPR + any rescale), applied once
  → content CSS px       : + scroll offset (Forge canvas = 0)
  → screen logical px    : + window origin + content-area offset (frame/title/toolbar)
  → screen physical px   : × monitor_scale (Windows display scaling), applied once; sign preserved
```

CSS pixels and device pixels are never mixed silently; the browser content is not
assumed to start at screen (0,0); negative screen coordinates (a monitor left of /
above the primary) are preserved. Zoom and DPR are recorded and required to match
between scan and move (they change *where a point lands*), but are not multiplied
in twice — the surface already reflects them. Verified by unit tests at 100 % and
125 % scaling, two monitors, negative origins, DPR, and capture≠viewport.

`WindowGeometry` carries the window position/size, content offset, DPR, zoom,
viewport, capture size, monitor scale, scroll, and a window/monitor identity used
for staleness detection.

## Freshness policy

A preview may use only a scan newer than `max_age_s` (default **5 s**, configurable
per request). Older → blocked with *"Target expired — run Test Scan again"*. The
app never silently rescans and moves.

## Adapter boundary

- `forge/cursor/port.py` — `CursorPreviewPort` with the single method `move_to`.
  A `FORBIDDEN_INPUT_METHODS` list is asserted absent by tests, so a future edit
  that adds click/keyboard fails loudly.
- `adapters/cursor/fake_cursor.py` — records moves; used by all normal tests.
- `adapters/cursor/os_cursor.py` — `WindowsCursorPreview`, Win32 `SetCursorPos`
  (movement only; DPI-aware so it takes physical pixels). Unavailable off Windows —
  the app reports the preview as unavailable rather than guessing.

Deliberately **separate from the generic action engine** (`ActionHandlerPort`): the
Forge product gains no general-purpose input API.

## Audit format (`forge/cursor/audit.py`)

Append-only JSONL at `<data>/forge/cursor_preview_audit.jsonl`. Every move (and
every blocked attempt at move time) writes one line:
`event = "CURSOR_PREVIEW_ONLY"`, `no_click = true`, timestamps, scan age, World /
hostname / browser mode, target %/confidence, weakening value/decision, the full
coordinate trace, window geometry, requested screen point, operator confirmation,
and the movement result. Only Forge-tab context is recorded — never other tabs.

## Test results

`QT_QPA_PLATFORM=offscreen pytest` on the container:

- `tests/unit/forge/cursor/test_coordinate_contract.py` — 9 (100 %/125 %, two
  monitors, negative coords, DPR, capture≠viewport, bounds, trace).
- `tests/unit/forge/cursor/test_preview_gate.py` — 20 (every blocking condition +
  happy path + geometry/DPR/zoom drift + Managed accepted).
- `tests/unit/forge/cursor/test_controller.py` — 8 (disabled by default; fresh
  controller re-disabled; confirm required; one move; blocked never moves; World
  switched at move time; audit CURSOR_PREVIEW_ONLY; blocked audited; cancel no
  audit/no move).
- `tests/unit/adapters/cursor/test_cursor_adapters.py` — 4 (fake records; no
  click/keyboard surface; Windows class has no forbidden methods; unavailable off
  Windows).
- `tests/unit/gui/test_cursor_preview_ui.py` — 6 (unavailable without controller;
  disabled→enable; confirmed valid moves once + NO CLICK; cancel no move; blocked
  shows reason; enable required).

**47 cursor tests pass**; the existing Vision Debugger tests (10) still pass. The
full unit suite result is recorded with the commit.

## Real Windows cursor verification

**Not performed** — this is a headless Linux container with no cursor/display and
no operator Chrome, so no real cursor movement was or could be exercised (the
Windows adapter is correctly *unavailable* here). The normal suite proves the gate,
transform, audit, and one-shot semantics with fakes. Operator checklist:

1. Attach External Chrome (M4.16).
2. Open one Forge World with one obvious badge.
3. Run Test Scan; confirm the selected badge and Would-Click marker visually.
4. Enable Cursor Preview for this session.
5. Press **Preview Cursor Target**; review every coordinate in the dialog.
6. Confirm **Move Cursor**.
7. Verify the cursor lands on the badge; verify **no click** occurs.
8. Move the browser to another screen position → the stale-geometry gate must
   reject until you re-scan.
9. Resize the browser → the stale-scan / stale-geometry gate must reject.
10. Repeat under Managed Chromium.

## Known limitations

- **Live window-geometry acquisition is not automated.** Accurate `WindowGeometry`
  (OS window position, content-area offset, DPR, zoom, monitor scale) is an
  OS-level fact not available in this environment, and CDP does not expose the
  content-area offset. `MainWindow._window_geometry` returns `None` by default, so
  the gate **safely refuses to move** ("window geometry unavailable") until a
  measured/calibrated geometry is supplied on Windows. Wiring a Windows geometry
  provider is the natural M5A follow-up; the transform + gate + audit are complete
  and tested.
- viewport/DPR/zoom flow through when known; when unknown the transform falls back
  to 1/DPR and the gate blocks on missing geometry.
- Real cursor movement is Windows-only (Win32 `SetCursorPos`).

## Explicit statement

**Clicking is not implemented in this milestone, and no code path performs a
click.** The single output action is a manual, confirmed, one-shot cursor *move*.
