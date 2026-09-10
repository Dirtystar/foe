# Developer tools vs. the shipped product

As the app moves toward release, this file tracks which modules are **product** (ship to
end users) and which are **developer/diagnostic tools** (used to build and debug, not shipped).
Use it to keep the codebase clean and to decide what to strip from release builds.

## Product path (ships)

- `bap.forge.app.farmer_gui` — the end-user desktop app (licence, world config, Start/Stop).
- `bap.forge.action.launcher` — launches the owned browser (fixed window, anti-throttle).
- `bap.forge.action.open_targets` — the autonomous farmer (enter GBG → target → fight),
  including the parallel `--worlds` orchestrator.
- `bap.forge.action.gbg_entrance` + `bap.forge.detection.template_match` — vision entry.
- `bap.forge.action.navigate`, `locate`, `cdp_click`, `solve`, `calibrate` — the live driving,
  map-transform, and marker calibration the farmer depends on.
- `bap.forge.gbg_data.*` — the `/game/json` parser, model, advisor, navigator (pure logic).
- `bap.forge.licensing` — tiers, prices, offline key check. (Key **generation** is owner-only.)

## Developer / diagnostic tools (do not ship; safe to keep out of release builds)

- `bap.forge.action.har_probe` — mines a browser HAR for the GBG entry fingerprint and city
  building codes. Used to reverse-engineer entry; not needed at runtime.

## Superseded — candidates for removal

These predate the current farmer and are replaced by `open_targets --farm` / `--worlds`. They
still have `pyproject` console-scripts and unit tests, so removing them means also deleting those
entry points and tests — do it deliberately, not silently:

- `bap.forge.action.autoplay` (`bap-forge-autoplay`) — single-world gated autoplay; superseded
  by `open_targets --farm`.
- `bap.forge.action.round_robin` (`bap-forge-farm`) — sequential multi-world loop; superseded by
  the parallel `open_targets --worlds`.

## Removed

- `inspect_map.py`, `marker_probe.py` — early one-off map/marker diagnostics, unwired
  (no imports, no entry points, no tests). Deleted.
