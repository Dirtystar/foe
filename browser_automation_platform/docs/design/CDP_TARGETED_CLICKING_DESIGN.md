# Design note — CDP-targeted clicking (click the tab, not the desktop)

_Design only. No implementation. Proposes clicking the FoE tab through the **CDP
connection the app already holds** (`Input.dispatchMouseEvent` / `dispatchKeyEvent`),
instead of injecting OS mouse input at a physical screen point. This removes the
"only clicks where the cursor is parked" limitation and stops the app hijacking the
real mouse and foreground window._

Status: **proposed / awaiting build approval.** Sibling of
`M6_AUTONOMOUS_CLICKING_DESIGN.md` (the click-milestone spec) and
`GBG_DATA_READER_DESIGN.md` (the same "reuse the CDP connection" principle).

---

## 1. Problem — what physical clicking forces on us

Two things click at a **physical screen pixel** today:

- the operator's semi-manual `click8.py` — `pyautogui.click()` at the current mouse
  position, on a loop, tapping `R` each cycle (FoE "repeat fight");
- the app's own M6A.1 adapter, `WindowsSingleClick` (`adapters/input/os_click.py`),
  which `SendInput`-moves the cursor to a screen point then clicks. The
  cursor-preview gate even *requires* the physical cursor to be on target first.

Both share the OS-input-injection limitations the operator flagged:

- **hijacks the real mouse/keyboard** — you cannot use the PC while it runs;
- needs the **FoE window foregrounded** and the cursor **parked** on the button;
- **single-focus and blind** to which tab/window actually receives the event;
- coordinates are **physical screen pixels**, entangled with monitor scale, window
  origin, and the title bar/toolbar offset.

This is fine for one supervised click. It is the wrong foundation for a product that
should act on a specific tab without taking over the machine.

## 2. Approach — dispatch input into the attached tab over CDP

The capture adapter is **already attached to the FoE tab over CDP** (that is how it
takes read-only screenshots). The same session can dispatch input **into that tab's
renderer**:

- **`Input.dispatchMouseEvent`** — `{type: "mousePressed"/"mouseReleased", x, y,
  button: "left", clickCount: 1}` at a **viewport (CSS) coordinate**. A press+release
  pair is one click.
- **`Input.dispatchKeyEvent`** — `{type: "keyDown"/"keyUp", key: "r", ...}` for the
  `R` repeat-fight hotkey.

Why this fixes every point in §1:

| Physical injection (now) | CDP dispatch (proposed) |
|---|---|
| Moves & steals the real cursor | **Cursor never moves** — event goes to the renderer |
| Needs window foregrounded | **Works on a backgrounded tab** |
| Clicks "wherever the mouse is" | **Targets the specific attached tab**, by coordinate |
| Physical screen px (monitor scale, window origin, title bar) | **Viewport CSS px** — none of that |
| Blind to focus/tab identity | Bound to the **tab id we attached and gated on** |

This is exactly how Playwright/Puppeteer drive browser games (their
`mouse.click` *is* `Input.dispatchMouseEvent`). CDP-dispatched input is delivered to
the page as trusted input, unlike JS-synthesized events.

## 3. The coordinate win — it's already computed

`bap/forge/cursor/geometry.py::image_to_screen` transforms a would-click point in
three stages:

```
raw capture px  →  captured viewport (CSS) px  →  browser content CSS  →  physical screen px
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                   this is exactly what CDP needs
```

The physical adapter needs the **last** stage (screen px, with monitor scale +
window origin). **CDP needs the middle stage** — the `viewport_css` point — which
`image_to_screen` already produces and exposes on its `CoordinateTrace`
(`CoordinateTrace.viewport_css`). So CDP clicking is a **shorter, simpler** path than
physical clicking: it stops before monitor scale, window origin, and the title-bar
offset ever enter the maths. Fewer transforms, fewer ways to be wrong, and multi-
monitor / DPI scaling stop mattering entirely.

(`geom.zoom` still applies if the page is zoomed; `scroll_x/y` are 0 for Forge.)

## 4. Shape — a sibling adapter behind the same tiny port

Keep the M6A.1 safety structure. `ClickPort` (`forge/click/port.py`) is deliberately
one method, "one left click, nothing else" — that guarantee stays.

- **New adapter `CdpClick`** in `adapters/input/` beside `WindowsSingleClick` and
  `FakeClick`. It performs exactly one `mousePressed`+`mouseReleased` on the attached
  CDP session. No double-click, drag, hold, scroll — same structural guarantee.
- **One honest interface change to face.** `ClickPort.click_at(screen_x, screen_y)`
  is typed in *physical screen* pixels; CDP wants *viewport CSS* pixels. Options,
  cheapest first:
  1. Have the controller pass the adapter the coordinate space it wants — i.e. give
     `CdpClick` the `viewport_css` point from the existing `CoordinateTrace`, and let
     `WindowsSingleClick` keep taking screen px. A thin seam, no port rewrite.
  2. Only if a second CDP consumer appears, generalise the port to a coordinate +
     space. **Not now** — one adapter doesn't justify it.
- **Key press** (`R`) is a separate, equally tiny capability — a `KeyPort` with one
  method, or an explicit `CdpClick.press_repeat_key()`. It must be as constrained as
  the click port: one named key, no free-form typing. Design it deliberately; do not
  fold general keyboard access into the app.

## 5. Safety model shifts — and must be redesigned, not dropped

The current gate leans on **"the physical cursor is on the target"** (cursor-preview
move + tolerance check). With CDP, **the cursor never moves**, so that check becomes
meaningless. Do **not** silently drop it — replace it with checks that actually hold
for tab-dispatched input:

- **Tab identity is the anchor.** `evaluate_preview` already verifies `tab_id`,
  `hostname`, `world`, and freshness (`captured_at` age). For CDP that identity check
  is *the* safety spine: dispatch only to the exact session/tab we scanned and gated,
  and re-verify the tab id immediately before dispatch.
- **Observe-after is the confirmation.** We already have
  `open_province_and_observe` — one click, then classify the result. That honest
  post-check replaces "did the cursor land" with "did the expected state appear",
  and captures the frame either way.
- **Still one click, still per session-enabled, still audited.** No loop, no retry
  in this design. Autonomous chaining remains a separate, later milestone with its
  own review (see `M6_AUTONOMOUS_CLICKING_DESIGN.md`).

## 6. Feasibility probe (must pass before any adapter code)

Exactly like the data-reader note — prove it on the real game first, locally:

1. On the attached FoE tab, `Input.dispatchMouseEvent` a `mousePressed`+`mouseReleased`
   at a **known viewport coordinate** of a harmless UI element; confirm the game
   reacts **without the window focused and without the physical cursor moving**.
2. `Input.dispatchKeyEvent` `keyDown`/`keyUp` for `r`; confirm the repeat-fight
   behaviour fires.
3. Confirm the click lands correctly using the `viewport_css` value from
   `image_to_screen` on a real scan (coordinate correctness end-to-end).

**Go/no-go.** If FoE ignores CDP input (unlikely for a browser game, but it must be
checked), physical injection stays the fallback and this note is shelved.

## 7. Risks & honest limits

| Risk | Note |
|---|---|
| FoE ignores synthetic/CDP input | Unlikely (browser-rendered game; Playwright drives such games), but the probe is the gate. Fallback: physical adapter stays. |
| Coordinate mismatch (canvas hit-testing) | Mitigated: we feed the same `viewport_css` the geometry already derives; verify in the probe. |
| Page zoom / DPR edge cases | `geom.zoom` and the capture↔viewport scale are already modelled; test at 100/125/150 %. |
| **ToS / automation posture** | Background, cursor-free clicking is a **higher automation profile** than observe-only or a supervised physical click. This is a conscious product decision, not implied by the mechanism. Keep it operator-enabled per session; do not enable by default. |
| Losing the cursor-on-target safety | Explicitly replaced by tab-identity + observe-after (§5); the note fails review if that swap isn't built. |
| Key access creep | The `R` capability must be as narrow as the click port — one named key, no typing. |

## 8. Staged plan (for when approved)

1. **Probe** (§6) — observation/one-shot only, locally. Go/no-go.
2. **`CdpClick` adapter** behind `ClickPort`, fed `viewport_css`; unit-tested with a
   fake CDP session (assert exactly one press+release, correct coords, right session).
3. **Wire into `open_province_and_observe`** as an alternative adapter — one gated CDP
   click, then the existing observe + capture. Compare against the physical path.
4. **Narrow key capability** for `R`, same structural constraints, its own tests.
5. **Only then** revisit the autonomous milestone with CDP as the actuator and the
   redesigned (tab-identity + observe) safety model.

## 9. Recommendation

Adopt CDP-targeted clicking as the app's real click actuator, **after** the
feasibility probe, as a sibling adapter behind the existing one-method `ClickPort`.
It directly resolves the operator's limitation (no parked cursor, no stolen mouse, no
foreground requirement), it is *simpler* than physical clicking because it reuses the
`viewport_css` coordinate the geometry already computes, and it keeps the M6A.1 safety
guarantees — provided the cursor-on-target check is **replaced** by tab-identity +
observe-after, not dropped. Sequence it after real panel frames exist (the current
collection milestone), so the first CDP clicks are validated against a proven
open→observe path.

_Await the feasibility-probe result before writing adapter code._
