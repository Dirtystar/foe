# B3 — Province auto-selection (design; feasibility CONFIRMED)

_The milestone that makes it "play by itself": the app **chooses** which provinces to attack
(per-world %-allowlist) and **opens them on the map** — no manual line-up. Feasibility is
confirmed from real captures; the pure foundation (map layout + transform + %-filter) is
built and tested. This note is the plan for the live navigation on top._

## The three pieces (and their state)

1. **WHICH provinces** — from `getBattleground.map.provinces`: filter to the per-world
   **allowed %** (`gain_attrition_chance ∈ {20,40,…}`), enemy-owned, not locked; rank by %.
   → ✅ built: `rank_targets(bg, allowed_pcts=…)`.
2. **WHERE each province is** — the static map asset
   `assets/guild_battlegrounds/map/data/<mapId>` lists every province's **flag position in
   map space** (~2500×1960). Confirmed: all 60 `getBattleground` ids have a flag.
   → ✅ built: `parse_map_data` → `MapLayout.flags[id] = (mx, my)`.
3. **MAP → SCREEN** — an axis-aligned affine `screen = scale*map + offset`. Solve it from a
   **two-point calibration** (click two known provinces once); then any province's click
   point = `transform.to_screen(flag)`.
   → ✅ built: `MapTransform.from_two_points`, `province_screen_point`.

So the whole "what/where" is data-driven and unit-tested against real fixtures
(`dataset/api_samples/map_data.*.sample.json`, `getBattleground.sample.json`).

## The live flow (to build)

Per world, on one CDP connection (background play, `--no-raise`):

1. **Capture the map asset**: watch the tab's network for `.../map/data/<mapId>` (like we
   watch `/game/json`) and parse it → `MapLayout`. (`map.id` from `getBattleground` tells us
   which map; the browser fetches the asset on GBG load.)
2. **Calibrate once** (per world/session): ask the operator to click two provinces the app
   names (far apart in x and y); record screen points → `MapTransform`. Persist it with the
   world config so it's not repeated every start (invalidate if the map view changes).
3. **Select a target**: `rank_targets(bg, allowed_pcts=world.allowed_pcts)` → best allowed,
   open, enemy province.
4. **Open it**: CDP-click `province_screen_point(layout, transform, target.id)` → the panel
   opens. Confirm via the UI-state classifier / the panel response.
5. **Fight it**: click the (fixed, calibrated) attack button + `R` — the existing gated loop,
   stopping at the world's real attrition limit.
6. **Advance**: when the province is exhausted (its `conquest_progress`/ownership shows done,
   or fights stop registering), pick the next allowed target and repeat.

The per-world `allowed_pcts` and the two calibration points join the world config
(`worlds.json` today; the GUI later).

## Open questions / risks (live)

- **Map pan/zoom stability.** The transform assumes the map isn't panned/zoomed mid-play. If
  the game re-centers or the user scrolls, the transform drifts. Mitigation: calibrate on a
  known default view; detect drift (a known flag no longer under its computed point) and
  re-calibrate; or read the camera transform from the page if exposed.
- **Opening vs attacking.** Clicking a province flag opens its panel; the attack button is a
  second (fixed) click. Need to confirm the panel-open reliably before attacking (reuse the
  province-open observation).
- **Province exhaustion signal.** Decide the cleanest "this province is done" signal —
  ownership flip to us, `conquest_progress` complete, or the battle simply stops returning a
  fight. Prefer a data signal from `getBattleground` over a pixel guess.
- **Per-map assets.** Different worlds/rotations use different maps; capture each world's own
  `map/data`. The flag layout is per map id.

## Build order

1. ✅ Pure foundation: `map_layout` (parse + transform + place), `rank_targets(allowed_pcts)`.
   Tested against real fixtures.
2. Capture `map/data` live (CDP network) + a small **2-point calibration** flow (persisted).
3. Wire selection→open→confirm→fight→advance into the autoplay/farm loop.
4. Field-test; then the GUI (E2) exposes the allowlist + calibration to non-technical users.

_Foundation done; steps 2–3 are the next build._
