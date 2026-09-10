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
| **attack / defence** | `province.isAttackBattleType` — a per-province flag, independent of who owns it | ✅ **visually confirmed live** — see §8. Two controlled same-owner-colour pairs: `true` is a maroon banner on the province, absent is navy. `side_rule` still switches back to the ownership rule if a wider check ever disagrees |
| **coordinate** | `province` id + flag position, run through the map's geometry | ✅ **computed, not guessed** — see §4. A GBG map is a centred hexagon of provinces; the code is the compass sector and the ring out from the centre. 13 of 14 codes read live off the game matched one computed from nothing but the map asset |
| **attrition %** | `province.gainAttritionChance` | ✅ values in the capture are exactly {20, 40, 60, 100} — the same set the group writes. Absent on every province we own (22 of 22), and an absent value prints **no bracket**, never `0%` |

The percentage is also why the colour cannot be the ownership rule: the group's *blue* lines
carry a `[20%]`, and the field is missing on everything we own. A blue line therefore cannot
mean "our province".

Two more things the payload gives us for free, and we use them:

- **commander marks** (`battlegroundParticipants[].signals`): `focus` = "Cíl/Útok",
  `ignore` = "Stop". A Stop mark silences a province we do *not* own — we are told not to fight
  there — and never one of ours, whichever colour it is shown in.
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

**Step-by-step, including Green API and the launchers: [`FOE_ALERTING_SETUP.md`](FOE_ALERTING_SETUP.md).**
The short version — the alerter imports nothing outside the standard library, so there is
nothing to install:

```bash
cd browser_automation_platform
./foe-alerting.sh           # Windows: double-click foe-alerting.bat
```

`pip install -e .` also works and puts `bap-alert` on PATH, but it drags in the farmer's
dependencies (playwright, pydantic) that the alerter never uses.

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

Or do the whole thing in the panel (`bap-alert ui`, §9): paste the credentials, press *Ověřit
instanci*, then *Poslat testovací zprávu*. The panel can also keep them for you without putting
them in `alerting.json`.

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

The generator **computes the real code, not a guess**: a GBG map is a centred hexagon of
provinces — one centre, then rings of 6, 12, 18, 24 — and the code the game shows is exactly
that geometry: a compass sector (`A`–`F`) and how many rings out from the centre (`2`–`5`),
plus a letter for which province in that cell. Confirmed against a live 61-province map: 13 of
14 codes read off the game matched what `hex_cells`/`ring_labels` compute from nothing but the
map asset's flag positions — the one miss was one ring off, most likely a transcription slip
reading the screen, not a scheme error.

So most provinces need **no typing at all**. `LabelBook` uses the settings confirmed live by
default, and refits itself against whatever the guild *has* named as soon as there are a few —
so naming five provinces can improve the computed guess for the other fifty-five, not just
those five. Naming stays necessary only for a season whose map isn't a centred hexagon (then
it falls back to a positional grid hint) or when the guild simply prefers a different word for
a province than the code the game shows.

Until a province is named, it is announced by its computed code (`C3B`) and, failing that,
`#14` — the alert is never blocked on the naming being finished.

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

## 7. Running it split: collector and scheduler

`bap-alert run` does everything in one process, which means the machine that plays the game is
also the machine that must be awake when a province opens. Two problems follow: the alerts stop
when that PC sleeps, and running it on several people's PCs posts every message once per
person.

So the job splits along its natural seam:

```
  someone's browser                        a small always-on box
  ┌────────────────────┐   snapshot   ┌──────────────────────────┐
  │ bap-alert collect  │ ───────────► │ bap-alert serve          │ ──► WhatsApp
  │ needs the game     │   HTTP+token │ needs a clock            │
  └────────────────────┘              └──────────────────────────┘
   several of these, whoever is           exactly one of these
   online; duplicates are harmless        — that is what makes the
                                          message arrive once
```

**The collector** watches one world's tab exactly like `run` does, but decides nothing: it
forwards the game's own response body verbatim. It holds no WhatsApp credential, so handing it
to guild members costs nothing if one of them is careless.

**The scheduler** keeps the newest snapshot, runs the engine, and posts. It never sees a game
account. It is the piece that fits a ~$5/month VPS: no browser, no GPU, a few hundred MB.

```bash
# on the always-on box
export ALERT_RELAY_SECRET="something long and random"
bap-alert serve --config alerting.json --port 8770

# on any machine that plays cz8
export ALERT_RELAY_SECRET="the same value"
bap-alert collect --to http://<the box>:8770 --config alerting.json
```

The wire format is the game's raw body, re-parsed on the far side by the same reader, so the
two halves cannot disagree about what the game said. The shared secret goes in
`Authorization: Bearer`; the scheduler refuses to start without one, because an open relay
would let anyone drive the guild's alerts. `GET /health` needs no secret, so a host checker can
watch the process without holding a credential.

### The stale-snapshot cutoff

A snapshot describes about 3.7 h of openings. Past that the times still *look* plausible while
being wrong, which is worse than silence — so beyond `max_snapshot_age_minutes` (default 210,
i.e. 3.5 h) the scheduler stops sending and says so once, then resumes the moment a collector
comes back. This matters most in the split setup, where "nobody is playing right now" is a
normal state rather than a fault.

---

## 8. Confirmed live, and what's still open

Two rounds against a live map (`waterfall_archipelago`, 61 provinces, cz8) settled most of
what could only ever be settled by playing, not testing:

**Confirmed:**

- **The colour rule.** `isAttackBattleType: true` is a maroon province banner; the key absent
  is navy — checked on two pairs that share an owner colour, specifically to rule out the
  banner just being ownership in disguise. Small sample (2 pairs), but controlled, so
  `side_rule: battle_type` stays the default with real evidence behind it now, not just a
  ratio. The farmer's own model annotates the same field as "attack vs negotiate" — a
  different reading of the same flag — so treat that comment as outdated, not as a second
  vote.
- **The map asset matches the live season.** Both captures agree: `waterfall_archipelago`,
  61 provinces, ids 0–60 — the labels file and the computed codes are built from the real
  thing, not a guess from an old sample.
- **The `[20%]` badge's *source*.** `gainAttritionChance` is absent on every province either
  capture's own guild owned — 96 provinces across two maps and two worlds, zero exceptions.
  What is *not* independently confirmed is that number against a screenshot of the badge as
  drawn on the map tile itself: the one click-through checked showed a different pair of
  numbers (50%/50%, next to *Negotiate*/*Defend* — a different game mechanic, not this one).
  The omission pattern is strong enough on its own to keep trusting the field; a screenshot of
  the on-map badge next to its JSON value would close the loop completely.
- **Province naming.** See §4 — computed from geometry, not guild folklore. (One curiosity
  from the live check, not a blocker: clicking a province opens a detail panel that *does*
  show a name — `A3A: Micianary` — not present in either JSON payload captured. Whether that
  prefix is the game's own or FoE Helper injecting into the native panel is unresolved; it
  doesn't matter for alerting either way, since the ring/sector code is what gets used.)

**Still open:**

- **`lockedUntil` really is "opens at"** for a province we do not own. Nothing in either
  capture had a foreign province within watching distance of unlocking — this is blocked on
  real timing, not on tooling, and isn't urgent: the field's shape and the ~3.7 h spread of
  openings already fit "opens at" and nothing else makes sense of the data.
- **A guild-name field on the detail panel didn't match the province's owner** in the second
  capture (it showed *our* guild's name on a province owned by someone else). Not investigated
  — noted rather than guessed at, and not something alerting depends on.

If a wider check of the colour rule ever disagrees, `side_rule` in `alerting.json` switches to
the ownership rule (`owner`) without touching code.

---

## 9. The control panel (`bap-alert ui`)

```bash
bap-alert ui --map-data dataset/api_samples/map_data.volcano_archipelago.sample.json
```

A local page on `127.0.0.1` — the four things the command line is bad at:

* **message format** — a template (`{time} {emoji} {label} {pct}`, plus `{pct_num}`, `{side}`,
  `{id}`) previewed live against a captured snapshot, so a new layout is tried before it ever
  reaches the group;
* **labels** — a row per province, the computed ring/sector code beside each (usually
  already what the game shows), type an override only where the guild wants a different word;
* **Green API** — paste `idInstance` / `apiTokenInstance` / group `chatId`, check the instance
  is authorised, and send one test message;
* **log** — what was decided and sent, refreshed every 5 s.

It is a web page rather than a desktop window because this subproject deliberately has no
dependencies beyond the standard library, and the scheduler half is meant to run on a headless
box where there is no desktop at all.

**It holds credentials, so it is locked down**: it binds loopback only, every request needs the
random token in the URL printed at startup (this is what stops any other page in your browser
POSTing to it), and the `Host` header must be loopback so DNS rebinding cannot reach it. Treat
that URL like a password — it is not written to the log panel for that reason.

Credentials typed into the page stay **in memory** until you press *Uložit na disk*, which
writes them to `alerting.secrets.json` (mode 600) — never into `alerting.json`, and both files
are gitignored.

---

## 10. The live capture prompt

**Already run twice; results are folded into §8.** Kept here as a record and for the next
season's map (province ids and the geometry both need re-confirming whenever the map changes).

For an AI with **Chrome MCP** access, with GBG open on the watched world. It collects the
mapping data (§4) and settles the open questions (§8) in one pass. It is **read-only**:
it observes traffic and the screen, sends nothing to the game, clicks nothing inside it, and
never touches the `setSignal` write endpoint.

Parts A and E are the ones that matter — without the map asset there is no province mapping at
all. Everything else is a bonus that can come later.

```text
You have Chrome MCP access to a browser with Forge of Empires open on Guild
Battlegrounds. This is a READ-ONLY observation task on a live game.

HARD RULES
- Do not click anything inside the game. Do not send any request to the game.
- Never call setSignal or any other endpoint that writes.
- Only read what the page already shows and what the network already delivered.
- If something would need a click in the game to answer, skip it and say so.

PART A — the two payloads. This is the important part.
A1. From the network log, take the most recent
    GuildBattlegroundService.getBattleground response and paste its "responseData"
    object verbatim, complete, in a ```json block.
A2. Find the static map asset request — the URL looks like .../map/data/<mapId>.
    Paste its whole body verbatim in a second ```json block. It should contain
    "size", "bgTextures" and "provinces" with an "id" and a "flag" {x, y} each.
A3. Report both request URLs, but STRIP any session token from them (anything like
    ?h=... ). Do not paste cookies or headers.

PART B — pictures of the map.
B1. One screenshot of the whole battleground map at default zoom, all provinces visible.
B2. Two or three close-ups of different corners, close enough that individual province
    flags are clearly distinguishable.
B3. Before sending: check that no player name, avatar, chat, message list or friends
    list is visible anywhere in the images, and crop it out if it is. Guild names are
    fine. Do not include any screenshot you are unsure about.

PART C — four things only a live map can settle.
C1. COLOUR RULE. Pick 6 provinces visible on the map: 3 whose JSON has
    "isAttackBattleType": true, and 3 where that key is absent. For each, report what
    the GAME shows — is it one the guild attacks, or one it defends? State plainly
    whether "isAttackBattleType" lines up with attack-vs-defence, with something else
    (fighting vs negotiating, say), or with nothing visible.
C2. OWNERSHIP CROSS-CHECK. For those same 6, report "ownerId" and the response's
    "currentParticipantId". The question: is the attack/defence split independent of
    who owns the province?
C3. ATTRITION BADGE. For 4 provinces that have "gainAttritionChance", report the JSON
    number and the percentage the game displays on that province. Do they match? Also
    check 2 provinces our own guild owns: the key should be absent — report what, if
    anything, the game shows there instead.
C4. LOCK TIME. Pick one province we do NOT own whose "lockedUntil" is a few minutes
    out. Convert it to local time, watch that province, and report what happens at
    that minute — is "opens at / becomes attackable" the right description?

PART D — does the game name provinces at all?
D1. Inspect a few provinces (hover, side panel, and the page DOM around a flag).
    Does the game display ANY name, code, letter or label for a province anywhere?
D2. If yes: say exactly where it appears, and give three examples with their province
    ids. If no: say so plainly.
This decides whether province naming can ever be read from the game or has to stay a
hand-written list.

PART E — map identity.
E1. The map id, from the asset URL and from the body if present.
E2. How many provinces there are, and the lowest and highest province id.
E3. The "bgTextures" asset names (they usually carry the map name).

OUTPUT
Put the two ```json blocks first, then short answers to A3 and C–E. Attach the
screenshots. Where something could not be determined, say so instead of guessing.
```

What each part is for: **A2 + E** make the province mapping possible at all — the flag
coordinates are what the panel draws and what the ring/sector codes are computed from. **A1**
confirms the province ids match this season's map. **B** turns the panel's flag map into
something you can read next to the game. **C1** decides `side_rule`; **C3** confirms the
`[20%]` source; **C4** confirms the schedule. **D** decides whether §4 stays manual forever.
