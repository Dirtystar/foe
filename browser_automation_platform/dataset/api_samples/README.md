# GBG API samples (real, sanitized)

Captured from a live Guild Battlegrounds session (world cz6) via a browser HAR export,
then reduced to the JSON-RPC **`responseData`** bodies only. **No URLs, session tokens
(`?h=…`), cookies, or request headers are included** — just the game payloads, so we can
build and test the structured-data reader against real shapes.

| File | Source call | What it is |
|---|---|---|
| `getBattleground.sample.json` | `GuildBattlegroundService.getBattleground` | The whole battleground: league, map + 60 provinces, 7 guild participants, the current player's attrition, season end. |
| `getState.sample.json` | `GuildBattlegroundStateService.getState` | Championship/season metadata (dates, rewards, `stateId`). |

These are fixtures for parser development — not part of the vision dataset. See
`docs/design/GBG_API_SCHEMA.md` for the field mapping.
