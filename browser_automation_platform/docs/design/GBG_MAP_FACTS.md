# GBG Map — observed facts (for building the next stages)

_Exploration note, read-only. The live Chrome MCP was **not reachable** from this
cloud session (network-isolated; `forgeofempires.com` → 403; no Chrome/browser MCP
present). So these facts come from the **real committed dataset** — 106 GBG-map
frames across 8 worlds (A–H) — cross-checked against the app's **own detector
output** run on a live frame. Everything below is a factual observation, not a
design decision._

Reference frame: `dataset/frames/2026-08-06_10-33-51_H.png` (1920×869, world H).

---

## 1. The single most important fact

**The GBG map does not show weakening percentages.** Province banners on the map
show a **building fraction** (e.g. `X/2`, `X/3`) — how many of that province's
buildings are built/owned — next to a house icon and the province name. There is
no `20 / 40 / 60 / 80 / 100` pill anywhere on the map view.

The app's detector agrees. Run on the reference frame:

```
detections: 2
  badge cx=299 cy=472  pct=None  conf=0.71
  badge cx=873 cy=807  pct=None  conf=0.67
selected target: None
panel present: False
```

The `BadgeDetector` **fires** on map banners (conf ~0.67–0.71), but the
`PercentClassifier` returns **`pct=None`** for both — correctly, because there is
no weakening pill to read. So on the map alone the pipeline produces **no
selectable target**, and that is the *right* answer, not a bug.

**Consequence for next stages:** the 20/40/60/80/100 weakening percentage the whole
gate is built around **lives in the province detail panel**, not on the map. The
map is for *locating and choosing* a province; the panel is where the weakening %
(and therefore the CONTINUE/STOP decision) actually becomes readable. This is
exactly why the `GBG_MAP → PROVINCE_PANEL` transition is the load-bearing next step.

---

## 2. Screen anatomy (what's where on the map)

| Region | Contents (observed) |
|---|---|
| **Center map** | Isometric island terrain. Provinces separated by colored **guild-territory borders** (red = enemy-held here, other guild colors elsewhere). Thick colored coastlines trace who owns each landmass. |
| **Province banners** (float over provinces) | House icon + **building fraction** `X/2`/`X/3` + province name. Banner tint: **blue = own guild's**, **red = enemy guild's**. These are what the badge detector locks onto. |
| **Guild HQ shields** | Ornate **shield emblems** (e.g. blue lion crest) mark a guild's home/HQ provinces — distinct from ordinary province banners. |
| **Top-left bar** | Season/round **timer**, **goods** counters, and an **attrition counter** — crossed-swords + red-arrow icon showing a number (`0` on this frame). |
| **Top-right bar** | **Resource caps** (e.g. `94.9k / 200k`) plus `+ / ? / X` window controls. |
| **Bottom-left panel** | Wooden button cluster: 4 tab icons (mail / messages / rewards / buildings), a big orange **"Zpět do města"** ("Back to city") button, and a bottom icon row (attack, defense, ranking bars, links, list, **zoom/search**). A small tag reads **`C4: H`** = province C4, guild H. |
| **UI language** | **Czech** (`Zpět do města`). World host = `cz8.forgeofempires.com`. Expect Czech labels in any panel text we later parse. |

---

## 3. Attrition vs weakening — do not conflate

- The **top-bar attrition counter** (crossed-swords + red arrow, value `0`) is the
  player's **own accumulated attrition** for the round — a global, per-player
  penalty that rises as you fight. It is *not* the per-province weakening %.
- The **weakening %** the gate cares about is **per-province** and appears **inside
  the province panel** after you open a province. These are two different numbers
  living in two different screens. The gate's "per-World, never global" invariant
  lines up with the *weakening* number, not the top-bar attrition.

---

## 4. Map behavior / structure (as far as still frames show)

- The map is a **single scrollable/zoomable board** (zoom control bottom-left). All
  106 dataset frames are this map state — **zero** panel/battle/result frames exist
  yet, confirming the panel is a *separate* screen reached by clicking a province.
- **Ownership is color-coded**, not text-coded: you read who holds a province from
  border/coastline color and banner tint, and read *build progress* from the
  fraction. Neither encodes weakening.
- Banner **positions are content-dependent** (they float over province centroids),
  so badge locations vary frame to frame — consistent with the detector finding
  badges at different `cx,cy` per frame rather than fixed slots.

---

## 5. What this means for the next stages (facts → implications)

1. **The map cannot answer "is this province weakened enough?"** Only the panel
   can. Any targeting logic that needs a % must go map → open → panel-read.
2. **The classifier's two states are the right primitives.** `GBG_MAP` = "choose a
   province"; `PROVINCE_PANEL` = "read the weakening % / decide". `UNKNOWN`
   correctly covers everything else (battle screen, city, dialogs) we have never
   captured.
3. **The missing dataset is entirely panel/battle frames.** The province-open
   milestone's capture-on-not-`PROVINCE_PANEL` is the mechanism that will finally
   produce them.
4. **Panel text will be Czech.** Whatever reads the panel (% pill is image-based, so
   likely fine, but any label/button matching) must not assume English.
5. **Two candidate "target" cues on the map** (building fraction, guild ownership
   color) are available *before* opening — potentially useful later to prefer
   enemy, under-built provinces — but that is selection policy, not part of the
   read pipeline, and is out of scope until asked.

---

## 6. Honesty / limits of this note

- Derived from **still frames**, not live interaction — I could not observe
  hover/click/scroll/animation behavior, cooldowns, or what the panel actually looks
  like (no panel frame exists). Those remain genuinely unknown until the first live
  `PROVINCE_PANEL` capture.
- One reference frame was scanned end-to-end; the fraction/percentage finding was
  visually confirmed across several worlds' banners but not exhaustively OCR'd.
- No code, thresholds, or workflow were changed producing this note.
