"""End-to-end without a browser: snapshot in → exactly one message per opening, out."""

from __future__ import annotations

from conftest import ENEMY, ME, battleground, province

from bap.alerting.config import AlertConfig
from bap.alerting.engine import AlertEngine
from bap.alerting.labels import LabelBook
from bap.alerting.notifiers import NullNotifier
from bap.alerting.state import SentLog


class FlakyNotifier(NullNotifier):
    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times

    def send(self, text: str) -> bool:
        if self.fail_times > 0:
            self.fail_times -= 1
            return False
        return super().send(text)


def _engine(tmp_path, *, notifier=None, labels=None, **cfg_kw):
    cfg = AlertConfig.from_dict({"lead_minutes": 10, "stale_minutes": 5, **cfg_kw})
    notifier = notifier or NullNotifier()
    engine = AlertEngine(cfg, notifier, SentLog(tmp_path / "state.json"),
                         labels or LabelBook(overrides={1: "A1X"}, auto={}))
    return engine, notifier


def test_nothing_to_say_before_a_snapshot(tmp_path):
    engine, notifier = _engine(tmp_path)
    assert engine.tick() == [] and notifier.sent == []
    assert "waiting for GBG data" in engine.status_line()


def test_announces_an_opening_once(tmp_path, now):
    engine, notifier = _engine(tmp_path)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=300)]), now=now)
    assert [e.province_id for e in engine.tick(now)] == [1]
    assert notifier.sent == ["16:05 🔵 A1X"]
    assert engine.tick(now + 30) == []                  # same opening, second tick: silence
    assert len(notifier.sent) == 1


def test_waits_until_the_lead_window(tmp_path, now):
    engine, notifier = _engine(tmp_path)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=3600)]), now=now)
    assert engine.tick(now) == []                       # an hour out — too early to be useful
    assert engine.tick(now + 3000) != []                # 10 minutes out — now it matters
    assert notifier.sent == ["17:00 🔵 A1X"]


def test_several_openings_share_one_message(tmp_path, now):
    engine, notifier = _engine(tmp_path)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=300),
                                     province(2, owner=ENEMY, opens_in=310, siege_by=ME)]),
                       now=now)
    assert len(engine.tick(now)) == 2
    assert notifier.sent == ["16:05 🔵 A1X\n16:05 🔴 #2"]


def test_dedupe_survives_a_restart(tmp_path, now):
    engine, notifier = _engine(tmp_path)
    bg = battleground([province(1, owner=ME, opens_in=300)])
    engine.on_snapshot(bg, now=now)
    engine.tick(now)
    fresh, fresh_notifier = _engine(tmp_path)           # same state file, new process
    fresh.on_snapshot(bg, now=now)
    assert fresh.tick(now + 60) == [] and fresh_notifier.sent == []


def test_a_failed_send_is_retried_not_lost(tmp_path, now):
    engine, notifier = _engine(tmp_path, notifier=FlakyNotifier(fail_times=1))
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=300)]), now=now)
    assert engine.tick(now) == []                       # gateway hiccup
    assert [e.province_id for e in engine.tick(now + 30)] == [1]
    assert notifier.sent == ["16:05 🔵 A1X"]


def test_quiet_hours_silence_but_do_not_queue(tmp_path, now):
    # NOW is 16:00 Prague; a window of 15-17 covers it
    engine, notifier = _engine(tmp_path, quiet_hours=[15, 17])
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=300)]), now=now)
    assert engine.tick(now) == [] and notifier.sent == []
    assert engine.tick(now + 60) == []                  # not queued up to burst later either


def test_server_clock_drift_shifts_the_decision(tmp_path, now):
    """With the server 10 minutes ahead of us, a province the game opens at 16:15 server-time
    is due immediately at a 10-minute lead — the announced time still comes from the game."""
    engine, notifier = _engine(tmp_path)
    bg = battleground([province(1, owner=ME, opens_in=900)], server_time=now + 600)
    engine.on_snapshot(bg, now=now)
    assert [e.province_id for e in engine.tick(now)] == [1]
    assert notifier.sent == ["16:15 🔵 A1X"]


def test_status_line_reports_the_next_opening(tmp_path, now):
    engine, _ = _engine(tmp_path)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=1500)]), now=now)
    line = engine.status_line(now)
    assert "1 upcoming" in line and "16:25 🔵 A1X" in line


def test_layout_supplies_labels_for_unnamed_provinces(tmp_path, now):
    from bap.forge.gbg_data.map_layout import MapLayout

    engine, notifier = _engine(tmp_path, labels=LabelBook(overrides={}, auto={}))
    engine.on_layout(MapLayout(map_id="m", width=2500, height=1960,
                               flags={1: (0, 0), 2: (2500, 1960)}))
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=300)]), now=now)
    engine.tick(now)
    assert notifier.sent == ["16:05 🔵 A1"]
