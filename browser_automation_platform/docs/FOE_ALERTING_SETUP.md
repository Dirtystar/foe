# FoE Alerting — setup guide

Getting from a fresh clone to "the group is getting alerts". Follow it top to bottom; every
step is checkable before the next one, and nothing is posted to a real group until §7.

For *why* it works the way it does — where the data comes from, why messages are batched, why
Green API — read `FOE_ALERTING.md`. This file is the how.

> **Language note.** This guide is in English because the repository's docs are; the app's own
> screens are in Czech. Say the word and it gets translated.

---

## 0. What you need

| | |
|---|---|
| **Python 3.11 or newer** | the only requirement. The alerter imports **nothing** outside the standard library — no pip install, no virtualenv, no build step |
| **A browser** | to open the control panel, and (for live running) the one already playing the game |
| **A WhatsApp account for the bot** | see §4. Use a spare number, not your main one |

Check your Python:

```bash
python3 --version        # Linux / macOS
py -3 --version          # Windows
```

Anything from 3.11 up is fine. If Windows says nothing is installed, get it from
<https://www.python.org/downloads/> and **tick "Add python.exe to PATH"** in the installer.

---

## 1. Get the code

```bash
git clone https://github.com/Dirtystar/foe.git
cd foe
git checkout claude/foe-alerting-cz8
```

The alerter lives on that branch. The `main`/farmer branches are a different application; don't
mix them.

---

## 2. Start the control panel

**Windows** — double-click **`foe-alerting.bat`** in `browser_automation_platform\`. If
Windows blocks it (see the troubleshooting table), double-click **`foe-alerting.py`** instead —
same thing, and Smart App Control does not block `.py`.

**Linux / macOS**:

```bash
cd browser_automation_platform
./foe-alerting.sh
```

Either way a browser opens on a page like `http://127.0.0.1:8765/?t=…`.

> **That URL is a password.** The `?t=…` token is what stops any other page open in your
> browser from talking to the panel behind your back — and the panel can send WhatsApp
> messages. Don't paste the URL into a chat, an issue, or a screenshot. The panel listens on
> `127.0.0.1` only, so nobody outside your machine can reach it at all.

Close the panel by closing the terminal window it opened, or Ctrl-C in it.

<details>
<summary>Running it by hand instead</summary>

```bash
cd browser_automation_platform
PYTHONPATH=src python3 -m bap.alerting ui \
    --map-data dataset/api_samples/map_data.volcano_archipelago.sample.json
```

Useful flags: `--port 9000`, `--no-browser`, `--config path/to/alerting.json`.
</details>

---

## 3. The panel, screen by screen

### Formát zprávy (message format)

The template for one line. The default is what the guild already writes by hand:

```
{time} {emoji} {label} {pct}     →     21:34 🔴 D4A [20%]
```

| placeholder | becomes |
|---|---|
| `{time}` | opening time in Prague, `HH:MM` |
| `{emoji}` | 🔴 attack / 🔵 defence |
| `{label}` | the guild's coordinate — `D4A` (see §5) |
| `{pct}` | the attrition badge as `[20%]`, **empty** when the game reports none |
| `{pct_num}` | the same number bare — `20` |
| `{side}` | the word `attack` / `defence` |
| `{id}` | the province id the game uses |

The preview underneath renders against a real captured battleground, so you see the actual
shape before anything is sent. **Uložit formát** writes it to `alerting.json`.

A province the game reports no percentage for prints no bracket at all — never `[0%]`, because
"no value" and "zero" are different things.

### Dávkování a rozsah (batching and scope)

| setting | what it does |
|---|---|
| **Předstih** | how many minutes before the *soonest* opening the alerter speaks. Default **4** |
| **Okno** | having spoken, it lists everything opening within this many minutes. Default **30** |
| **Rozsah** | which provinces count at all — see below |
| **Pravidlo barev** | how 🔴/🔵 is decided. Leave on `battle_type` until the live check in `FOE_ALERTING.md` §10 says otherwise |

Batching is the difference between ~52 messages a day and ~350. Widen the window and you get
fewer messages but longer notice, which is exactly when people stop reading them.

Scope:

| scope | announces |
|---|---|
| `labeled` | only provinces you named in §5 — the sharpest filter, and where you want to end up |
| `relevant` *(default)* | ours + commander `focus` marks + provinces we are already sieging |
| `mine` | only our provinces |
| `all` | everything — 60 provinces of noise |

### Labely provincií (province names)

The game has **no province names**: a province is an id (0–59) and a flag on the map. `A1X` is
your guild's convention, so it has to be typed once.

The panel starts with one row. Pick a province from the dropdown — it shows `#14 (C1C)`, where
`C1C` is a *generated* position in a 4×4 grid, matching the `A`–`D` / `1`–`4` shape your guild
uses. Type the real name next to it and press **+ Přidat** for the next one. **✕** removes a
row.

You do **not** have to name all 60. Anything unnamed is announced by its generated position, so
alerts work from day one and the naming can grow over time. Saving writes
`province_labels.<world>.json` — that file is gitignored, it is yours.

Once the file covers your front line, switch **Rozsah** to `labeled`.

### WhatsApp (Green API)

Covered in §4.

### Log

What the alerter decided and sent. Refreshes after every action and every 5 seconds. This is
the first place to look when something seems wrong — and it deliberately never contains the
panel's token, so it is safe to screenshot.

---

## 4. Green API, step by step

WhatsApp's official API **cannot post to a group at all** — neither can Twilio. Green API
drives a linked WhatsApp account, like WhatsApp Web does, which is why it can.

### 4.1 Create the instance

1. Register at <https://green-api.com/> and open the console at
   <https://console.green-api.com/>.
2. Create an instance on the **Developer** tariff (free).
3. Open the instance and note **`idInstance`** (an 11-digit number) and
   **`apiTokenInstance`** (a long hex string).
4. Scan the QR code with the phone that will send the messages. The instance state must become
   **`authorized`**.

> **Use a spare number.** Green API is an unofficial gateway. If WhatsApp objects to it, the
> account that carries the risk is the one you linked. That number must be a member of the
> group.

### 4.2 Find the group's chatId

A group chat id looks like `120363123456789012@g.us`. Easiest routes:

* the Green API console's chat list, or
* send one message *into* the group from the linked phone, then read the incoming webhook /
  `lastIncomingMessages` view in the console — the `chatId` is on it.

It always ends in `@g.us`. A id ending in `@c.us` is a single person, not a group.

### 4.3 Put them in the panel

Paste all three into the **WhatsApp** panel, then:

1. **Použít** — hold them for this run.
2. **Ověřit instanci** — calls `getStateInstance`. You want `authorized`. Anything else
   (`notAuthorized`, `blocked`, `starting`) means go back to the console; no message will send
   until this is right.
3. **Poslat testovací zprávu** — sends one real line to the group. Check the group.

### 4.4 Where the credentials live

By default they stay **in memory** and vanish when you close the panel. **Uložit na disk**
writes them to `alerting.secrets.json` with permissions `600` — never into `alerting.json`.
Both files, plus `alert_state.json` and the label files, are gitignored, so they cannot be
committed by accident.

Environment variables win over both, if you prefer them:

```bash
export GREEN_API_ID_INSTANCE=1101xxxxxx
export GREEN_API_TOKEN=xxxxxxxxxxxxxxxxxxxx
export GREEN_API_CHAT_ID=120363xxxxxxxxxxxx@g.us
```

### 4.5 What the free tier actually limits

Messages are **unlimited**. The limit is **3 chats per calendar month** and **1 instance**.
Alerting one group uses one chat, so the quota is not a concern — but the counter includes
chats you *receive* from, so turn incoming webhooks off in the console; a stranger messaging
the bot number would otherwise eat a slot. Exceeding it gives HTTP `466` / `QUOTE_EXCEEDED`.

---

## 5. A dry run before the group hears anything

```bash
cd browser_automation_platform
PYTHONPATH=src python3 -m bap.alerting run --config alerting.json --dry-run --verbose
```

It attaches to the Chrome you already play in, watches the world's tab, and prints what it
*would* send without sending it. Open Guild Battlegrounds on that world (or let the farmer run)
and the schedule refreshes itself.

Let it run for a day. You are checking two things: that the times are right, and that the
volume is bearable. If it is noisy, narrow the scope — not the batching.

---

## 6. Optional: split it in two

If the sending should survive your PC being off, run the two halves separately — the collector
where the game is, the scheduler on a small always-on box. `FOE_ALERTING.md` §7 has the detail;
the short version:

```bash
export ALERT_RELAY_SECRET="something long and random"   # same value on both sides
bap-alert serve   --config alerting.json --port 8770    # the always-on box
bap-alert collect --to http://<the box>:8770            # any machine playing cz8
```

Several people can run a collector. Only ever run **one** scheduler — it is the thing that
sends, and two of them means the group hears everything twice.

---

## 7. Going live

```bash
PYTHONPATH=src python3 -m bap.alerting run --config alerting.json
```

Set `"notifier": "green_api"` in `alerting.json` first (the panel does not switch it for you —
sending to a real group should be a deliberate edit).

---

## 8. When something is wrong

| symptom | cause |
|---|---|
| **Smart App Control blocked the launcher** (no "run anyway" button) | `.bat`/`.cmd`/`.ps1` carrying the mark of the web are blocked outright. Either run `foe-alerting.py` instead (`.py` is not on that list), or right-click the file → Properties → **Unblock**. Best avoided by unblocking the ZIP *before* extracting |
| Panel won't open, "port already in use" | another copy is running; close it or use `--port 9000` |
| Panel says **403 Forbidden** | the URL lost its `?t=…` token. Copy the whole line the terminal printed |
| Labels table says "Žádná data mapy" | started without `--map-data`. The launchers pass it for you |
| **Ověřit instanci** returns `notAuthorized` | the phone is not linked — rescan the QR in the Green API console |
| Test message says sent, group gets nothing | the `chatId` is wrong, or the linked account is not in that group |
| HTTP `466` / `QUOTE_EXCEEDED` | the 3-chats-a-month tariff limit (§4.5) |
| Scheduler says the snapshot is **TOO OLD** | no collector has fed it for 3.5 h — open GBG somewhere, or start a collector |
| `refusing to start without a shared secret` | set `ALERT_RELAY_SECRET` on the scheduler and every collector |
| Collector logs `HTTP 401 — check ALERT_RELAY_SECRET` | the two sides have different secrets |
| Alerter is silent while GBG is open | nothing is *in scope* — check **Rozsah**, and that the world matches `world` in the config |
| Times look shifted | the alerter corrects against the game's own clock; if they are still off, say so — do not "fix" it by changing your PC clock |

---

## 9. What it will never do

Worth knowing, because it is enforced in the code and not just policy: the alerter is
**read-only towards the game**. It never clicks, never sends a request to the game, and never
calls the `setSignal` endpoint that would write the commander's marks. It only reads responses
the browser already received, and posts text to a messaging gateway.
