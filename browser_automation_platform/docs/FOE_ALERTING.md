# FoE Alerting (subproject)

One world (cz8), one job: tell the guild's WhatsApp group **when a province opens, and
whether that is an attack or a defence for us**.

```
21:34 🔴 D4A [20%]
21:48 🔴 B4H [20%]
21:52 🔵 C2S [20%]
```

`<time it opens, Prague> <🔴 attack | 🔵 defence> <the coordinate your guild uses> [<attrition %>]`

The format copies what the guild already types by hand, down to the bracket. Messages are
**batched** — one message per window, not one per province (§5).

It is a **separate subproject** on its own branch: it reuses the GBG reader
(`bap.forge.gbg_data`) read-only and shares nothing with the farmer's clicking code. It never
sends a request to the game, never clicks, and never writes anything to the game — it listens
to data the browser already receives, and posts text to a messaging gateway.

---

## 1. Do we have the data? (short answer: yes, except the names)

Everything comes from one `GuildBattlegroundService.getBattleground` response — the payload the
game sends whenever GBG is opened or refreshed:

| Line of the message | Where it comes from | Status |
|---|---|---|
| **time it opens** | `province.lockedUntil` — unix second when the cooldown ends | ✅ already parsed; corrected against the server clock (`TimeService`) so a wrong PC time can't shift it |
| **attack / defence** | `province.isAttackBattleType` — a per-province flag, independent of who owns it | ⚠️ the field exists and fits (38 attack / 22 defence in the capture, matching the ≈2:1 red/blue ratio in the group's own messages), but its meaning is **not confirmed live** — see §8. `side_rule` switches back to the ownership rule |
| **coordinate** | — | ⚠️ **the game has no province names.** A province is an id (0…59) plus a flag position in the static map asset. `A1X` is a *guild* convention, so it has to be mapped once (see §4) |
| **attrition %** | `province.gainAttritionChance` | ✅ values in the capture are exactly {20, 40, 60, 100} — the same set the group writes. Absent on every province we own (22 of 22), and an absent value prints **no bracket**, never `0%` |

The percentage is also why the colour cannot be the ownership rule: the group's *blue* lines
carry a `[20%]`, and the field is missing on everything we own. A blue line therefore cannot
mean "our province".

Two more things the payload gives us for free, and we use them:

- **commander marks** (`battlegroundParticipants[].signals`): `focus` = "Cíl/Útok",
  `ignore` = "Stop". A province the commander marked Stop is never announced as an attack
  (it is still announced as a defence — a Stop mark doesn't mean we let it fall).
- **conquest progress**: whether our guild is already sieging a province — used to decide what
  is worth announcing at all.

**Freshness is not a problem.** One snapshot lists every opening for the next several hours
(in the captured sample: 52 of 60 provinces, spanning ~3.7 h ahead). So the alerter does not
need its own polling — it only needs *a* reasonably recent snapshot, and it gets one every time
GBG is entered on that world. Running the farmer on cz8 refreshes it constantly for free;
`--refresh-minutes` exists for the case where nothing else is driving the tab.

**FoE Helper is not needed.** The marks, the lock times and the owner all come from the game's
own JSON. (Helper would add nothing here and would be one more moving part.)

---

## 2. Why Green API

Group messages rule out most options:

| Gateway | Groups? | Verdict |
|---|---|---|
| **Green API** | ✅ a group is just a `chatId` ending in `@g.us` | **chosen** — free developer tier is enough for this volume |
| Meta WhatsApp Cloud API (official) | ❌ 1:1 template messages only | cannot post to a group at all |
| Twilio WhatsApp | ❌ | same limitation |
| whatsapp-web.js / Baileys (self-hosted) | ✅ | free, but you host and babysit a Node service + session |
| Telegram | ✅ and trivially free | worth knowing as a fallback; not WhatsApp |

Green API drives a **linked WhatsApp account** (like WhatsApp Web). That account must be in the
group. Prefer a spare number: an unofficial gateway on your main number is the account that
takes the risk if WhatsApp objects.

The transport is one method (`send(text) -> bool`), so switching later is a config change:
`notifier` can be `green_api`, `webhook` (POST the text anywhere — a self-hosted bridge, a
Telegram relay), `console`, or `null`.

---

## 3. Setup

```bash
pip install -e .            # bap-alert is installed as a console script
cp alerting.example.json alerting.json
```

**Green API** (~5 minutes): create an account, create an instance, scan the QR with the phone
that will send the messages, then note *idInstance* and *apiTokenInstance*.

Credentials belong in the environment, not in the file:

```bash
export GREEN_API_ID_INSTANCE=1101xxxxxx
export GREEN_API_TOKEN=xxxxxxxxxxxxxxxxxxxx
export GREEN_API_CHAT_ID=120363xxxxxxxxxxxx@g.us
```

The group's `chatId` is easiest to read from the Green API console (or from the
`getContacts` / incoming-webhook view) — it always ends in `@g.us`.

Check it before pointing it at the guild:

```bash
bap-alert check --config alerting.json                 # is the instance authorized?
bap-alert check --config alerting.json --send "test"   # does the group receive it?
```

---

## 4. Naming the provinces ("A1X")

The game has no names, so the guild's own naming lives in one file. Generate a template from
the map asset (the `map/data/<mapId>` body — the alerter also picks it up live), then replace
the generated values:

```bash
bap-alert labels map_data.json --write province_labels.cz8.json
```

```json
{
  "map_id": "volcano_archipelago",
  "labels": { "14": "A1X", "15": "A2", "17": "B1" }
}
```

The generator uses a **4×4 grid**, because that is the shape the guild says out loud: a sector
letter `A`–`D`, a sector number `1`–`4`, then a per-province letter (`D4A`, `C3Y`, `B4H`, and
plain `C1` when it is the only one in its cell). So a generated label already lands in the
right sector and usually only the trailing letter has to be corrected by hand.

Until a province is named, it is announced by its generated grid position (`C3B`) and, failing
that, `#14` — the alert is never blocked on the naming being finished. The generated grid is a
*positional hint*, not a standard: GBG flags are hand-placed, not a lattice, so the sector a
flag falls into near a boundary may not be the one the guild calls it.

**Which map?** Each GBG season can use a different map, and province ids belong to that map.
Keep one labels file per map and switch `labels_file` when the map changes (the `labels`
command prints the map id it read).

---

## 5. What gets announced (`scope`)

A 60-province map would be noise, so:

| scope | announces |
|---|---|
| `labeled` | only provinces named in the labels file — *the guild's own front line*, the sharpest filter |
| `relevant` *(default)* | ours + commander `focus` marks + provinces we are already sieging |
| `mine` | only our provinces (defence watch) |
| `all` | every locked province |

Once the labels file describes the front line, `labeled` is usually the right answer.

### Batching — why the group is not notified 350 times a day

A 60-province map unlocks roughly **14.6 provinces an hour** (measured on the captured
snapshot: 52 openings across 3.5 h). One message per opening is ~350 a day, and they barely
ever share a minute, so naive grouping saves nothing.

Instead the alerter stays quiet until the **soonest unannounced opening** is
`trigger_lead_minutes` away, then sends **everything opening within `window_minutes`** as one
message:

| lead | window | messages/day | lines/message | notice on the first line |
|---|---|---|---|---|
| 3 min | 15 min | 91 | 3.7 | 3 min |
| **3–5 min** | **30 min** | **52** | **6.5** | **3–5 min** |
| 3 min | 60 min | 26 | 13.0 | 3 min |
| 10 min | 60 min | 32 | 10.4 | 10 min |

The default is **4 min / 30 min** — a ~6× cut, and it matches what the guild does by hand
(their messages run 3–6 lines with the first opening 1–7 minutes out). A wider window sends
fewer messages but pushes the median notice past half an hour, which is where people stop
reading.

When a **later snapshot adds an opening inside a window already announced**, the whole window
is re-sent rather than a bare delta, so the newest message in the group is always the complete
picture — again mirroring the guild's habit of re-posting an updated list.

Other timing knobs: `stale_minutes` (never announce an opening older than this — matters after
a restart), `quiet_hours` (e.g. `[23, 7]` Prague; suppressed openings are marked handled, so
the group is not hit by a burst at 07:00).

Each opening is announced **once as a trigger**: the key is `provinceId:lockedUntil`,
remembered in `alert_state.json`, so a restart, a re-entry into GBG, or ten snapshots of the
same map change nothing.

---

## 6. Running

Dry run first — decides everything, sends nothing:

```bash
bap-alert run --config alerting.json --dry-run --verbose
```

Live:

```bash
bap-alert run --config alerting.json
```

It attaches to the Chrome you are already using (CDP, same endpoint as the farmer), picks the
**cz8 tab only**, and listens. Open GBG on that world (or let the farmer run) and the schedule
refreshes itself.

Offline, from a saved capture — no browser, no game:

```bash
bap-alert preview dataset/api_samples/getBattleground.sample.json --at capture \
    --map-data dataset/api_samples/map_data.volcano_archipelago.sample.json
```

`preview` prints the schedule and then the first batch exactly as the group would receive it;
`--window` tries a different batch window without editing the config.

---

## 7. Still to confirm live (next season)

Everything above is built and unit-tested against a real captured payload, but four things can
only be settled against a live map. **Do not guess these — run §8 and bring the findings back.**

1. **The colour rule.** Does `isAttackBattleType` really correspond to what the guild calls
   attack vs defence? The evidence for it is circumstantial (ratio, and the fact that the
   ownership rule is ruled out by blue lines carrying a `[20%]`). The farmer's own model
   annotates the same field as "attack vs negotiate", which is a *different* reading — so
   somebody has it wrong and only the live map says who.
2. **`lockedUntil` really is "opens at"** for provinces we do *not* own (supported by shape and
   by the ~3.7 h spread in the capture; worth watching one province cross its time).
3. **`gainAttritionChance` is the badge the guild reads as `[20%]`** — i.e. the number in the
   message equals the number on the province in the game.
4. **The map asset's province ids match the season's map** — i.e. the labels file stays valid
   until the map changes.

Until #1 is settled, `side_rule` in `alerting.json` switches between the two candidates
(`battle_type`, the default, and `owner`) without touching code.

---

## 8. The live verification prompt

GBG reopens around 2026-09-11. Paste the block below to an AI that has Chrome MCP access, with
GBG open on the watched world. It is **read-only**: it observes traffic and the screen, sends
nothing to the game, clicks nothing, and never touches the `setSignal` write endpoint.

```text
You have Chrome MCP access to a browser where Forge of Empires is open on Guild
Battlegrounds. This is a READ-ONLY observation task.

Hard rules:
- Do not click anything in the game. Do not send any request to the game.
- Do not call any endpoint that writes (in particular anything named setSignal).
- Only read what the page already shows and what the network already delivered.

Capture the most recent GuildBattlegroundService.getBattleground response body from the
network log. Then answer these four questions, quoting the raw JSON you relied on.

1) COLOUR RULE. Pick 6 provinces that are visible on the map: 3 whose JSON has
   "isAttackBattleType": true, and 3 where the key is absent. For each, report what the
   GAME shows on that province — is it marked/treated as one the guild attacks, or one it
   defends? Say explicitly whether "isAttackBattleType" lines up with attack-vs-defence,
   or with something else (for example fighting vs negotiating). If it lines up with
   nothing visible, say that.

2) OWNERSHIP CROSS-CHECK. For those same 6, report "ownerId" and the response's
   "currentParticipantId", and whether the province belongs to our guild. The question
   being tested: is the attack/defence split independent of who owns the province?

3) ATTRITION BADGE. For 4 provinces that have "gainAttritionChance", report the number in
   the JSON and the percentage the game displays on that province. Do they match? Also
   check 2 provinces we own: the key should be absent, and report what (if anything) the
   game shows there instead.

4) LOCK TIME. Pick one province we do NOT own with a "lockedUntil" a few minutes out.
   Convert it to local time, then watch that province. Report what happens at that minute
   and whether "opens at / becomes attackable" is the right description.

Also report: the map id, the total number of provinces, and the lowest and highest
province id, so the labels file can be checked against this season's map.
```

Then bring the answers back. #1 decides `side_rule`; #3 confirms the `[20%]` source; #4
confirms the schedule itself; the map id and id range confirm the labels file.
