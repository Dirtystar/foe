"""Build a runtime configuration from Forge Worlds.

Forge of Empires renders Guild Battlegrounds on a WebGL/canvas surface — there
are no DOM elements to select, so capture is always the **full game canvas**.
This is the P0-C fix: the Forge path builds its own capture configuration and
never inherits the generic placeholder selectors (e.g. ``#status-panel``) that
broke capture. Each World becomes one attended session:

  - profile id  = the World alias (the user-facing identity)
  - capture     = one full-page "canvas" binding, NO selector
  - cadence     = the World's own click interval
  - navigation  = none (attended: the user's own logged-in tab is adopted)

No badge analyzers are wired here yet — detection is a later milestone. For now
a Forge session captures the canvas each tick and evaluates an empty rule pack,
so it observes without acting.
"""

from __future__ import annotations

from collections.abc import Sequence

from bap.config.config_models import (
    ApplicationConfig,
    CaptureBindingConfig,
    GlobalSettings,
    ProfileConfig,
    SessionConfig,
    ViewportConfig,
)
from bap.core.domain.models import TabProfile
from bap.core.engine.session_manager import SessionSpec
from bap.forge.worlds import World


def forge_session_spec(world: World) -> SessionSpec:
    """The runtime session-plan entry for one World: profile id = alias, cadence
    = the world's interval. Used for live (no-restart) add/edit of worlds."""
    return SessionSpec(tab_profile=TabProfile(id=world.alias), interval_ms=world.interval_ms)

# The rule pack Forge sessions reference. Empty for now (observe-only): the
# assistant looks at the canvas but performs no action until the detector and
# fight logic land in later milestones.
FORGE_RULE_PACK = "forge"

CANVAS_BINDING = "canvas"


def build_forge_config(
    worlds: Sequence[World],
    *,
    viewport: tuple[int, int] = (1920, 1080),
    max_sessions: int = 8,
) -> ApplicationConfig:
    """Translate Worlds into an attended, full-canvas ApplicationConfig.

    The capture binding is deliberately ``target: full_page`` with no selector —
    a Forge session must never fall back to a DOM selector. `max_sessions` is
    raised to fit the number of worlds so the config is always self-consistent.
    """
    width, height = viewport
    profiles = [
        ProfileConfig(
            id=world.alias,
            viewport=ViewportConfig(width=width, height=height),
            session=SessionConfig(interval_ms=world.interval_ms),
            rule_pack=FORGE_RULE_PACK,
            capture_bindings=[
                CaptureBindingConfig(name=CANVAS_BINDING, target="full_page", analyzers=[])
            ],
        )
        for world in worlds
    ]
    return ApplicationConfig(
        version=1,
        settings=GlobalSettings(
            attended=True,
            browser_engine="chromium",
            max_sessions=max(max_sessions, len(profiles), 1),
        ),
        rule_packs={FORGE_RULE_PACK: []},
        profiles=profiles,
    )


__all__ = ["FORGE_RULE_PACK", "CANVAS_BINDING", "build_forge_config", "forge_session_spec"]
