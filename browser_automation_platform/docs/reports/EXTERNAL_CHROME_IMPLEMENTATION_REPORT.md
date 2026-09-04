# External Chrome Attach — Implementation Report (Milestone 4.16)

BAP can now **attach to an operator-launched Google Chrome over CDP** and observe
the Forge tabs already open, instead of always launching and owning its bundled
Chromium. It stays strictly **observe-only** — no clicking, keyboard, cursor,
navigation, or gameplay — and Managed Chromium remains the default, so existing
installs are unchanged.

## Architecture

Attach is a **new adapter behind existing ports**, not a new core. The hexagon was
already shaped for it:

| Port (unchanged) | Attach adapter responsibility |
|---|---|
| `BrowserPort` | connect over CDP to `http://127.0.0.1:9222`; **never** launch or close Chrome |
| `TabSourcePort` | enumerate open tabs (`BrowserTab{id,title,url}`); adopt one by id |
| `CapturePort` | the **existing** read-only `ForgeCanvasCaptureAdapter` — a CDP `Page.captureScreenshot`, unchanged |

New/changed pieces:

- **`adapters/browser/cdp_attach_adapter.py`** — `CdpAttachBrowserManager`
  (`BrowserPort` + tab discovery/adoption). `start()` connects via
  `connect_over_cdp` (injectable for tests); `stop()` **disconnects the CDP client
  only**; `scan_tabs()`/`adopt_tab()` enumerate and adopt the operator's tabs;
  `open_tab`/`navigate` raise (observe-only guest), `close_tab` is a no-op. Also
  `probe_cdp()` (a driver-free `GET /json/version` + `/json` reachability check),
  `normalize_endpoint()`, and `is_localhost_endpoint()`.
- **`forge/browser_settings.py`** — persisted `BrowserMode` (Managed / External),
  `cdp_endpoint`, `chrome_path`, and the copyable Windows launch command. Default
  = **Managed Chromium**; a missing file is never an error.
- **Ownership model** — `core/domain/enums.py` gains `BrowserOwnership`
  (`MANAGED` / `EXTERNAL`); `BrowserPort.ownership` declares it (default MANAGED,
  so every existing adapter is unchanged); `BrowserController` exposes
  `ownership` / `owns_process`.
- **Capture provenance** — `CaptureGeometry` gains `browser_mode` + `cdp_endpoint`;
  External Chrome contributes an `ext:` marker to the calibration `key` so its
  calibration is never silently reused from a Managed capture (Managed keys are
  byte-identical to before). Snapshot metadata gains `browser_mode`,
  `browser_name`, `cdp_endpoint`, `zoom`.
- **GUI** — the Worlds page Browser card adds a **Browser mode** selector and, in
  External mode, a **CDP endpoint** field, **Test Connection**, **Attach Chrome**,
  **Disconnect**, a live status line, a localhost warning, and the copyable launch
  command. The exit path in External mode disconnects but never closes Chrome.

## Ownership model (explicit, no flag soup)

Ownership is a single enum the adapter declares and the controller reads — there
is no per-call mutable flag deciding whether a close kills the operator's browser:

- **Managed Chromium** (`ownership = MANAGED`): Open starts the browser, Close
  stops it, application exit closes it. Unchanged from before.
- **External Chrome** (`ownership = EXTERNAL`): Attach connects; Disconnect and
  application exit **disconnect the CDP client only**; Stop automation never
  touches the connection. The adapter's `stop()` disconnects and physically cannot
  close the process — the guarantee lives in the adapter, so the controller stays
  a plain idempotent open/close.

## Lifecycle guarantees (all proven by tests)

| Scenario | Guarantee | Test |
|---|---|---|
| Managed Open/Close/exit | starts / stops / closes the managed browser | `test_browser_controller.py`, `test_forge_lifecycle.py` |
| External Attach | connects, never launches | `test_cdp_attach_adapter.py`, `test_external_lifecycle.py` |
| External Disconnect | detaches, Chrome stays alive | both above |
| Stop automation (External) | never disconnects or closes Chrome | `test_external_lifecycle.py` |
| Application exit (External) | disconnects, Chrome stays alive | `test_external_lifecycle.py` |
| Failed connection | `CdpConnectionError`, recoverable (retry works) | `test_cdp_attach_adapter.py` |
| Reconnect after Chrome restart | attaches to the new process | `test_cdp_attach_adapter.py` |

## Tab & World routing

Attach reuses the existing hostname-based reattachment unchanged: `scan_tabs()`
returns every open tab; `WorldStore.match_tabs` maps Worlds to tabs by durable
Forge **hostname** (never tab id), so selecting H scans H, selecting D scans D, and
Scan All uses each World's own tab. Manual per-World tab pickers remain the
fallback. Stale tab handles are pruned on scan/adopt.

## Security & privacy

- The endpoint defaults to and is validated as **localhost**; a non-localhost
  endpoint raises a visible warning ("the Chrome debugging port must not be
  exposed to the network — use 127.0.0.1"). BAP binds nothing itself.
- Discovery lists tab **metadata only** (id/title/url) for selection/transparency
  and persists none of it. **Screenshots are only ever taken of Forge world tabs**
  (capture is triggered per assigned World, which is a Forge hostname) — non-Forge
  tabs are never captured.
- BAP reads through CDP only: it writes nothing to the Chrome profile, installs no
  extensions, and delivers no input.

## Migration / compatibility

- Default is **Managed Chromium**; a missing `browser_settings.json` yields it, so
  existing users and Worlds load unchanged and no persistence migration is needed.
- Snapshot metadata keys are additive — older snapshots (without `browser_mode`)
  still load.
- CLI entry points and existing tests are unchanged.

## Files changed

- `src/bap/core/domain/enums.py` — `BrowserOwnership`.
- `src/bap/core/ports/browser_port.py` — `ownership` on the port.
- `src/bap/core/engine/browser_controller.py` — `ownership` / `owns_process`.
- `src/bap/adapters/browser/cdp_attach_adapter.py` — **new** attach adapter + probe.
- `src/bap/forge/browser_settings.py` — **new** persisted browser-mode settings.
- `src/bap/forge/detection/geometry.py` — `browser_mode` / `cdp_endpoint` + key.
- `src/bap/forge/detection/testscan.py` — thread `geometry_meta` through scans.
- `src/bap/forge/snapshots.py` — browser provenance in metadata.
- `src/bap/gui/gui_main.py` — choose adapter from persisted mode.
- `src/bap/gui/main_window.py` — Browser-mode selector + External connection UI,
  provenance on live captures, External exit path.

## Tests

- `tests/unit/adapters/browser/test_cdp_attach_adapter.py` (11) — attach/discover/
  adopt; disconnect leaves Chrome alive; failure recoverable; reconnect; guest
  refuses open/navigate; endpoint helpers; probe with fake fetch.
- `tests/unit/core/engine/test_browser_controller.py` (+3) — ownership managed/
  external; external close delegates to adapter `stop()` only.
- `tests/unit/forge/test_browser_settings.py` (6) — default managed; persistence;
  unknown/corrupt → managed; launch command.
- `tests/unit/forge/test_external_lifecycle.py` (4) — app-level non-ownership.
- `tests/unit/forge/test_snapshots.py` (+3) — provenance metadata; older snapshots
  load.
- `tests/unit/forge/test_capture_geometry.py` (+1) — External key separated,
  Managed unchanged.
- `tests/unit/gui/test_external_chrome_ui.py` (5) — External controls shown; no
  "Open Browser"; localhost warning; Test Connection status; mode persist + note.

Use faithful **fake CDP adapters** (an injected `connect` returning fake
browser/contexts/pages, and an injected `fetch` for probe) so the normal unit
suite needs no real Chrome.

## Real-Chrome integration

No real Chrome was launched in this environment (headless CI container, no
operator-driven browser). The design's opt-in integration test (start a real
headless Chrome on a debug port from the *test*, connect, capture one screenshot,
disconnect, assert the process is still alive) is **not** part of the normal unit
suite by choice. The fake-CDP unit tests exercise the same adapter code paths.

## Limitations

- **Mode switching applies at next launch.** The browser adapter is chosen at
  startup from the persisted mode; changing the Worlds-page dropdown persists the
  choice and shows a restart note rather than hot-swapping the running adapter
  (hot-swapping the live browser would mean rebuilding the session graph — avoided
  for observe-only safety).
- **viewport / DPR / zoom** are reported when available and otherwise `None` — as
  in Managed mode today; this milestone did not add live CDP metric queries.
- Endpoint typed into Test Connection is probed and persisted, but **Attach uses
  the endpoint the adapter launched with**; change the endpoint then relaunch to
  attach elsewhere.
- localhost only; remote/multi-machine CDP is out of scope.

## Exact Windows verification checklist

1. Close any Chrome using the dedicated BAP profile.
2. Launch the dedicated Chrome:
   `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\BAP\chrome-profile"`
3. Log into Forge; open your World tabs (e.g. H and D).
4. In BAP → **Worlds** → **Browser mode → External Chrome (CDP)**; restart BAP if
   prompted.
5. Confirm the **CDP endpoint** is `http://127.0.0.1:9222`; click **Test
   Connection** → expect "Reachable — Chrome/… · N tab(s) (M Forge)".
6. Click **Attach Chrome** → status **Connected**; **Scan && Reattach** → each
   World auto-reattaches by hostname.
7. Test Scan a World (e.g. H) → the Vision Debugger opens observe-only; Save
   Snapshot → metadata shows `browser_mode: external_chrome`.
8. Close BAP → **Chrome stays open** with your tabs and login intact.
9. Reopen BAP → **Attach Chrome** again → it reconnects to the same Chrome.
