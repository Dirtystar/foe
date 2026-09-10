# Milestone A — UI State Detection ("Where am I?")

_A new product capability, read-only. The application can now look at a screenshot
and reliably answer **which Forge UI state it is looking at** — `GBG_MAP`,
`PROVINCE_PANEL`, or a fail-safe `UNKNOWN` — with a confidence and the supporting
signals. It contains **no** automation, transition, or gameplay logic; a future state
machine will consume this to decide "what should I do next?". No clicking, cursor, or
gameplay behaviour changed._

## Summary — what was implemented

A small, self-contained `bap.forge.state` package:

| File | Responsibility |
|---|---|
| `screen_state.py` | `ScreenState` (open enum: `GBG_MAP`, `PROVINCE_PANEL`, `UNKNOWN`), the evidence/result dataclasses, `classify_screen()` orchestrator, and the pure fail-safe `decide()` rule. Emits one structured log line per classification. |
| `detectors.py` | Per-state detectors in a **registry** (`DEFAULT_DETECTORS`): `detect_gbg_map` (map badges in the map ROI) and `detect_province_panel` (fixed-pill emblem score). Reuses the **frozen** `BadgeDetector` read-only. |

Plus a **read-only** "UI state" indicator line in the Vision Debugger (reuses the
open scan's detections — no second scan), and tests.

## New capability

Before: the app assumed every screenshot was the battle map and acted blind to
context. After: it can **name the screen** it is looking at, expose *how sure* it is
and *why*, and **refuse to guess** when it cannot tell (UNKNOWN). This is the
substrate every future action and every recovery path needs — the first answer to
"Where am I?" that the future "What should I do next?" will build on.

## Design (kept intentionally small, built to grow)

- **One question only.** The classifier produces a state + confidence + signals and
  stops. It never decides or acts.
- **Registry of detectors.** Each state has one detector that scores *only its own*
  state and explains why. A future state (City, Battle, Result, Loading, Connection
  Lost, Unexpected Popup, …) is added by writing one detector and registering it —
  `classify_screen` does not change. The enum is the single place states are named.
- **Fail-safe decision (`decide`).** A state wins only if its score ≥
  `min_confidence` (0.60) **and** it leads the runner-up by ≥ `min_margin` (0.15);
  otherwise `UNKNOWN`. A broken detector abstains (score 0) — it can never win. **No
  heuristic pretends to know more than it does.**
- **Observability.** Every classification carries per-state candidate scores + the
  signals it used + a human reason, and logs one structured record
  (`logger "bap.forge.state"`).
- **Reuse, not re-scan.** `DetectContext.map_detections` lets a caller that already
  ran the detector (the Debugger) feed those detections in, so the indicator is
  instant and no work is duplicated.

## Grounding — thresholds are measured, not guessed

Measured on real reviewed frames: map frames carry several detected weakening badges
and a **low** province-pill emblem score (≈ 0.09–0.12), while the map score lands
0.71–0.95. The two states therefore separate with a wide margin, and map frames are
never mistaken for a panel. Example (6 real frames): 5 → `GBG_MAP` (conf 0.71–0.95),
1 badge-less frame → `UNKNOWN`, 0 → `PROVINCE_PANEL`.

## Tests (18 new, all green)

- **Decision rule** (pure): clear winner chosen; below-confidence → UNKNOWN;
  small-margin → UNKNOWN; no scores → UNKNOWN.
- **Composition** (fake detectors): map wins; panel wins; ambiguous → UNKNOWN;
  all-low → UNKNOWN; `None` image → UNKNOWN without running detectors; a **crashing
  detector abstains** and never wins; the registry is extensible; the structured-log
  shape is stable; the confidence default is conservative; the **reuse hook** derives
  the map signal from precomputed detections without scanning.
- **Real frames** (bounded, cached once): real map frames are **never** read as a
  panel and the panel signal stays below the bar; the positive path yields `GBG_MAP`;
  a blank frame → `UNKNOWN`; classifications expose confidence/candidates/signals.

Full unit suite: run with `QT_QPA_PLATFORM=offscreen … pytest tests/unit` (green;
see the commit).

**What remains untested:** the *positive* `PROVINCE_PANEL` path on real pixels — we
have **zero** committed panel screenshots, so panel-open is validated only via
composition + the (already-tested) fixed-pill signal. This is by design: the product
should now drive that data (below).

## Technical notes / debt discovered (documented, not fixed — per policy)

1. **Badge-less GBG map → UNKNOWN** (severity: low). `detect_gbg_map` currently
   infers the map from detected weakening badges; a map with no visible badges reads
   UNKNOWN. Acceptable because we only act on maps that have targets, but a
   map-structure signal (top weakening bar / hex layout) would raise recall. Add when
   a non-map state (City) needs disambiguation anyway.
2. **Panel pill is a single fixed point** scaled crudely by resolution (severity:
   low→medium). Fine as a coarse state signal; real panel/battle detection will want
   proper panel geometry — collect panel frames first.
3. **No panel/battle/result data** (severity: medium, product-driven). The moment
   this runs live, panel/battle/result screens will read `UNKNOWN` — that is the
   signal to collect them (dataset grows from product need, per the new policy).
4. **Real-vision test cost.** `det.scan` is seconds per frame in this environment, so
   the real-frame test classifies just 2 frames + 1 blank, once. Coverage of the
   logic lives in the fast pure tests.

## Future risks

- Panel/other states can only be *positively* validated once we have their
  screenshots; until then they correctly read UNKNOWN (safe, but not yet capable).
- Thresholds are tuned to current live-capture scales; new resolutions/zooms may need
  the same margin re-checked (the confidence/margin design degrades to UNKNOWN, not
  to a wrong answer, so this fails safe).

## Recommended next milestone (one)

**Seed and validate the `PROVINCE_PANEL` state on real pixels — via a tiny,
product-driven collection pass, then a live check.**

Why this is the highest product value next: the state machine's very next transition
is `GBG_MAP → PROVINCE_PANEL`, and M6A.1 already performs the click that opens the
panel. Right now that transition is unproven on real panel pixels because we have
**zero** panel screenshots. The smallest high-value step is to **use the app to
generate the data**: run Open & Verify (or just click a badge) on a live world,
capture the opened panel, confirm `classify_screen` reports `PROVINCE_PANEL` with
confidence, and add a handful of panel frames as fixtures + a real positive test.
That turns the second state from "declared but unseen" into "reliably detected,"
unlocks the first real state **transition**, and directly feeds the independent
panel percentage reader built in M6A.1 — all in a few hours, entirely product-driven.

_(Await approval before starting the next milestone.)_
