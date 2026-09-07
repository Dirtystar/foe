# FoE Alerting — handoff for a fresh session

This subproject was split off from the farmer's session on purpose. Everything it needs lives
on the branch `claude/foe-alerting-cz8`; the farmer lives on
`claude/browser-automation-architecture-5784h1` and the two must not be mixed. **Read
`docs/FOE_ALERTING.md` first** — it is the design and the user guide. This file only carries
the context a fresh session cannot read out of the code.

## What this is

Guild Battlegrounds alerting for **one world (cz8) only**. It posts one line per province
opening into the guild's WhatsApp group:

```
16:25 🔵 A1X
```

`<time it opens, Prague> <🔴 attack | 🔵 defence> <the guild's coordinate>`

It is read-only. It never clicks, never sends a request to the game, and shares no code path
with the farmer's clicking. It only listens to `/game/json` responses the browser already
receives on the cz8 tab, and posts text to a messaging gateway.

## Decisions already made (don't re-litigate)

- **Data source**: one `getBattleground` snapshot carries every opening for hours ahead
  (52/60 provinces spanning ~3.7 h in the captured sample), so there is **no polling of the
  game**. The watcher rides on the GBG entries that happen anyway — the farmer running on cz8
  refreshes it constantly. `--refresh-minutes` is the fallback when nothing drives the tab.
- **No FoE Helper.** Lock times, owner and the commander's marks all come from the game's own
  JSON. Helper would add a moving part and nothing else.
- **Green API** is the transport: Meta's official Cloud API and Twilio cannot post to a group
  at all. It sits behind a one-method port (`send(text) -> bool`), so a webhook or a
  self-hosted bridge is a config change.
- **Attack vs defence** = `province.ownerId` vs `currentParticipantId`. Ours → they will siege
  it when it opens (defence 🔵); theirs → we can (attack 🔴).
- **Commander marks are honoured**: `ignore` ("Stop") suppresses an *attack* announcement but
  never a defence; `focus` widens the default scope. Marks are read-only — the `setSignal`
  write endpoint must never be called.
- **Each opening is announced exactly once**, keyed `provinceId:lockedUntil`, remembered in
  `alert_state.json` across restarts.

## The one open question

**The game ships no province names.** A province is an id (0…59) plus a flag position in the
static map asset, so `A1X` is a guild convention that has to be mapped once per map
(`province_labels.<world>.json`). Until a province is named it falls back to a generated grid
position (`F7`) and then `#14`, so nothing is blocked on the naming.

Ask the owner: *is `A1X` your guild's own notation, or is it written somewhere in the game / a
tool?* If the game shows it, read it from there instead of maintaining a file.

## Standing rules from the owner

- **No blind testing.** When something can only be settled against a live game, produce a
  ready-to-paste prompt for an AI with Chrome MCP access; the owner runs it in another chat and
  brings the findings back. Never guess and ship.
- **No personal identifiers anywhere** — not in code, comments, docs, config, commit messages
  or on the web. No player name, nickname, or account trace. Git identity stays neutral.
- Commit and push to `claude/foe-alerting-cz8` only.

## State: built and unit-tested, never run against a live map

`src/bap/alerting/` (73 tests, all browser-free):

| module | job |
|---|---|
| `clock.py` | server-clock drift + Prague `HH:MM` (works without `tzdata`; EU DST rule tested against the tz database at both switches) |
| `labels.py` | province id → the guild's coordinate (file → generated grid → `#id`) |
| `schedule.py` | snapshot → `UnlockEvent`s; scopes `labeled`/`relevant`/`mine`/`all`; due-window logic |
| `render.py` | the message text |
| `notifiers.py` | Green API / webhook / console / null |
| `state.py` | the "already announced" log |
| `config.py` | `alerting.json` + secrets from env |
| `engine.py` | snapshot in → messages out (no browser) |
| `watcher.py` | the only browser glue: CDP, one tab, listen |

```bash
PYTHONPATH=src python3 -m pytest tests/unit/alerting -q          # 73 passed
PYTHONPATH=src python3 -m bap.alerting preview \
    dataset/api_samples/getBattleground.sample.json --at capture \
    --map-data dataset/api_samples/map_data.volcano_archipelago.sample.json
```

## Next steps

1. **Naming** — settle what `A1X` is (above), then generate/fill `province_labels.cz8.json`
   and switch `scope` to `labeled`.
2. **Green API** — the owner creates the instance and links a phone (use a spare number, not
   the main one). Then `bap-alert check --send "test"`.
3. **Live confirmation** — GBG was closed for ~4 days from 2026-09-07. When it reopens, confirm
   (a) `lockedUntil` really is "opens at" for provinces we don't own, and (b) the map asset's
   province ids match the season's map. The verification prompt is in
   `docs/FOE_ALERTING.md` §7; run it as a Chrome-MCP prompt, don't test blind.
4. Only after a clean `--dry-run` day should it post to the real group.
