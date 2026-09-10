# M6A.1 — Manual Open & Verify: implementation report

_The first real click. One operator-confirmed left click on the validated map badge,
used to open the province/detail panel for an **independent** second reading of the
percentage, then **STOP**. No battle loop, scheduler, retry, repeated clicking, or
unattended behaviour — none of those are implemented or reachable._

Built on the approved M6 design (`docs/design/M6_AUTONOMOUS_CLICKING_DESIGN.md`),
reusing the M5A safety spine verbatim. No detector / classifier / OCR / threshold /
weakening / cursor-movement code was modified.

---

## 1. What was implemented

### New, self-contained package `bap.forge.click`
| File | Responsibility |
|---|---|
| `port.py` | `ClickPort` — the narrow single-click boundary (`click_at` only) + `FORBIDDEN_INPUT_METHODS`. Separate sibling of the movement-only cursor port. |
| `constants.py` | `MAX_CLICK_AGE_S=2.0`, `PANEL_WAIT_TIMEOUT_S=3.0`, `PANEL_POLL_INTERVAL_S=0.25`, `CURSOR_TOLERANCE_PX=3`. |
| `audit.py` | `ClickAudit` — append-only JSONL, **fail-closed** `record_or_raise` for the pre-click intent. Events below. |
| `panel_reader.py` | `PanelReader` — the independent, fail-closed panel percentage reader. |
| `open_verify.py` | `OpenAndVerifyController` — the gated one-click Open & Verify flow. |
| `panel_calibration.py` | `PanelClickCalibrationStore` + `analyze`/`predict_point`/`draw_prediction` — measurement-only next-button calibration. |

### New input adapters `bap.adapters.input`
| File | Responsibility |
|---|---|
| `fake_click.py` | `FakeClick` — records clicks, touches nothing (default in all tests). |
| `os_click.py` | `WindowsSingleClick` — real Win32 `SendInput` single left click; DPI-aware; raises off Windows. |

### GUI (Vision Debugger)
A separate, warning-styled **Open Target & Verify** section: `Enable clicking for
this session` → `Open Target & Verify` (one gated, confirmed click) → status lines
showing MAP vs PANEL and the verdict. Plus a **Calibrate Next-Button Point…** button
(measurement only). Wired in `main_window` via `_open_verify_controller()` and
`_panel_calibration_store()` (session-scoped, **disabled by default, never
persisted**, unavailable off Windows).

---

## 2. The click flow (exactly one click, then STOP)

```
fresh live scan → select one valid target
  → evaluate_preview (the 11 M5A gates, fresh clock)
  → tighter click-age bound (≤ 2.0 s)   [expired_click]
  → operator confirms (explicit dialog; Cancel is default, Esc cancels)
  → CLICK_ARMED written (fail-closed; no trail ⇒ no click)
  → cursor.move_to(screen_point)         [reuses M5A move]
  → verify cursor is on target (≤ 3 px)  [cursor_moved]
  → click_at(screen_point)  ← the ONE left click → CLICK_EXECUTED (click=true)
  → wait ≤ 3 s for the province panel (poll, re-capture)  [PANEL_TIMEOUT ⇒ STOP]
  → PANEL_DETECTED → read the panel INDEPENDENTLY
  → compare MAP pct vs PANEL pct
       match   → PANEL_VERIFY_MATCH    → STOPPED, verification complete
       differ  → PANEL_VERIFY_MISMATCH → hard STOP
       unknown → PANEL_VERIFY_UNKNOWN  → hard STOP
  → STOP. No further click, ever.
```

`ClickPort.click_at` is called from exactly one place in the code, reached only
after every gate passes and the operator confirmed. There is no loop, retry, or
second-click path. Any gate failure blocks with a specific code and performs **no**
click.

---

## 3. Exact `ClickPort` implementation

**Boundary** (`bap/forge/click/port.py`):
```python
@runtime_checkable
class ClickPort(Protocol):
    def click_at(self, screen_x: int, screen_y: int) -> None: ...
FORBIDDEN_INPUT_METHODS = ("double_click","right_click","middle_click","mouse_down",
    "mouse_up","press","release","hold","drag","scroll","type","type_text",
    "key_down","key_up","send_keys")
```
It is a **separate sibling** of `CursorPreviewPort`; no click method was added to the
cursor port (a test asserts `FakeCursorPreview` has no `click_at`).

**Real adapter** (`bap/adapters/input/os_click.py`, `WindowsSingleClick`): Win32
`SendInput` — one absolute `MOUSEEVENTF_MOVE|ABSOLUTE` to the physical target pixel,
then `LEFTDOWN`, then `LEFTUP`. Process-DPI-aware (matches the cursor adapter) so the
coordinates are physical pixels from the same `image_to_screen` contract. Constructed
off Windows it raises `OsClickUnavailable`, so the GUI shows Open & Verify as
unavailable rather than clicking. It exposes **only** `click_at` (+ a read-only
`current_position`); none of `FORBIDDEN_INPUT_METHODS` exist (asserted).

**Test double** (`FakeClick`): records `click_at` calls in `.clicks`; the "at most one
click" guarantee is asserted directly via `.count`.

---

## 4. Panel-reader method (independent of the map result)

`bap/forge/click/panel_reader.py::PanelReader.read(image)` returns a `PanelReading`
`(ok, pct, confidence, color_group, reason, pill_center, crop_bgr)`. It is
independent of the map classification in two concrete ways:

1. **Different pixels.** It reads the panel's fixed weakening pill
   (`PANEL_PILL_CENTER = (1469, 773)`, scaled to the capture resolution), not the map
   badge. It never receives the map pct as input — it re-observes and re-classifies.
2. **A signal the map path never uses.** The map classifier is an OCR-free
   *grayscale* crop-cosine. This reader adds an independent **HSV colour-group** check
   (`blue → {20,40}`, `green → {60}`, `red → {80,100}`). Colour cannot split 20 from
   40 (both blue) — only the value does — but colour **catches a gross family error**
   (e.g. a map "20" whose panel pill is red → blocked).

**Fail-closed.** `ok=False` (a hard STOP) whenever: the percentage bank is empty, the
pill is off-frame, the class is UNKNOWN, similarity `< MIN_PCT_SIM (0.70)`,
unconfirmed, or the colour contradicts the read value. **Classes are never
collapsed**: 80 and 100 (and 20 and 40) are reported distinctly.

The percentage *technique/bank* is injected (the app's existing `PercentClassifier`),
so a future dedicated **panel-exemplar bank / digit reader** — the strongest 20↔40
barrier — can replace it without touching the controller. That data is what today's
diagnostics + calibration begin collecting (see §7).

> **Honesty note on the 20↔40 barrier.** Today the panel read shares the map's cosine
> *technique/bank*, so it is a genuine *second observation with an added colour gate*,
> not yet a fully independent digit reader. Where it cannot confirm the exact value it
> **fails closed to UNKNOWN → STOP**, which is safe. Making it a hard 20↔40 barrier
> needs real panel exemplars, which this milestone is built to collect.

---

## 5. Audit events (append-only `<data>/forge/click_audit.jsonl`)

`CLICK_ARMED` (fail-closed, pre-click intent) · `CLICK_EXECUTED` (`click=true`) ·
`CLICK_BLOCKED` (gate failures) · `PANEL_DETECTED` · `PANEL_VERIFY_MATCH` ·
`PANEL_VERIFY_MISMATCH` · `PANEL_VERIFY_UNKNOWN`. Diagnostics (when a diagnostics dir
is set) save per run: `before_click.png`, `after_click.png`, `panel_crop.png`, and
`result.json` (map prediction, panel prediction, click point, state, timing).

---

## 6. Tests

`tests/unit/forge/click/` (35) + `tests/unit/gui/test_open_verify_ui.py` (3) — **38
new, all green** — using `FakeClick` and synthetic frames:

- **exactly one click maximum** (`.count == 1` on success; `== 0` on every block).
- **no click without manual confirmation** (`confirmed=False` ⇒ 0 clicks).
- **no click when disabled** (session flag off ⇒ blocked, 0 clicks).
- **panel timeout stops** (panel never opens ⇒ `PANEL_TIMEOUT`, 1 click, no retry).
- **panel UNKNOWN stops** (`PANEL_VERIFY_UNKNOWN`).
- **map/panel mismatch stops** (`PANEL_VERIFY_MISMATCH`).
- **map/panel exact match succeeds** (`PANEL_VERIFY_MATCH`, exactly one click).
- **20 map / 40 panel blocks** (the flagship product-safety case ⇒ mismatch STOP).
- **tab/window/geometry/weakening/pct changes block** before any click.
- **click age tighter than the move bar** (3 s old ⇒ `expired_click`).
- **cursor not on target blocks** (`cursor_moved`, 0 clicks).
- **fail-closed audit** (arm write fails ⇒ `audit_unavailable`, 0 clicks).
- **no automatic retry / no second click reachable** (no `retry`/`loop`/`battle`
  method; a single invocation never clicks twice, even on a mismatch).
- **port shape** (only `click_at`; cursor port still has no `click_at`).
- **panel reader** (empty bank / low-sim / unconfirmed / colour-contradiction all
  UNKNOWN; classes not collapsed).
- **calibration** (normalized coords, VERIFIED only when stable across ≥3 samples,
  drift reported, predict round-trips, persistence).
- **GUI** (section unavailable/disabled by default; enable makes the button
  available; no auto-battle control present).

Full unit suite: see the commit (run with `QT_QPA_PLATFORM=offscreen … pytest
tests/unit`).

---

## 7. Future fixed click points — measured only (no clicking)

**Known fixed anchor (already in the codebase):** the province-panel weakening pill is
modelled at `PANEL_PILL_CENTER = (1469, 773)` for a 1920×1080 capture (scaled by
resolution in `panel_reader.scaled_pill_center`). This is the panel-open anchor the
verification reads.

**Next action buttons (attack / start):** candidate fixed coordinates are **not yet
measured** — no province-panel screenshot is committed to the repo, so proposing
absolute pixels now would be a guess. Instead this milestone ships the **mechanism** to
measure them safely: the **Panel Click Point Calibration** tool records, per sample,
the absolute screen point, the panel/content rectangle, the **normalized (x, y)**
inside it, the viewport, resolution, DPR, zoom, browser mode, and World; then reports
the cross-sample variance and marks the point **VERIFIED** only if the normalized
position is stable (std ≤ 0.02 on both axes across ≥ 3 samples on different
Worlds/positions), else **not verified** with the reason. `predict_point` +
`draw_prediction` overlay the predicted point on newly opened panels. **No action
button is ever clicked.** Populating this across today's live worlds is exactly the
input the next milestone needs.

---

## 8. Was a real Windows test possible?

**Not in this environment.** The build ran on headless Linux with **no attached
Chrome and no Windows**; the real click adapter (`WindowsSingleClick`, `SendInput`)
and the cursor adapter are Windows-only and were **not** exercised here — off Windows
they raise and the GUI shows Open & Verify as *unavailable*. Everything else — the
gate, the single-click guarantee, the panel reader, the compare/STOP logic, the audit,
and the calibration analysis — is Qt-free and fully unit-tested with fakes, and the
GUI wiring is smoke-tested offscreen. The live path must be validated on the operator's
Windows machine using the checklist below.

---

## Windows live-test checklist (today)

Pre: dedicated Chrome (external attach), geometry **calibrated** (Set Browser Content
Origin), Vision Debugger open on a **fresh live scan**, **Enable clicking for this
session**.

1. Find one obvious badge; run a **fresh** Test Scan.
2. Confirm the annotated target (cyan cross) is the intended badge, at the expected %.
3. Click **Open Target & Verify**; read the confirmation dialog (World, MAP %, screen
   point, scan age).
4. Confirm **Click Once & Verify**. Watch: the cursor moves to the badge, **one** left
   click fires (the province panel opens).
5. Confirm the **correct** panel opened for that sector.
6. Read the status: **MAP: X%** vs **PANEL: Y%** and the verdict
   (MATCH ✅ / MISMATCH ⛔ / UNKNOWN ⛔ / panel-timeout).
7. Confirm **no additional click** happens — the flow STOPS after the read.
8. Repeat on **2–3 different percentages** if available (ideally a 20% and a 40% to
   exercise the safety pair; expect UNKNOWN→STOP until the panel bank is seeded).
9. Check `click_audit.jsonl`: `CLICK_ARMED` → `CLICK_EXECUTED (click=true)` →
   `PANEL_DETECTED` → one `PANEL_VERIFY_*` per run; and the diagnostics run folder has
   before/after/panel-crop + `result.json`.
10. (Optional) On an open panel, use **Calibrate Next-Button Point…** on a few
    Worlds/positions to start the next-button variance data.

---

## Stop conditions (abort immediately if any occur)

- A click is emitted while any gate should have blocked it (gate escaped).
- `FakeClick`/`WindowsSingleClick` records **> 1** click for a single confirmed run.
- A click fires **without** a preceding `CLICK_ARMED` record, or while clicking is
  disabled, or after app relaunch (persistence leak).
- The cursor is **not** on the target but a click still fires.
- A MISMATCH or UNKNOWN is followed by **any** further click.
- Any loop, retry, scheduler, or second click occurs without a fresh operator confirm.
- The panel opens for the **wrong** sector but verification reports MATCH.
→ Disable clicking, revert to observe-only, file a regression; do **not** proceed.

---

## Explicitly deferred (NOT in M6A.1)

Battle execution, any second/subsequent click, automatic retries, scheduler, loops,
multi-step battle flow, unattended behaviour, and clicking the next action button
(the calibration tool only **measures** its position). These remain gated behind later
milestones and their own safety reviews.
