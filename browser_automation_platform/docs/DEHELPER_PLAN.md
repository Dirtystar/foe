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

### 4. Cíl / Stop leader marks — the hard part ⚠️
The leader's Cíl (fight-this) and Stop (never-fight) marks are **not in `getBattleground`** and no
GBG service method in the client exposes them (confirmed via the live client probe). They appear to
be a **FoE-Helper-only overlay** (guild-shared through the Helper's own channel), so there is no
native game API to read them.

Options, cheapest first:
- **A. Drop the feature.** Fight purely by %, then centrality. Simple, fully Helper-free. Lose the
  leader-coordination nicety.
- **B. Manual marks in our app.** Let the user type "always fight" / "never fight" province ids (or
  pick on a map view) per world. Replaces the leader overlay with our own — Helper-free, and it's
  our data.
- **C. Find a real source.** Record a HAR on a map the leader has marked and diff it — if the marks
  ride on a guild message/annotation endpoint, we can read them natively. Unknown until we look.
- **D. Cooperation.** If the marks only live in FoE Helper, integrate with it *for this one feature*
  (or partner with its authors) while everything else runs native.

**Recommendation:** ship **A or B now** (fully Helper-free), keep **C** as a quick HAR experiment,
and consider **D** only if the leader-marks feature proves important enough to users.

## Rollout (no risk to the working path)
1. Land `native_calibrate` behind an opt-in `--native-calib` flag; keep the Helper path default.
2. Live-test native calibration on one world; compare `residual` to the Helper solve.
3. Make native the **fallback** when Helper markers are absent, then the default.
4. Swap `_in_gbg` and `_ring` for the native versions.
5. Decide Cíl (A/B/C/D) and remove the last `tr[data-id]` reads.

Result: items 1–3 are straightforward and mostly built; only **Cíl (4)** may need cooperation —
matching the "if it's too big, we'll consider cooperation" call.
