# GBG API schema — the game's own structured data (CONFIRMED from a real capture)

_This supersedes the "assumed WebSocket" part of `GBG_DATA_READER_DESIGN.md` with the
**real** shapes, captured from a live GBG session (world cz6) via a browser HAR. Sanitized
sample payloads live in `dataset/api_samples/`. Everything the app has been trying to read
from pixels is present here as clean JSON — including the number the pixel classifier
struggles with._

## Where it comes from — HTTP POST, not (only) WebSocket

FoE sends game state over **HTTP POST to `/game/json`** (a JSON-RPC-style batch), not a
metatag or the DOM (the map is a canvas). Each request/response is an array of
`ServerRequest` / `ServerResponse` objects keyed by `requestClass` / `requestMethod`.
The two that matter:

- **`GuildBattlegroundService.getBattleground`** → the whole battleground (map, provinces,
  participants, the player's attrition).
- **`GuildBattlegroundStateService.getState`** → season/championship metadata.

**How the app reads it (no third party, observe-only):** the capture adapter is already
attached over CDP. Enable the **CDP Network domain** and watch
`Network.responseReceived` for URLs containing `/game/json`, then `Network.getResponseBody`
to read the JSON — purely passive, same connection as screenshots. (This replaces the
WebSocket-frame plan in the data-reader note; HTTP responses are easier and complete.)

## The payload — `getBattleground.responseData`

```
{
  league: { id: "diamond", name, rating },
  map: {
    id: "volcano_archipelago",
    pendingUpdate: { updateAt: <unix>, provinceIds: [33] },   // next province(s) to change
    provinces: [ GuildBattlegroundProvince, … 60 ],
  },
  battlegroundParticipants: [ GuildBattlegroundParticipant, … 7 ],
  currentPlayerParticipant: { attrition: { level, negotiationMultiplier, defendingArmyBonus }, activeTrial },
  currentParticipantId: <me>,
  endsAt: <unix>,           // season end
}
```

### `GuildBattlegroundProvince`
```
{
  id: 14,                          // province id (the "0" province omits id)
  ownerId: 103787,                 // → participantId of the owning guild
  lockedUntil: 1788210517,         // UNIX — when this province next opens/unlocks
  gainAttritionChance: 60,         // ★ 0/20/40/60/80/100 — see below
  conquestProgress: [ { participantId, progress: 38, maxProgress: 132 } ],  // active siege(s)
  usedBuildingSlots: 2, totalBuildingSlots: 3,   // the "X/3" fraction on the map
  isAttackBattleType: true,        // attack vs negotiate
  victoryPoints, victoryPointsBonus,
}
```

### `GuildBattlegroundParticipant`
```
{ participantId: 103783, clan: { id, name, flag }, colour: "red", victoryPoints: 2897 }
```
`ownerId` on a province → this participant → **guild name + colour** (matches the map's
territory colours: red/green/yellow/teal/orange/blue/purple).

## Field → app-concept mapping (the reconciliation)

| App concept (today, from pixels) | Data field (exact, no OCR) |
|---|---|
| **"weakening %" badge = 20/40/60/80/100** | **`province.gainAttritionChance`** — measured distribution in the sample: `{20:17, 40:4, 60:5, 100:12}` across 38 attackable provinces. **This is the number `PercentClassifier` tries to read.** |
| province building fraction "X/3" | `usedBuildingSlots` / `totalBuildingSlots` |
| guild ownership (territory colour) | `ownerId` → `participant.colour` / `clan.name` |
| "when does it open?" (not on screen at all) | `province.lockedUntil` (+ `map.pendingUpdate.updateAt`) |
| siege in progress on a province | `conquestProgress[] {participantId, progress, maxProgress}` |
| player's accumulated attrition (top-bar counter) | `currentPlayerParticipant.attrition.level` (e.g. **67**) — **per-world/player, matches the gate's invariant** |
| attack vs negotiate | `isAttackBattleType` |

**The old caveat is resolved.** Earlier we worried whether an "attrition" field meant the
weakening %. It does, cleanly split: **per-province `gainAttritionChance`** (the map badge
value the gate reasons about) vs **player `attrition.level`** (how weakened *you* already
are). Both are exact.

## What this unlocks

- **The weakening gate can read `gainAttritionChance` directly** — no OCR, no similarity
  bar, no wrong-accepts, no ROI calibration. Pixels become a cross-check, not the source.
- **Province identity, ownership, and unlock timing** — the two questions pixels can't
  answer — are all present.
- **Targeting** (which province to open/attack) becomes a data query (low `gainAttritionChance`,
  right `isAttackBattleType`, enemy `ownerId`, not `lockedUntil` in the future) instead of a
  pixel guess.

## Reader shape (unchanged from the data-reader note, now with real fields)

Read-only `GbgDataPort` + a `CdpGameJsonAdapter` that watches `/game/json` responses,
parses the `GuildBattlegroundService.getBattleground` body into `Province(id, owner_guild,
colour, gain_attrition_chance, locked_until, used_slots, total_slots, is_attack,
conquest_progress)` + `PlayerState(attrition_level)`, keeps an in-memory snapshot with
`observed_at`, and **falls back to the vision pixels** if absent. Defensive parsing: unknown
shape → drop + keep last good snapshot. Fixtures: `dataset/api_samples/*.json`.

## Safety / posture (unchanged)

Passively reading `/game/json` responses that already cross our attached tab is the same
observe-only category as the screenshots. It reads; it does not act. Any move to
data-informed clicking is a separate, conscious milestone (see `M6_AUTONOMOUS_CLICKING_DESIGN.md`
and `CDP_TARGETED_CLICKING_DESIGN.md`).

## Provenance

Captured by the operator (world cz6, diamond league) as a HAR; reduced to `responseData`
bodies only, session token and headers stripped, saved to `dataset/api_samples/`.
