"""Prague wall-clock formatting (with and without a tz database) and server-clock drift."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bap.alerting import clock
from bap.forge.gbg_data.model import Battleground, PlayerState


def _ts(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp())


def test_summer_is_utc_plus_two():
    # 14:25 UTC on a July day → 16:25 in Prague (CEST)
    assert clock.prague_hhmm(_ts(2026, 7, 1, 14, 25)) == "16:25"


def test_winter_is_utc_plus_one():
    assert clock.prague_hhmm(_ts(2026, 1, 15, 14, 25)) == "15:25"


@pytest.mark.parametrize("ts", [
    _ts(2026, 3, 29, 0, 59),      # minutes before the spring switch
    _ts(2026, 3, 29, 1, 1),       # minutes after
    _ts(2026, 10, 25, 0, 59),     # before the autumn switch
    _ts(2026, 10, 25, 1, 1),      # after
])
def test_fallback_rule_matches_the_tz_database(ts):
    """The dependency-free EU rule must agree with zoneinfo, including at the switch —
    a Windows box without `tzdata` may not print a different time than a Linux one."""
    assert clock._rule_offset(ts) == clock.prague_offset(ts)


def test_prague_hour_used_by_quiet_hours():
    assert clock.prague_hour(_ts(2026, 7, 1, 21, 30)) == 23


def _bg(server_time, observed_at):
    return Battleground(map_id="m", provinces=(), participants={}, player=PlayerState(),
                        server_time=server_time, observed_at=observed_at)


def test_drift_uses_the_server_clock():
    observed = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    bg = _bg(int(observed.timestamp()) + 90, observed.isoformat())
    assert clock.drift_seconds(bg) == pytest.approx(90, abs=1)
    assert clock.game_now(bg, 1000.0) == pytest.approx(1090, abs=1)


def test_drift_zero_without_a_server_reading():
    observed = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert clock.drift_seconds(_bg(None, observed.isoformat())) == 0.0
    assert clock.drift_seconds(_bg(1, "not-a-timestamp")) == 0.0


def test_absurd_drift_is_distrusted():
    observed = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    bg = _bg(int(observed.timestamp()) + 90 * 86400, observed.isoformat())
    assert clock.drift_seconds(bg) == 0.0        # a wrong PC date must not shift every alert
