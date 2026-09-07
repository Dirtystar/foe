# FoE Alerting (subproject)

One world (cz8), one job: tell the guild's WhatsApp group **when a province opens, and
whether that is an attack or a defence for us**.

```
16:25 🔵 A1X
```

`<time it opens, Prague> <🔴 attack | 🔵 defence> <the coordinate your guild uses>`

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
| **attack / defence** | `province.ownerId` vs `currentParticipantId` — ours → they will siege it (defence 🔵), theirs → we can siege it (attack 🔴) | ✅ |
| **coordinate** | — | ⚠️ **the game has no province names.** A province is an id (0…59) plus a flag position in the static map asset. `A1X` is a *guild* convention, so it has to be mapped once (see §4) |

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

Until a province is named, it is announced by its generated grid position (`F7`) and, failing
that, `#14` — the alert is never blocked on the naming being finished. The generated grid is a
*positional hint*, not a standard: GBG flags are hand-placed, not a lattice.

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

Timing knobs: `lead_minutes` (how far ahead to announce, default 10), `stale_minutes` (never
announce an opening older than this — matters after a restart), `quiet_hours` (e.g. `[23, 7]`
Prague; suppressed openings are marked handled, so the group is not hit by a burst at 07:00).

Each opening is announced **once**: the key is `provinceId:lockedUntil`, remembered in
`alert_state.json`, so a restart, a re-entry into GBG, or ten snapshots of the same map change
nothing. Openings that fall in the same tick share one message (one line each).

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

---

## 7. Still to confirm live (next season)

Everything above is built and unit-tested against a real captured payload, but two things can
only be confirmed with a live map:

1. **`lockedUntil` really is "opens at"** for provinces we do *not* own (confirmed by shape and
   by the ~4 h spread in the capture; worth watching one province cross its time).
2. **The map asset's province ids match the season's map** — i.e. the labels file stays valid
   until the map changes.

Both are a five-minute check once GBG reopens: run `bap-alert run --dry-run --verbose`, note a
line, and watch that province in the game at the announced minute.
