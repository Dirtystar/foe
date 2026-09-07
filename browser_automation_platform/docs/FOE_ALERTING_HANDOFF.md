# FoE Alerting — handoff for a fresh session

This subproject was split off from the farmer's session on purpose. Everything it needs lives
on the branch `claude/foe-alerting-cz8`; the farmer lives on
`claude/browser-automation-architecture-5784h1` and the two must not be mixed. **Read
`docs/FOE_ALERTING.md` first** — it is the design and the rationale;
`docs/FOE_ALERTING_SETUP.md` is the step-by-step setup guide (install, panel, Green API,
troubleshooting). This file only carries the context a fresh session cannot read out of the
code.

## What this is

Guild Battlegrounds alerting for **one world (cz8) only**. It posts batched province openings
into the guild's WhatsApp group, in the format the guild already types by hand:

```
21:34 🔴 D4A [20%]
21:48 🔴 B4H [20%]
21:52 🔵 C2S [20%]
```

`<time it opens, Prague> <🔴 attack | 🔵 defence> <the guild's coordinate> [<attrition %>]`

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
- **Attack vs defence** = `province.isAttackBattleType`, a per-province flag independent of
  ownership (`side_rule: battle_type`, the default). The old ownership rule is **ruled out by
  the owner's own screenshots**: their blue lines carry a `[20%]`, and `gainAttritionChance` is
  absent on every province we own (22 of 22 in the capture), so blue cannot mean "ours". The
  flag's meaning is still unconfirmed live — `side_rule: owner` switches back.
- **`[20%]` = `province.gainAttritionChance`**, straight from the payload. Values in the
  capture are exactly {20, 40, 60, 100}, the same set the guild writes. No OCR: the farmer's
  vision-based `weakening.py` reads the *player's own* attrition on the battle screen, which is
  a different number — nothing was ported from that branch.
- **Batching, not one message per opening.** The map unlocks ~14.6 provinces/hour (measured),
  so per-opening messages are ~350/day. The engine waits until the soonest unannounced opening
  is `trigger_lead_minutes` away, then sends the whole `window_minutes` in one message —
  4/30 min by default, ~52 messages/day, 6.5 lines each. A newcomer landing inside an already
  announced window re-sends that whole window (the owner asked for re-send, not a delta).
- **Commander marks are honoured**: `ignore` ("Stop") suppresses a province we do *not* own —
  we are told not to fight there — and never one of ours, whatever colour it is shown in.
  (This is now tied to ownership, not to the displayed colour, because the colour no longer
  implies ownership.) `focus` widens the default scope. Marks are read-only — the `setSignal`
  write endpoint must never be called.
- **Each opening triggers exactly once**, keyed `provinceId:lockedUntil`, remembered in
  `alert_state.json` across restarts. It can still be *listed again* in a re-sent window.

## Naming — settled

`A1X` is **the guild's own notation; the game ships no province names.** Confirmed from the
owner's screenshots of the group. The shape is `[A–D][1–4][letter]` — a 4×4 sector grid with a
per-province letter (`D4A`, `C3Y`, `B4H`, and plain `C1` when it is alone in its cell), so
`auto_labels` now generates a 4×4 grid with an uppercase suffix. A generated label lands in the
right sector and usually only the trailing letter needs correcting by hand.

Still to do: fill `province_labels.cz8.json` against the live map and switch `scope` to
`labeled`. Without it `relevant` announces ~195 openings/day, which is too much for the group
even after batching.

## The open questions

1. **Does `isAttackBattleType` really mean attack vs defence?** The owner's answer was "Útok a
   Obrana, tak jsou ty provincie rozdělené — nevím jaký je v tom pattern", so he cannot settle
   it either. The farmer's `gbg_data/model.py` annotates the same field as "attack vs
   negotiate" — a different reading. Only the live map decides. Prompt is ready in
   `docs/FOE_ALERTING.md` §10.
2. **Where the scheduler runs.** The split is built; no host is chosen or paid for,
   so nothing is deployed. Budget is ~$10/month and the owner will not buy a machine.

## Standing rules from the owner

- **No blind testing.** When something can only be settled against a live game, produce a
  ready-to-paste prompt for an AI with Chrome MCP access; the owner runs it in another chat and
  brings the findings back. Never guess and ship.
- **No personal identifiers anywhere** — not in code, comments, docs, config, commit messages
  or on the web. No player name, nickname, or account trace. Git identity stays neutral.
- Commit and push to `claude/foe-alerting-cz8` only.

## State: built and unit-tested, never run against a live map

`src/bap/alerting/` (119 tests, all browser-free):

| module | job |
|---|---|
| `clock.py` | server-clock drift + Prague `HH:MM` (works without `tzdata`; EU DST rule tested against the tz database at both switches) |
| `labels.py` | province id → the guild's coordinate (file → generated 4×4 grid → `#id`) |
| `schedule.py` | snapshot → `UnlockEvent`s; scopes; the two colour rules; `plan_batch` (the batching window) |
| `render.py` | the message text |
| `notifiers.py` | Green API / webhook / console / null |
| `state.py` | the "already announced" log |
| `config.py` | `alerting.json` + secrets from env |
| `engine.py` | snapshot in → messages out (no browser) |
| `watcher.py` | the only browser glue: CDP, one tab, listen |
| `relay.py` | the collector/scheduler split: forward snapshots, receive them, auth |
| `webui.py` | `bap-alert ui` — the local control panel (format, labels, credentials, log) |

Launchers `foe-alerting.sh` / `foe-alerting.bat` start the panel with no install step (the
alerter has zero third-party imports — verified, not assumed). **The `.bat` has never been
run on Windows** — no Windows in the build environment — so treat its first run as untested.

```bash
PYTHONPATH=src python3 -m pytest tests/unit/alerting -q          # 119 passed
PYTHONPATH=src python3 -m bap.alerting preview \
    dataset/api_samples/getBattleground.sample.json --at capture \
    --map-data dataset/api_samples/map_data.volcano_archipelago.sample.json
```

## Deployment — built

The owner will **not** buy a separate machine and has a **~$10/month** budget. The job splits
cleanly, and only the cheap half needs to be always-on:

- **Collector** — needs the game, a browser and an account. Does *not* need to run 24/7: one
  snapshot covers ~3.7 h ahead, so it only has to refresh every couple of hours. Runs on
  whatever machine is playing; the farmer on cz8 refreshes GBG for free.
- **Scheduler + sender** — needs a clock and internet, nothing else. No game credentials, so a
  compromise there cannot reach the account. This is the piece that belongs on a small VPS
  (~$0–6/month, inside budget).

A headless-Chrome collector in the cloud was **rejected**: a WebGL client on a GPU-less VPS
blows the budget on its own, and it would need a second in-guild game account, which is against
InnoGames' terms and puts the guild at risk. The owner was told this plainly and chose the
split; his fallback is "runs when my PC runs, someone else covers the rest", which the split
supports — several designated collectors, not random members (he explicitly rejected relying on
whoever happens to open GBG).

Both halves exist now: `bap-alert collect --to <url>` and `bap-alert serve` (`relay.py`,
`docs/FOE_ALERTING.md` §7). The wire format is the game's raw response body, re-parsed by the
same reader on the far side, authenticated with a shared secret in `Authorization: Bearer`
(`ALERT_RELAY_SECRET`); the scheduler refuses to start without one. Several collectors are
fine — the scheduler keeps the newest snapshot and is the single thing that sends.

The stale cutoff is in too: past `max_snapshot_age_minutes` (default 210) the engine stops
sending and says so once, then resumes when a collector returns. Old times look plausible while
being wrong, which is worse than silence.

**Never run against a live game or a real VPS** — verified end to end as two local processes
against the captured payload.

## Next steps

1. **Live confirmation** — GBG reopens ~2026-09-11. Run the §10 prompt in
   `docs/FOE_ALERTING.md` and bring the findings back. It settles `side_rule`, the `[20%]`
   source, `lockedUntil`, and the map/id range. Don't test blind.
2. **Labels** — fill `province_labels.cz8.json` from the live map, switch `scope` to `labeled`.
3. **Green API** — the owner creates the instance and links a phone (use a spare number, not
   the main one). Then `bap-alert check --send "test"`. Free Developer tier: unlimited
   messages, but only **3 chats per calendar month** and 1 instance — the group is one chat, so
   disable incoming webhooks so a stray inbound chat cannot burn a slot.
4. **Host the scheduler** — the code is ready, nothing is deployed. ~$5/month VPS, no game
   credentials on it. Until then `bap-alert run` (single process) is still the way.
5. Only after a clean `--dry-run` day should it post to the real group.
