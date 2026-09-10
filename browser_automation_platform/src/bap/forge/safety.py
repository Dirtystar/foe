"""Safety / stealth ladder — trade speed & precision for a lower ban risk.

Automating GBG breaks the game's Terms; the server can't easily see our (real, signed) traffic,
but it *can* profile **behaviour**: perfect timing, 24/7 activity, huge daily volume, all worlds in
lockstep. This module turns one **safety level** (0 = fastest/riskiest … 4 = stealthiest) into the
concrete knobs the farmer uses to look more human:

- **cadence jitter** — randomised delay between fights (and between R-reloads),
- **daily cap** — stop each world after N fights/day (a human number),
- **active hours** — only run in given local-time windows (not 24/7),
- **stagger / pass gaps** — worlds don't start or loop in lockstep,
- **mistake rate** — occasional *harmless, self-recovering* human noise (extra hover / short
  idle / a deliberate near-miss the normal retry catches) — never anything that can desync or
  hang the loop.

Nothing here guarantees you won't be banned — it only reduces the footprint. Pure & testable;
the farmer reads these values, the GUI shows the descriptions/warnings.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyLevel:
    idx: int
    name: str                       # short id, e.g. "stealth"
    label: str                      # UI label
    inter_ms: tuple[int, int]       # delay between auto-battle clicks (jittered in this range)
    reload_every: tuple[int, int]   # press R (reload units) every N fights, N jittered in range
    mistake_rate: float             # 0..1 chance per fight of harmless, self-recovering noise
    daily_cap: int | None           # max battles per world per local day (None = unlimited)
    active_hours: tuple[tuple[int, int], ...]   # local-hour windows [start, end) the farm may run
    world_stagger: tuple[int, int]  # seconds between launching successive worlds
    pass_gap: tuple[int, int]       # seconds to wait between farm passes on a world
    description: str
    warning: str


# 0 = fastest & most precise (highest risk) … 4 = stealthiest (lowest risk). Numbers are tunable.
LEVELS: tuple[SafetyLevel, ...] = (
    SafetyLevel(
        0, "turbo", "Turbo — fastest, no mistakes (highest risk)",
        inter_ms=(140, 180), reload_every=(5, 5), mistake_rate=0.0, daily_cap=None,
        active_hours=((0, 24),), world_stagger=(0, 2), pass_gap=(2, 6),
        description="Maximum speed and precision: exact clicks, every world, around the clock.",
        warning="HIGHEST BAN RISK. Perfectly robotic and unlimited — easy to flag. Not recommended."),
    SafetyLevel(
        1, "fast", "Fast",
        inter_ms=(140, 280), reload_every=(4, 6), mistake_rate=0.02, daily_cap=800,
        active_hours=((6, 24),), world_stagger=(2, 8), pass_gap=(8, 25),
        description="Quick, lightly randomised. Up to 800 fights/world/day, active 06:00–24:00.",
        warning="High volume and long hours still stand out. Watch your accounts."),
    SafetyLevel(
        2, "balanced", "Balanced (recommended)",
        inter_ms=(160, 460), reload_every=(3, 6), mistake_rate=0.05, daily_cap=400,
        active_hours=((7, 12), (13, 23)), world_stagger=(5, 20), pass_gap=(20, 70),
        description="Human-ish pace with a midday break. Up to 400 fights/world/day.",
        warning="Reasonable compromise. Still against the game's Terms — use at your own risk."),
    SafetyLevel(
        3, "careful", "Careful",
        inter_ms=(220, 750), reload_every=(3, 5), mistake_rate=0.08, daily_cap=250,
        active_hours=((8, 12), (14, 22)), world_stagger=(10, 40), pass_gap=(45, 150),
        description="Slower, more varied, with breaks. Up to 250 fights/world/day.",
        warning="Lower footprint, but no automation is invisible."),
    SafetyLevel(
        4, "stealth", "Stealth — safest, most human",
        inter_ms=(320, 1300), reload_every=(2, 5), mistake_rate=0.12, daily_cap=150,
        active_hours=((9, 12), (15, 21)), world_stagger=(20, 90), pass_gap=(90, 300),
        description="Slow, irregular, plenty of breaks. Up to 150 fights/world/day — like a "
                    "relaxed human. Lowest risk we offer.",
        warning="Lowest risk, but still not guaranteed safe. You are responsible for your account."),
)

DEFAULT_LEVEL = 2


def get(idx: int) -> SafetyLevel:
    """A level by index, clamped into range."""
    return LEVELS[max(0, min(len(LEVELS) - 1, int(idx)))]


def jittered_inter(level: SafetyLevel, rng: random.Random | None = None) -> int:
    lo, hi = level.inter_ms
    return (rng or random).randint(lo, hi)


def jittered_reload(level: SafetyLevel, rng: random.Random | None = None) -> int:
    lo, hi = level.reload_every
    return (rng or random).randint(lo, hi)


def jittered_stagger(level: SafetyLevel, rng: random.Random | None = None) -> float:
    lo, hi = level.world_stagger
    return (rng or random).uniform(lo, hi)


def jittered_pass_gap(level: SafetyLevel, rng: random.Random | None = None) -> float:
    lo, hi = level.pass_gap
    return (rng or random).uniform(lo, hi)


def roll_mistake(level: SafetyLevel, rng: random.Random | None = None) -> bool:
    """True with probability ``mistake_rate`` — the caller then does a *harmless, self-recovering*
    bit of human noise (never an action that can desync the loop)."""
    return (rng or random).random() < level.mistake_rate


def _hour_now(now: float | None = None) -> float:
    lt = time.localtime(now) if now is not None else time.localtime()
    return lt.tm_hour + lt.tm_min / 60.0


def is_active_now(level: SafetyLevel, now: float | None = None) -> bool:
    """Is the current local time inside one of the level's active windows? (Turbo = always.)"""
    h = _hour_now(now)
    return any(s <= h < e for (s, e) in level.active_hours)


def seconds_until_active(level: SafetyLevel, now: float | None = None) -> int:
    """Seconds to wait until the next active window opens (0 if active now). Used to sleep between
    windows instead of hammering the game round the clock."""
    if is_active_now(level, now):
        return 0
    h = _hour_now(now)
    starts = sorted(s for (s, _e) in level.active_hours)
    nxt = next((s for s in starts if s > h), None)
    delta_h = (nxt - h) if nxt is not None else (24 - h + starts[0])
    return int(delta_h * 3600)


def daily_key(world: str, now: float | None = None) -> str:
    """Per-world, per-local-day counter key for the daily cap."""
    lt = time.localtime(now) if now is not None else time.localtime()
    return f"{lt.tm_year:04d}{lt.tm_mon:02d}{lt.tm_mday:02d}::{world}"


def cap_reached(count: int, level: SafetyLevel) -> bool:
    return level.daily_cap is not None and count >= level.daily_cap


def describe(level: SafetyLevel) -> str:
    return f"{level.label} — {level.description}"


__all__ = [
    "SafetyLevel", "LEVELS", "DEFAULT_LEVEL", "get", "jittered_inter", "jittered_reload",
    "jittered_stagger", "jittered_pass_gap", "roll_mistake", "is_active_now",
    "seconds_until_active", "daily_key", "cap_reached", "describe",
]
