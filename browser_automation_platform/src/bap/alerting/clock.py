"""Time handling: the game's clock vs ours, and Prague wall-clock formatting.

``province.lockedUntil`` is a **unix timestamp on the game server's clock**. A player's PC
can be a minute or two off, which would shift every announced time, so when the captured
batch carried a ``TimeService`` reading we correct for the difference (:func:`drift_seconds`).

Formatting is deliberately dependency-free: Prague is CET/CEST, and the EU rule (last Sunday
of March 01:00 UTC → last Sunday of October 01:00 UTC) is implemented here directly. We still
prefer :mod:`zoneinfo` when the platform has a tz database, and fall back to the rule on
Windows installs without ``tzdata`` — so the alert never prints the wrong hour just because a
package is missing.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

PRAGUE = "Europe/Prague"


def _last_sunday_utc(year: int, month: int, hour_utc: int) -> int:
    """Unix ts of the last Sunday of ``month`` at ``hour_utc`` — the EU DST switch."""
    last_day = calendar.monthrange(year, month)[1]
    d = datetime(year, month, last_day, hour_utc, tzinfo=timezone.utc)
    d -= timedelta(days=(d.weekday() + 1) % 7)      # Monday=0 … Sunday=6 → step back to Sunday
    return int(d.timestamp())


def _rule_offset(ts: int) -> int:
    """CET/CEST offset in seconds for ``ts`` using the EU summer-time rule."""
    year = datetime.fromtimestamp(ts, tz=timezone.utc).year
    start = _last_sunday_utc(year, 3, 1)            # 01:00 UTC → 02:00 CET becomes 03:00 CEST
    end = _last_sunday_utc(year, 10, 1)             # 01:00 UTC → 03:00 CEST becomes 02:00 CET
    return 7200 if start <= ts < end else 3600


def prague_offset(ts: int) -> int:
    """Seconds east of UTC in Prague at ``ts`` (3600 winter / 7200 summer)."""
    try:
        from zoneinfo import ZoneInfo

        return int(datetime.fromtimestamp(ts, tz=ZoneInfo(PRAGUE)).utcoffset().total_seconds())
    except Exception:                                # no tzdata (typical on Windows) → the rule
        return _rule_offset(ts)


def prague_time(ts: int) -> datetime:
    """``ts`` as Prague wall-clock, as a naive datetime (already shifted)."""
    return datetime.fromtimestamp(ts + prague_offset(ts), tz=timezone.utc).replace(tzinfo=None)


def prague_hhmm(ts: int) -> str:
    """``1788210517`` → ``"16:25"`` — the only format the alert message needs."""
    return prague_time(ts).strftime("%H:%M")


def prague_hour(ts: int) -> int:
    """Prague hour of day (0-23) — used by the quiet-hours window."""
    return prague_time(ts).hour


def _observed_epoch(bg) -> float | None:
    stamp = getattr(bg, "observed_at", "") or ""
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def drift_seconds(bg) -> float:
    """``server_now - our_now`` at the moment the snapshot was captured, or ``0.0`` when the
    batch carried no server clock. Add it to our clock to think in game time."""
    server = getattr(bg, "server_time", None)
    observed = _observed_epoch(bg) if bg is not None else None
    if server is None or observed is None:
        return 0.0
    delta = float(server) - observed
    return delta if abs(delta) < 3600 else 0.0       # implausible → distrust it, stay on our clock


def game_now(bg, now: float) -> float:
    """Our ``now`` expressed on the game server's clock."""
    return now + drift_seconds(bg)


__all__ = ["PRAGUE", "prague_offset", "prague_time", "prague_hhmm", "prague_hour",
           "drift_seconds", "game_now"]
