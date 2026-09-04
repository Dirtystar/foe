# Design note — GBG structured-data reader (observe the game WebSocket via CDP)

_Design only. No implementation. Proposes a read-only way for the product to learn
**which provinces exist, who owns them, and when they open**, by observing the game's
own data — not by reading pixels and not by depending on any third-party tool._

Status: **feasibility CONFIRMED — real payload captured.** The go/no-go probe is done: a
live HAR gave us the actual data over HTTP POST `/game/json`. The concrete schema, the
field→app mapping, and the CDP mechanism now live in **`GBG_API_SCHEMA.md`**, with sanitized
sample payloads in `dataset/api_samples/`. Read this note for the rationale/shape; read
`GBG_API_SCHEMA.md` for the real fields. (Correction: the data is HTTP POST responses, not
WebSocket frames — same CDP connection, `Network.responseReceived` + `getResponseBody`.)
Sibling of `GBG_MAP_FACTS.md` and `M6_AUTONOMOUS_CLICKING_DESIGN.md`.

---

## 1. Problem this solves

`GBG_MAP_FACTS.md` established that the GBG **map view does not contain the facts we
need**: banners show building fractions (`X/2`), not weakening percentages; province
identity/ownership is encoded only in colors; and **when a province will open is not
on screen at all**. The pixel pipeline therefore returns `pct=None` on the map and
can never report unlock timing.

Two product questions we cannot answer from pixels:

1. **Identify the provinces** — stable name/id, which guild owns each, which world.
2. **Know when a province will open** — the unlock time, ahead of time.

Both facts *do* exist — they travel between the game client and its server as
structured JSON. We should read them at the source.

## 2. Why not FoE Helper (the third-party tool)

FoE Helper's "Web Requests" module can push exactly this sector data (`name`, `guild`,
`world`, unlock `time`, `battletype`, `vp`, `neighbors`) to a server. It is a useful
**documentation of the data model** — it tells us precisely which fields are worth
extracting. But building on it is rejected:

- It is a **browser extension we do not ship, version, or control.** A contributor
  who hasn't installed and configured it produces **no data** — the capability
  silently disappears. Unacceptable for a product foundation.
- It offers **no data we cannot get ourselves.** FoE Helper has no privileged access;
  it reads the game's own WebSocket/JSON traffic in the page — **the same traffic our
  app's CDP session is already attached to.** Depending on it means routing our own
  data through a middleman.

**Decision: read the source directly. Keep FoE Helper's field list as free spec, drop
the dependency.**

## 3. Approach — passive CDP WebSocket observation

We already hold a **read-only CDP connection** to the Chrome tab (the capture adapter).
Chrome DevTools Protocol can surface WebSocket traffic passively:

- `Network.enable`, then subscribe to **`Network.webSocketFrameReceived`** (and
  `webSocketFrameSent` if we ever need request context). Each event carries the frame
  payload as it crosses the wire.
- We **do not inject any script into the page** and **do not send/modify** anything.
  This is strictly observation — it upholds the OBSERVE-ONLY invariant as cleanly as
  the screenshot capture does. (Contrast with FoE Helper, which overrides the page's
  WebSocket object — a mutation we deliberately avoid.)

Forge of Empires speaks a JSON-RPC-style protocol; GBG data arrives from
**`GuildBattlegroundService`** methods (e.g. `getProvinces`) as arrays of province
objects. We filter frames to that service and parse only the fields we need.

> **Feasibility gate (must pass before any code):** in a *local* session, confirm the
> `GuildBattlegroundService` frames actually appear on the CDP `webSocketFrameReceived`
> feed during GBG, and capture their **real** shape. Everything below is provisional
> until a real frame is in hand. We build to the observed payload, not to memory.

## 4. Shape (hexagonal — a new read-only port + one adapter)

Keep it consistent with the existing ports/adapters core; do **not** entangle it with
the vision pipeline.

```
GbgDataPort  (domain-facing, read-only)          # "give me the latest known provinces"
    └── CdpWebSocketGbgAdapter                    # observes frames, parses, updates a snapshot
```

Domain object (fields taken from the FoE Helper spec, pared to what we need):

```
Province(
    id,            # stable game id (preferred key)
    name,          # e.g. "C4"
    world,         # e.g. "cz8" / alias "H"
    owner_guild,   # guild currently holding the sector
    unlock_at,     # datetime | None  ← answers "when will it open"
    progress,      # built / required, if present
    battletype,    # attack / defense, if present
    observed_at,   # when WE saw this frame (freshness)
    source,        # "cdp_ws" (provenance, for honest reporting)
)
```

- The adapter maintains an **in-memory snapshot** keyed by province id, updated as
  frames arrive. No database, no store abstraction (same principle as the province-open
  helper — repetition, not anticipation, justifies structure later).
- `observed_at` is mandatory so every consumer can see **how stale** the data is. Data
  we haven't seen refreshed is reported as old, never as current.

## 5. Defensive parsing — the independence tax, contained

Owning the parser means game updates can change the payload. The rule that keeps that
from becoming fragility:

- **Unknown / changed / missing shape → drop the frame, keep the last good snapshot,
  log once.** Never crash, never guess, never half-fill a `Province`.
- A field we can't parse is `None`, and a `None` is reported as "unknown" — it never
  silently becomes a default that looks like real data.
- **Fallback is the existing vision pixels.** If the data feed is empty or stale, the
  app behaves exactly as it does today (map facts from pixels). The data layer is
  **additive** — its absence degrades to current behavior, never to a worse one.

## 6. How it fits the rest of the app (and what it does NOT do)

**It answers WHAT/WHEN. It does not answer WHERE, and it takes no action.**

- ✅ Province identity, ownership, world, **unlock timing** — directly.
- ❌ **Screen coordinates for clicking** — not in the data. The click path still needs
  vision/geometry to turn a chosen province into a screen point. Data = *what/when*,
  pixels/geometry = *where*.
- ❌ **The action itself** — this port never clicks and never drives the gate. It is a
  read-side information source, shown side-by-side with the pixel read.
- ✅ **Independent verification.** The data gives the province-open milestone a second,
  exact ground truth: "the click should have opened province C4" can be checked against
  what the data says is loaded — no longer a pixel-only guess.

### Caveat carried from the FoE Helper spec — `attrition`

FoE Helper labels its field **"attrition *chance* in percent."** That is very likely
**not** the per-province weakening % our classifier/gate targets. **Do not wire any
attrition-looking field into the weakening gate until its meaning is confirmed against
a real frame.** Misreading this would corrupt the CONTINUE/STOP decision. Treat weakening
as still-a-panel-question until proven otherwise.

## 7. Build plan (staged, verification-first — for when approved)

1. **Feasibility probe (observation only).** Local session: capture raw
   `webSocketFrameReceived` payloads during GBG; confirm `GuildBattlegroundService`
   frames exist; save real samples. **Go/no-go decision point.**
2. **Port + domain object.** Define `GbgDataPort` and `Province` against the *real*
   sample. No transport yet.
3. **Adapter.** Implement `CdpWebSocketGbgAdapter` on the existing CDP session; parse
   defensively; maintain the in-memory snapshot with `observed_at`.
4. **Show, don't act.** Surface the snapshot in the Vision Debugger **beside** the pixel
   read (province list + unlock countdowns). Build trust by comparison before anything
   depends on it. Nothing wired to the gate or to clicking.
5. **Reconcile.** Compare data vs pixels on real sessions; confirm the `attrition`
   semantics; decide whether/where the weakening % actually lives.
6. **Only then** consider letting data inform *selection* (what/when to open) while
   vision/geometry keep owning *where* and the safety gate keeps owning *whether*.

Each stage is independently valuable and independently stoppable. No stage after (1)
starts without a real frame in hand.

## 8. Risks & honest limits

| Risk | Mitigation |
|---|---|
| Protocol changes on game update break the parser | Defensive parse → drop + log; fall back to vision; parser is small and ours to fix |
| Frames only appear on certain in-game actions/refreshes | Snapshot + `observed_at` freshness; never present stale as current |
| `attrition`/weakening semantic mismatch | Do not feed the gate until confirmed on a real frame (§6) |
| Scope creep toward "data drives clicking" | This port is read-only by construction; action stays behind the existing gate + a separate future milestone |
| New data source becomes a second source of truth | Additive only; vision remains the fallback; consumers see provenance (`source`) + freshness (`observed_at`) |

## 9. ToS / posture

Passively observing traffic that already crosses our own attached tab, for an
**assistant/observer**, is the same category of activity as reading the screen — and is
what FoE Helper does openly. This design keeps it **observe-only**: no injection, no
sent frames, no action. Any move toward *data-informed clicking* is a separate,
conscious decision with its own safety review — not implied by building this reader.

## 10. Recommendation

Build the reader **ourselves, against the game's WebSocket via the existing CDP session,
staged and verification-first**, starting with the feasibility probe. It removes the
third-party dependency entirely, answers the two questions pixels can't (identity +
unlock timing), and strengthens the province-open verification work with an independent
ground truth — while staying strictly read-only and degrading to today's behavior if the
feed is ever absent.

_Await the feasibility-probe result before writing adapter code._
