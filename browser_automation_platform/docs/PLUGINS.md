# Plugins — extending analyzers and action handlers

Third-party analyzers and action handlers install as ordinary Python packages
and are discovered via entry points. No `bap` source changes are needed.

## Extension contract

Declare an entry point in one of two groups. The entry-point **name** is the
config `type` string; the target is a **zero-argument factory** returning a
`VisionAnalyzerPort` (analyzers) or `ActionHandlerPort` (actions):

```toml
# your plugin's pyproject.toml
[project.entry-points."bap.analyzers"]
custom_ocr = "my_pkg:create_analyzer"     # create_analyzer() -> VisionAnalyzerPort

[project.entry-points."bap.actions"]
my_action = "my_pkg:create_handler"       # create_handler() -> ActionHandlerPort
```

The factory takes **no arguments** — this is the same contract the built-in
registries use. Per-invocation settings are **not** passed to the factory;
they flow to the analyzer at `analyze()` time via `AnalyzerContext.settings`
and to the handler at `execute()` time via `ActionRequest.params`, exactly
like the built-ins. Consequently there is **no plugin-specific config schema
in core** — a plugin reads whatever keys it wants out of the settings/params
mapping.

Reference the plugin from YAML like any built-in:

```yaml
analyzers:
  - type: custom_ocr
    settings: { threshold: 0.8 }   # -> AnalyzerContext.settings
```

A working example package is in `tests/example_plugin/` (`bap-fake-plugin`).

## Discovery and merging

- `production_analyzer_registry()` and `playwright_action_registry()` register
  the built-ins, then merge discovered plugins on top (`include_plugins=True`
  by default; pass `False` to get built-ins only).
- Discovery lives in `bap.app.plugins` (`load_analyzer_plugins`,
  `load_action_plugins`, `apply_*_plugins`). The entry-point iterable is
  injectable, so discovery is unit-testable without installing packages.
- No global mutable state: every registry is a fresh object; discovery returns
  fresh dicts. Two `Application` instances never share plugin state.

## Conflict policy

A plugin whose name collides with an already-registered (built-in) type is a
**conflict error** by default — a plugin cannot silently hijack `ocr` or
`click`. Pass `allow_override=True` to intentionally replace a built-in.

## Failure behavior (fail during composition, not runtime)

- An entry point that fails to import, or whose target is not callable, raises
  `PluginError` (a `CompositionError`) at discovery.
- A factory that returns the wrong type is caught during composition:
  analyzers are instantiated and type-checked in `build_capture_binding`, and
  every action handler is instantiated and type-checked in
  `create_application` — both **before the browser starts**.
- A config `type` with no matching built-in or plugin fails composition with
  "no analyzer/handler registered", unchanged from before.

## Security note

Installing a plugin runs its code (entry-point import + factory + tick-time
analyze/execute). Only install plugins you trust. There is no sandbox — a
plugin has the same capabilities as a first-party adapter (which is exactly
the seam the architecture intends), so treat plugin installation as a
trust decision equivalent to adding a dependency.
