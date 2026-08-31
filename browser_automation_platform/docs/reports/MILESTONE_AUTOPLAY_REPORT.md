# Milestone — Gated autoplay (brain + hand joined)

_The payoff: the live data brain and the CDP hand meet into one **gated fight loop**.
Fight (click + repeat key) while the player's live `attrition_level` is below a limit;
**stop the moment it reaches the limit**. A province runs out of fights on its own;
attrition is the ceiling. Live CDP click was confirmed working on the real game (cz6)._

## The gate (the project invariant, made concrete)

Before **every** fight the loop reads the current attrition from the live `/game/json`
feed:

- `attrition >= max_attrition` → **STOP** (never fights at/over the limit, so with a
  per-fight +1 step it never pushes past it — a hard ceiling);
- `attrition is None` (unknown) → **STOP** — fail-safe, never fight blind;
- otherwise → one fight (click + `key`), then repeat.

Plus a hard `max_clicks` pojistka and a `should_stop` hook.

## What was built (`src/bap/forge/action/autoplay.py`)

- `run_autoplay_loop(clicker, get_attrition, x, y, *, max_attrition, max_clicks, key, …)`
  — the pure gated loop. Fully unit-tested with a fake clicker + scripted attrition.
- `run_autoplay(endpoint, …)` — live glue on **one** CDP connection carrying both the
  `/game/json` reader (attrition source, via `LiveGbgReader` + response listener) and the
  `CdpClicker`, on the chosen tab, brought to front. Waits for the first attrition reading,
  then runs the loop with `page.wait_for_timeout` as the pacing sleep so live responses keep
  arriving between fights. `no-cover`.
- CLI `bap-forge-autoplay` — requires confirmation; `--tab`/`--tab-index` selects the world.

## Usage

```
bap-forge-autoplay --tab cz6 --x 1145 --y 788 --max-attrition 50
# fights cz6 until attrition hits 50, then stops. --max-clicks caps it hard.
```

## Honest caveats

- **Data lag:** attrition is read from the latest `/game/json`; if the fight response lags,
  the loop could be ~one fight behind. Set the limit a point or two below your absolute
  ceiling for margin. (The fail-safe and per-fight step keep this small.)
- **Single tab, single province.** It fights whatever is under the button. It does **not**
  yet pick/switch provinces or worlds — that's next.
- **Multi-tab (≈8 worlds):** likely **round-robin**, not truly parallel — a backgrounded
  canvas game tends to need the tab in front to accept input (we saw `bring_to_front` matter).
  To be tested; if background clicks register, near-parallel becomes possible.

## Tests (7, all green)

`tests/unit/forge/action/test_autoplay.py`: fights up to the limit then stops; never fights
at/over the limit; attrition-unknown → fail-safe stop (no clicks); `max_clicks` hard cap;
`should_stop` halts; no key → no press; result reports final attrition. Full action suite:
13 passed. Packaging test updated for the new `bap-forge-autoplay` entry point.

## Next

1. **Confirm on the live game** (operator): `bap-forge-autoplay --tab cz6 --x .. --y .. --max-attrition N`.
2. **Multi-tab round-robin** across ~8 worlds (rotate focus, fight each, respect each world's
   own attrition).
3. **Province selection/switch** once a province is exhausted (data brain picks the next
   target; open it; resume).
