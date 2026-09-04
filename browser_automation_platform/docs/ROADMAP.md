# Forge GBG Farmer — Progress Roadmap

Living snapshot of how far each piece is. **Legend:** ✅ done · 🟡 works, needs polish ·
🟠 partial · ⛔ not started. Percentages are rough, updated as we go.

_Last updated: 2026-09-04._

## 1. Core farming engine — **95%**

| Feature | % | Status |
|---|---:|---|
| Read GBG data (`/game/json` parser, model, attrition) | 100 | ✅ |
| Rank targets (lowest % first, centre rings, Cíl priority, Stop skip) | 95 | ✅ |
| Round-keyed skip-list (resets each GBG round) | 100 | ✅ |
| Map transform from FoE-Helper markers (pan + place any province) | 100 | ✅ |
| Open province → Útok → Auto-battle chain (live-confirmed) | 95 | 🟡 |
| Attrition gate (stop at the limit, live reading) | 100 | ✅ |
| Fast fight cadence (auto-battle + R reload) | 90 | 🟡 |
| Self-heal (reload + re-enter on stall) | 85 | 🟡 |
| Parallel multi-world farming (one process per world) | 85 | 🟡 |

## 2. Entry & browser — **80%**

| Feature | % | Status |
|---|---:|---|
| Identify GBG entrance (HAR → Atlas building) | 100 | ✅ |
| Vision-locate the entrance (multi-scale template match) | 95 | ✅ |
| DPR / device→CSS click mapping | 100 | ✅ |
| Reliable entry click across window sizes | 70 | 🟠 needs a right-sized (owned) window |
| Owned browser launcher (fixed window, anti-throttle, profile) | 70 | 🟡 auto window-size calibration pending |
| End-to-end farm run (enter → fight → next world) | 60 | 🟠 verifying live |

## 3. Product — **75%**

| Feature | % | Status |
|---|---:|---|
| Licence tiers + prices (1/2/4/8/∞ worlds) | 95 | ✅ |
| Offline key check + world-count enforcement | 95 | ✅ |
| End-user GUI (key, worlds, limits, %s, Start/Stop) | 60 | 🟡 needs live status + log view |
| End-user documentation | 70 | 🟡 |

## 4. Release readiness — **15%**

| Feature | % | Status |
|---|---:|---|
| Codebase cleanup (drop dev tools) | 30 | 🟠 started |
| Wean off FoE Helper (native `.gbg-tabs` / markers / names / Cíl) | 15 | 🟠 still dependent |
| Packaging (installer + bundled Chromium, Win/macOS/Linux) | 5 | ⛔ |
| Obfuscation / licence hardening | 0 | ⛔ |

---

### Next up
1. Verify the full farm loop end-to-end (enter → target → fight → next world) on a right-sized window.
2. Auto-set the launcher window size so entry is reliable on the first try.
3. GUI polish: live status + a log panel.
4. Decide removal of superseded `autoplay` / `round_robin`.
