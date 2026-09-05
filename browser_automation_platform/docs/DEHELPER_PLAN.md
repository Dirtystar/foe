# Dropping the FoE Helper dependency

The farmer currently needs the **FoE Helper** browser extension at runtime: it reads the
extension's injected DOM for the map→screen transform, province names, the "in GBG?" check, and
the leader's Cíl marks. That's a problem for shipping — not every user has it, and it's a moving
third-party target. This is the plan to remove it, what's easy, and the one hard part.

## What we depend on today

| # | FoE Helper thing | Selector | Used for | Where |
|---|---|---|---|---|
| 1 | Building-marker arrows | `button.building-marker-btn[data-id]`, `.building-marker-arrow` | **Map→screen transform** (place any province) | `locate.py`, `solve.py`, `marker.py` |
| 2 | GBG sidebar | `.gbg-tabs` | "are we on the GBG map?" (`_in_gbg`) | `open_targets.py` |
| 3 | Province name rows | `tr[data-id] .prov-name b` | province **names** → centre-ring priority | `open_targets.py` (`_JS_NAMES`, `_ring`) |
| 4 | Focus-target rows | `tr[data-id] .focus-target` | leader **Cíl** override | `open_targets.py` (`_JS_CIL`) |

## Native replacements

### 1. Transform — SOLVED, no Helper needed ✅
The clever part already exists: `gbg_data/calibration.py` turns *"I clicked a point → the game told
me which province via `getArmyPreview.provinceId`"* into calibration samples, and `solve_uniform`
fits the transform. Today a human (or the Helper markers) supplies the clicks. The only missing
piece is an **autonomous probe**: the app clicks a spread of points itself, reads which province
each opens, and solves. Built in `action/native_calibrate.py` (`native_solve`). Scale has been
1.0 every run, so even 2–3 good samples fix it; `residual` validates.

### 2. "In GBG?" — easy ✅
Replace `.gbg-tabs` with a non-Helper signal. Cheapest: a **state flag** — set true when a fresh
`getBattleground` arrives, false on reload / when we detect the city. Backup: a tiny **vision**
check for the GBG attrition bar (same template-match tech as the entrance). Planned as
`native_in_gbg(page, reader)`.

### 3. Names / centre-ring — easy, arguably better ✅
Names were only used to prioritise central provinces (A1/B1 before …4) and for logs. Farming
doesn't need names. Replace name-parsing with **geometry**: rank provinces by distance from the
map centroid (`native_calibrate.centrality`) — central sectors first, straight from `map/data`
flags. Logs just show `#id`.

### 4. Cíl / Stop leader marks — native after all ✅ (find the field)
Correction: Stop/Cíl are a **native game feature** — a guild member with the right sets them, but
**every guild member can read them** without FoE Helper. So the marks ride on some `/game/json`
field; they were simply absent from our one sample (an unmarked map).

Plan: record a HAR on a map the leader **has** marked and run
``python -m bap.forge.action.har_probe marked.har --marks`` — it lists the GuildBattleground* calls
and prints any object whose keys look like a sector mark/strategy (e.g. a per-province
``sectorStrategy`` / priority field, or a map-level marks array). Once we know the field, parse it
into the model and honour it natively:
- **Stop** → add to the skip set (never fight), same effect as today.
- **Cíl** → absolute priority, same ordering as today.

No FoE Helper, no cooperation needed. `_JS_CIL` gets deleted along with the rest.

## Rollout (no risk to the working path)
1. Land `native_calibrate` behind an opt-in `--native-calib` flag; keep the Helper path default.
2. Live-test native calibration on one world; compare `residual` to the Helper solve.
3. Make native the **fallback** when Helper markers are absent, then the default.
4. Swap `_in_gbg` and `_ring` for the native versions.
5. Find the marks field from a marked-map HAR, parse Stop/Cíl natively, and remove the last
   `tr[data-id]` reads.

Result: all four dependencies are replaceable with native game data — no FoE Helper and no
cooperation required. The only outstanding unknown is the exact marks field name, which one
marked-map HAR reveals.
