# Milestone — Round-robin autoplay across worlds

_The first multi-world step toward the all-day vision: fight several worlds in rotation,
each to **its own** attrition limit, marking a world **Done** and leaving it alone while the
rest keep going. Config-driven (the shape the future GUI will write). Gated per world by the
**real** live attrition — a world with no data is skipped, never fought blind._

## What was built (`src/bap/forge/action/round_robin.py`)

- **`WorldPlan`** — one world's config: `name`, fight point `x,y`, `max_attrition`
  (`99999` = unlimited), tab selector (`tab`/`tab_index`), repeat `key`.
- **`run_round_robin(worlds, fight_once, get_attrition, …)`** — the pure scheduler. Rotates,
  fights each world in **bursts** (fairness), reads real attrition before each fight, marks a
  world **Done** at its limit, skips a world with unknown attrition, and stops when all are
  Done / `should_stop` / a total cap / a no-progress rotation. Returns `{name: WorldStatus}`.
- **`load_world_plans(path)`** — reads `worlds.json` (`docs/examples/worlds.example.json`).
- **`run_round_robin_live` / CLI `bap-forge-farm`** — one CDP connection, a `/game/json`
  reader + clicker per world tab, brings each to front when fought, prints per-world progress
  and `✅ Done <world>`. `no-cover` (needs a live browser).

## Usage

```
bap-forge-farm --config worlds.json          # rotate all worlds until each hits its limit
```
`worlds.json`:
```json
{"worlds": [
  {"name": "cz6", "tab": "cz6", "x": 1145, "y": 788, "max_attrition": 50},
  {"name": "cz8", "tab": "cz8", "x": 1145, "y": 788, "max_attrition": 80},
  {"name": "cz2", "tab": "cz2", "x": 1145, "y": 788, "max_attrition": 99999}
]}
```

## Scope & honesty

- **Per-world attrition limit + Done + others-continue**: ✅ delivered (the vision's core loop).
- **Fair rotation** via bursts; **fail-safe** skip on unknown attrition.
- **Not yet** (tracked in `docs/ROADMAP.md`):
  - **Province auto-selection / the % allowlist** — the farm fights whatever province is open
    under each world's fixed button; it does not yet navigate the map to *choose* provinces by
    their % (that's the map-navigation "where", B3).
  - **Self-heal** (reload/restart) for true all-day resilience (B4).
  - **GUI** (map tabs, set limits, START/STOP, live status) — config is JSON for now (E2).
- Since a canvas game needs the tab in front to accept input, worlds are fought in **rotation**
  (one active at a time), not truly in parallel — as anticipated.

## Tests (9 + packaging)

`test_round_robin.py`: each world fights to its own limit; fair rotation under a total cap;
Done world left alone while others continue; unknown-attrition world skipped (never fought
blind) → `no_data`; unlimited runs to the cap; `should_stop` halts; events report Done; config
loader (defaults + empty-is-error). Entry point `bap-forge-farm` added; full action suite green.

## Next

Per the roadmap: **B3 province auto-selection** (choose allowed-% provinces and open them on
the map) is the next big capability, then **B4 self-heal** and the **E2 autoplay GUI** that
makes all of this usable by a non-technical user.
