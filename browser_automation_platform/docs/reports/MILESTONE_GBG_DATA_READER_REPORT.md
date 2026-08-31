# Milestone — GBG structured-data reader + target advisor (Phase 1, read-only)

_The first real step of "read the game's own data instead of the pixels." Given the
confirmed `/game/json` schema (`docs/design/GBG_API_SCHEMA.md`), this parses the
`GuildBattlegroundService.getBattleground` payload into a typed model and ranks the best
attack targets **directly from the exact fields** — no OCR, no calibration, no UNKNOWN.
It is perception + advice only: it selects and explains, it never clicks._

## What was built (`src/bap/forge/gbg_data/`)

| Module | What |
|---|---|
| `model.py` | Frozen dataclasses: `Province` (id, owner, `locked_until`, `gain_attrition_chance`, building slots, `conquest_progress`, …), `Participant`, `PlayerState` (your `attrition_level`), `Battleground` (with `owner_of` / `is_mine` / `observed_at`). Missing values → `None`, never a crash. |
| `parser.py` | `parse_battleground(responseData)`, `parse_game_json(batch)` (finds the getBattleground entry + server clock), and `parse(obj)` (accepts either). **Defensive**: unknown shape → `None`; a bad province/participant is skipped, not fatal. |
| `advisor.py` | `rank_targets(bg)` → `TargetSuggestion` list, best first: **lowest `gain_attrition_chance` wins**, open before locked, soonest-to-unlock next. Excludes your own and negotiate-type; `include_locked=True` to plan ahead. |
| `__main__.py` | `python -m bap.forge.gbg_data <file.json>` — prints your attrition, the province count, the next change, and the ranked targets. Runs against a HAR-extracted response or the committed sample. |

## Proven against the real capture

Run on `dataset/api_samples/getBattleground.sample.json`:

```
Battleground: volcano_archipelago
You: Piráti (orange)   attrition level: 67
Provinces: 60   season ends 2026-09-07 06:00 UTC
Next change: province(s) [33] at 2026-08-31 20:04 UTC
Best attack targets (3 of 3):
   1. province 55  attrition 40%  owner red     1/1
   2. province 28  attrition 60%  owner purple  0/1
   3. province 45  attrition 60%  owner yellow  2/2  siege
```

Everything the pixel pipeline approximated is now exact: `gain_attrition_chance` is the
same 20/40/60/80/100 value space the classifier tries to OCR (verified distribution
`{20:17, 40:4, 60:5, 100:12}`), ownership comes from `ownerId → participant.colour`, and
timing from `lockedUntil`.

## Precision / correctness / speed (the evaluation, demonstrated)

- **Precision & correctness:** exact integer fields — no similarity bar, no wrong-accepts,
  no ROI calibration, immune to resolution / zoom / Czech UI / window position.
- **Speed:** the 17-test suite (parse 60 provinces + rank, many times) runs in **~0.07 s**;
  the pixel/vision suites take minutes. Parsing is microseconds vs a screenshot + CV pass.

## Tests (17, all green)

`tests/unit/forge/gbg_data/test_gbg_data.py`: parses the real capture (60 provinces, 7
guilds, player 103787 / attrition 67); the attrition-chance distribution matches the pixel
value space; owner mapping + `is_mine`; conquest-progress parsing; advisor orders by
attrition and never lists your own or locked provinces (and `include_locked` sorts locked
last); `parse_game_json` finds the entry and the server clock; `parse` rejects seven
non-battleground inputs; a malformed province is skipped without crashing; synthetic
advisor edge cases (own/negotiate/unknown excluded; locked filtering + ordering).

## Scope held

- **Read-only.** No clicking, no `/game/json` requests sent, no game actions. It reads what
  already crosses the tab and advises.
- **Additive.** A brand-new package; nothing in the vision/gate/GUI paths changed. The
  vision pipeline stays as the fallback / cross-check.

## Next (Phase 2 — action)

The data now answers **what/when**. Phase 2 adds **where**: turn a chosen `province_id`
into a screen/viewport point (map hitmaps or a vision confirm of the known target) and open
it with the CDP click (`CDP_TARGETED_CLICKING_DESIGN.md`). Also next: wire the live reader —
a `CdpGameJson` adapter that watches `/game/json` responses on the attached tab and feeds
`rank_targets` — and surface the ranked targets in the GUI beside the pixel scan.
