# External Chrome Attach (Milestone 4.16 — **implemented**)

**Status: implemented.** BAP can attach to an **operator-launched Chrome** over
CDP instead of launching its own bundled Chromium. It changes no gameplay
behaviour and stays strictly observe-only; capture remains read-only
(`Page.captureScreenshot`, `fromSurface`, no input). Managed Chromium is still the
default, so existing installs are unchanged. Implementation details and the exact
operator checklist are in **EXTERNAL_CHROME_IMPLEMENTATION_REPORT.md**; the design
below is preserved for context.

## Operator quick start (Windows)

1. Close any Chrome already using the dedicated BAP profile.
2. Launch a **dedicated** Chrome with remote debugging (never your personal profile):

   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\BAP\chrome-profile"
   ```

3. Log into Forge and open your World tabs.
4. In BAP → Worlds → **Browser mode: External Chrome (CDP)** (restart BAP if you
   just switched from Managed).
5. **Test Connection** → **Attach Chrome** → **Scan && Reattach**.
6. Close BAP — Chrome stays open.

A dedicated `--user-data-dir` is recommended because it isolates BAP from your
email/banking/personal tabs, avoids profile-lock conflicts, keeps the Forge login
persistent, and leaves the operator fully in control. The port stays on localhost.

## Why

Today BAP launches and owns a Chromium instance (the attended Playwright adapter).
Operators increasingly want to use **their own Chrome** — their logged-in Forge
sessions, extensions, and window layout — and have BAP simply *observe* the tabs
that are already open. Owning the browser also couples BAP's lifetime to the
browser's, which the P0-4 exit prompt only partly mitigates. Attaching to an
external Chrome removes that coupling entirely: the operator owns the browser, BAP
is a read-only guest.

## Requirements (from the milestone)

1. Connect via **CDP** to an already-running Chrome.
2. The **operator launches Chrome manually** (BAP never spawns it).
3. BAP **discovers tabs** from the running instance.
4. The operator **maps Worlds** to discovered tabs (by Forge hostname, as today).
5. **Closing BAP must NOT close Chrome.**
6. The **Chrome profile stays under operator control**.
7. A **separate Chrome profile is recommended** (isolation from daily browsing).
8. **No gameplay changes** — observe-only throughout.

## How Chrome is launched (operator side, documented — not automated)

The operator starts Chrome with remote debugging enabled and, ideally, a
dedicated profile:

```
# Windows (recommended: a separate profile dir)
chrome.exe --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\foe-chrome"
```

BAP never runs this command. The docs/first-run flow should present it as a copy
box and verify reachability (see "Discovery" below). The `--user-data-dir`
separation is a **recommendation** surfaced in the UI, not enforced by BAP.

## Architecture — where it fits the hexagon

The existing ports already model exactly what attach needs; attach is a **new
adapter**, not a new core:

| port (unchanged) | attach adapter responsibility |
|---|---|
| `browser_port` | connect over CDP to `http://127.0.0.1:9222`; expose contexts/pages; **never** launch or close the browser process |
| `tab_source_port` | enumerate open tabs (`BrowserTab{tab_id,title,url}`) from the connected Chrome |
| `capture_port` | the **existing** read-only `forge_capture` CDP screenshot, unchanged — it already attaches a CDP session to a page |

Playwright supports this directly: `chromium.connect_over_cdp(endpoint)` returns a
`Browser` whose `contexts`/`pages` are the operator's real tabs. The current
`attended_adapter` is the closest existing shape (it adopts operator-driven tabs);
the attach adapter is a sibling that obtains those pages from an external endpoint
instead of a BAP-launched one.

### Proposed new pieces (future work, named for clarity)
- `adapters/browser/cdp_attach_adapter.py` — `connect_over_cdp(endpoint)` →
  `BrowserPort`; `discover_tabs()` → `list[BrowserTab]`. **Guest semantics:** its
  `close()`/`shutdown()` disconnects the CDP client only; it never calls
  `browser.close()` on an externally-owned browser.
- A `ConnectionMode` selector in the composition root: `LAUNCH` (today) vs
  `ATTACH` (new). Forge config gains an optional `cdp_endpoint`.
- First-run/Settings UI: an "Attach to existing Chrome" panel — endpoint field
  (default `127.0.0.1:9222`), a **Test connection** button, and the copyable launch
  command with the separate-profile recommendation.

## Discovery + World mapping

1. **Test connection:** GET `http://127.0.0.1:9222/json/version` to confirm Chrome
   is reachable and report its version; a clear error + the launch command if not.
2. **Discover tabs:** enumerate pages; filter to Forge hostnames
   (`worlds.is_forge_hostname`) for the picker, but show all for transparency.
3. **Map Worlds:** reuse the **existing hostname reattachment** — `WorldStore.match_tabs`
   already maps Worlds to tabs by Forge hostname (not tab id), so a World follows
   its server across tab reordering/reopening. The operator adjusts any mapping in
   the same tab-picker UI used today.

## Lifecycle — the critical guarantee

- **Attach never spawns Chrome.** If the endpoint is unreachable, BAP reports it;
  it does not fall back to launching Chromium.
- **Closing BAP disconnects, never closes.** In ATTACH mode the exit path
  disconnects the CDP client and stops BAP's runtime; it must not call any
  browser-close API. The P0-4 exit prompt is simplified in this mode to "Close
  assistant (Chrome stays open)" — there is no BAP-owned browser to tear down.
- **Crash/disconnect handling:** if the operator closes Chrome or a tab, discovery
  reports the tab as gone and the affected World becomes unattached (the same
  fail-safe as today); no reconnection is attempted without operator action.
- **Profile ownership:** BAP reads through CDP only; it writes nothing to the
  Chrome profile and never installs extensions or changes settings.

## Safety invariants (unchanged)

- **Observe-only:** capture remains `Page.captureScreenshot` (no input, no
  foregrounding, no navigation). Attach adds **no** clicking, cursor, or keys.
- **Read-only guest:** BAP holds no ownership of the browser process; it cannot
  close it, resize its viewport, or bring tabs to front.
- **Per-World safety gate** and **wrong-accepted = 0** are untouched — attach only
  changes *where the pixels come from*, not any analysis.

## Testing strategy (when implemented)

- Unit: a fake CDP endpoint / fake `connect_over_cdp` returning canned pages →
  discovery yields the expected `BrowserTab`s; ATTACH `close()` disconnects and
  **asserts the browser-close API is never called**.
- Integration (marked, opt-in): a real headless Chrome started by the *test* (not
  by BAP) on a debugging port; connect, discover, capture one screenshot,
  disconnect, and assert the Chrome process is still alive afterwards.

## Explicitly out of scope

- Automating the Chrome launch (operator-run only).
- Any gameplay action, cursor movement, click, or key.
- Managing/mutating the operator's Chrome profile.
- Multi-machine / remote-CDP over the network (localhost only for now).

_Design authored in Milestone 4.13; implemented in Milestone 4.16 — see
EXTERNAL_CHROME_IMPLEMENTATION_REPORT.md._
