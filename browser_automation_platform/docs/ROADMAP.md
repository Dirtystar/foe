# Product roadmap — Autonomous GBG farmer (living document)

_The vision: a non-technical user maps their FoE world tabs in a friendly GUI, sets a
**max attrition** and an **allowed province % list** per world (once, remembered), clicks
**START**, and leaves for the day. The app fights the allowed provinces on each world,
**stops that world at its attrition limit** ("Done") while the others keep going, and
**self-heals** (reload/restart) unattended. Evening: **STOP**. Later: English product, easy
Mac/Linux/Win install, protected code, monetization._

_Last updated: 2026-09-01. `✅ done · ⏳ partial · ❌ not started`. % = share of the full
vision for that row._

## Where we are

| # | Capability | State | % | Notes |
|---|---|---|---|---|
| **A. Perception (brain)** | | | **90%** | the hard part — done & proven |
| A1 | Read GBG data (provinces, owners, %, unlock, siege) | ✅ | 95 | `gbg_data` parser, real fixtures |
| A2 | Live attrition, updates **per battle** | ✅ | 100 | `getPlayerParticipant`, proven live (4→14) |
| A3 | Rank/target provinces by attrition % | ✅ | 80 | advisor ranks; not yet filtered by a per-world allowlist |
| **B. Action (hand)** | | | **55%** | click + background play work; navigation missing |
| B1 | CDP targeted click + key (no mouse hijack) | ✅ | 90 | proven live on cz6 |
| B2 | Pick the right tab + bring to front | ✅ | 90 | `--list/--tab/--tab-index` |
| B3 | **Auto-open a chosen province on the map** | ❌ | 5 | the "where" problem — needs map hitmaps or vision |
| B4 | Self-heal (reload/restart window on error) | ❌ | 0 | required for all-day unattended |
| B5 | **Background play (no focus stealing)** | ✅ | 85 | **CONFIRMED live** — anti-throttle flags + `--no-raise` fought hidden tabs without stealing focus |
| **C. Orchestration** | | | **65%** | multi-world rotation landed |
| C1 | Single-world gated fight loop (stop at real attrition) | ✅ | 100 | proven live |
| C2 | **Multi-world round-robin** | ✅ | 80 | `bap-forge-farm`, config-driven; live glue needs field-testing |
| C3 | Per-world "Done" + keep others running | ✅ | 90 | delivered in the scheduler |
| C4 | Event-paced fighting (exact counts, zero waste) | ❌ | 0 | optional refinement |
| **D. Config & persistence** | | | **20%** | |
| D1 | World manager (worlds, browser mode) | ✅ | 60 | exists in the app |
| D2 | Per-world autoplay config (attrition limit + % allowlist + fight point) | ❌ | 5 | JSON config first, GUI later |
| D3 | Persisted, set-once, occasionally edited | ❌ | 10 | settings infra exists to build on |
| **E. GUI / UX** | | | **20%** | |
| E1 | Existing PySide6 console (observe-only) | ✅ | 50 | not yet autoplay-oriented |
| E2 | Autoplay GUI: map tabs, set limits, START/STOP, per-world status | ❌ | 5 | the user-facing product |
| E3 | Non-technical friendly, intuitive | ⏳ | 30 | nav split done; needs the autoplay screen |
| **F. Productization (future)** | | | **10%** | after the engine is complete |
| F1 | Cross-platform install (Mac/Linux/Win) | ⏳ | 30 | Python + packaging exists |
| F2 | English UI + optional i18n | ⏳ | 10 | strings not centralized |
| F3 | Hidden/obfuscated code base | ❌ | 0 | vision stage |
| F4 | Monetization / licensing | ❌ | 0 | vision stage |

**Overall engine (A–C1): ~85% and proven live. Overall product vision: ~35%.**
The perception + action + single-world gate — the technically hard core — works end to end.
What remains is orchestration across worlds, the map-navigation "where", config/GUI, and
productization.

## Known risks / open questions

- **Non-Chrome browsers:** CDP drives **Chromium-based** browsers (Chrome, Edge, Brave). A
  Firefox path would need a different mechanism — flag as a constraint to confirm with users.
- **B3 map navigation** is the biggest remaining engineering unknown: opening a *chosen*
  province needs its on-screen point (map hitmaps from the assets + camera state, or vision).
  Until then, autoplay fights whatever province is already open under the fixed button.
- **All-day resilience (B4):** reloads change the screen; self-heal must re-find the fight
  point and GBG map after recovery.

## Next up

**B3 — province auto-selection:** the farm currently fights whatever province is open under a
world's fixed button. Next it should read the allowed-% provinces (data ✅) and **open them on
the map** — the map-navigation "where" (hitmaps + camera, or vision). This unlocks the "attack
only the provinces I allow" part of the vision. Then **B4 self-heal** and the **E2 autoplay
GUI**.
