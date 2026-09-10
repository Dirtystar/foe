# Milestone — CDP-targeted clicking (Phase 2, the "hand")

_Explicitly authorised action layer. The data brain (Phase 1) decides **what/when**; this
adds **where → act**: a click dispatched **into the Forge tab over CDP**, at a viewport
coordinate, that does **not** move the real mouse and does **not** need the window
foregrounded. It replaces the OS autoclicker (`click8.py`) with a targeted, tab-scoped one._

## Why CDP, not OS input

`click8.py` fired `pyautogui.click()` at the physical cursor — it hijacks the mouse and
needs Forge in the foreground. This dispatches to the renderer of the attached tab instead
(Playwright `page.mouse` / `page.keyboard`, which ride CDP): the cursor never moves, it
works on a backgrounded tab, and it targets *that* tab by coordinate. The action button is
at a **fixed** viewport position, so its coordinate is scanned once and hardcoded — exactly
the operator's plan.

## What was built (`src/bap/forge/action/`)

| Piece | What |
|---|---|
| `CdpClicker` | Thin wrapper over a Playwright `page`: exactly `click_xy(x, y)` and `press(key)` — no drag, no typing, nothing else. Each action is logged. |
| `run_click_loop(...)` | Pure loop: click `count`× at (x, y), optional `key` after each (e.g. `r` to repeat a fight), `interval` pacing, early `should_stop()`. `sleep`/`should_stop` injectable → deterministic tests. |
| `connect_and_run` | Playwright `connect_over_cdp` → find the Forge page → run the loop. Injectable connect; `no-cover` live glue. |
| `probe_coordinate` (`--probe`) | **Scan tool**: attaches a click listener and prints the viewport `(x, y)` of each real click you make, so you read off the fixed button's coordinate. Read-only measurement. |
| CLI `bap-forge-click` | `--probe` to scan; `--x --y [--key r] [--count N] [--interval S]` to act. A loop (`--count > 1`) requires typing `yes` (or `--yes`). |

## Usage (local, against the running CDP Chrome)

```
# 1) scan the fixed action-button coordinate:
bap-forge-click --probe                       # click the button once → prints --x N --y M

# 2) one targeted click (safe default):
bap-forge-click --x 913 --y 521

# 3) the "grády" loop — click + R repeat, like click8.py but tab-targeted:
bap-forge-click --x 913 --y 521 --key r --count 50 --interval 0.15
```

## Safety / scope

- **Explicit, opt-in tool** — invoked deliberately with coordinates. It is **not** wired
  into the observe-only GUI; the main app stays observe-only.
- **Single-purpose** — `CdpClicker` can only click and press one key; `run_click_loop` has a
  hard `count` and a `should_stop` hook; a multi-click loop demands confirmation.
- **Targeted** — dispatches to the Forge page only (matched by host), never the desktop.
- **Audited** — every click/key and the target URL are logged.
- This is the first authorised move beyond OBSERVE-ONLY, on the action track, at the
  operator's explicit request.

## Tests (6, all green)

`tests/unit/forge/action/test_cdp_click.py`: the clicker dispatches click+key to the *page*
(not the OS); the loop does 1 click by default; `count=3 --key r` → 3 clicks + 3 presses
with correct interval pacing; `should_stop` halts mid-loop; `count<=0` does nothing; no key
→ no presses. The Playwright/CDP glue and the probe are `no-cover` (need a live browser).

## Next

- **Scan + hardcode** the fixed action coordinate(s) from a real session (`--probe`).
- **Close the loop with the data brain**: stop the click loop when `LiveGbgReader` shows the
  player's `attrition_level` crossing a limit (data-driven CONTINUE/STOP) — this is where
  Phase-1 data and Phase-2 action meet into a real gated autoplayer.
- (Later) province selection → open → attack chained under that gate.
