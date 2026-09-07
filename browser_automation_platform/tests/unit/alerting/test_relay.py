"""Collector → scheduler: the split that lets the sending half run without the game.

The interesting failures here are all at the seam, so these drive a real HTTP server: a
collector posts an actual captured body, the scheduler parses it with the same reader, and the
engine on the far side produces the message. A mocked transport would prove nothing.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from conftest import ME, battleground, province

from bap.alerting.config import AlertConfig
from bap.alerting.engine import AlertEngine
from bap.alerting.labels import LabelBook
from bap.alerting.notifiers import NullNotifier
from bap.alerting.relay import (
    BATTLEGROUND,
    MAP,
    RELAY_PATH,
    RelayClient,
    SnapshotReceiver,
    serve_relay,
)
from bap.alerting.state import SentLog

SECRET = "a-shared-secret"
SAMPLE = Path("dataset/api_samples/getBattleground.sample.json")
MAP_DATA = Path("dataset/api_samples/map_data.volcano_archipelago.sample.json")


def _engine(tmp_path, **cfg_kw):
    cfg = AlertConfig.from_dict({"trigger_lead_minutes": 10, "window_minutes": 30,
                                 "side_rule": "owner", **cfg_kw})
    notifier = NullNotifier()
    return AlertEngine(cfg, notifier, SentLog(tmp_path / "state.json"),
                       LabelBook(overrides={1: "A1X"}, auto={})), notifier


@pytest.fixture
def relay(tmp_path):
    engine, notifier = _engine(tmp_path)
    receiver = SnapshotReceiver(engine)
    httpd = serve_relay(receiver, secret=SECRET, port=0, host="127.0.0.1")
    url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        yield engine, notifier, receiver, url
    finally:
        httpd.shutdown()


def _raw_post(url, body, *, token=SECRET, path=RELAY_PATH):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url + path, data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


# ------------------------------------------------------------------------- auth

def test_a_snapshot_without_the_secret_is_refused(relay):
    _, _, receiver, url = relay
    assert _raw_post(url, {"kind": BATTLEGROUND, "body": "{}"}, token=None) == 401
    assert _raw_post(url, {"kind": BATTLEGROUND, "body": "{}"}, token="wrong") == 401
    assert receiver.accepted == 0


def test_health_needs_no_secret(relay):
    """A host checker should not need the credential to see the process is up."""
    _, _, _, url = relay
    with urllib.request.urlopen(url + "/health", timeout=5) as resp:
        assert json.loads(resp.read())["ok"] is True


def test_it_refuses_to_start_without_a_secret(tmp_path):
    """An open relay on a public host would let anyone drive the guild's alerts."""
    engine, _ = _engine(tmp_path)
    with pytest.raises(SystemExit):
        serve_relay(SnapshotReceiver(engine), secret="", port=0, host="127.0.0.1")


def test_junk_is_rejected_without_killing_the_server(relay):
    _, _, receiver, url = relay
    assert _raw_post(url, {"kind": "nonsense", "body": "{}"}) == 400
    assert _raw_post(url, {"kind": BATTLEGROUND, "body": 17}) == 400
    assert _raw_post(url, {"kind": BATTLEGROUND, "body": "not json"}) == 202   # parsed, unused
    assert _raw_post(url, {"kind": BATTLEGROUND, "body": "{}"}) == 202
    assert receiver.accepted == 0
    # still alive and still working
    assert _raw_post(url, {"kind": BATTLEGROUND,
                           "body": SAMPLE.read_text(encoding="utf-8")}) == 200


def test_a_wrong_path_is_a_404_not_an_ingest(relay):
    _, _, receiver, url = relay
    assert _raw_post(url, {"kind": BATTLEGROUND, "body": "{}"}, path="/anything") == 404
    assert receiver.accepted == 0


# ------------------------------------------------------------------- end to end

def test_a_posted_snapshot_reaches_the_engine_and_becomes_a_message(relay, tmp_path):
    """The whole seam: real captured body → HTTP → reader → engine → WhatsApp text."""
    engine, notifier, _, url = relay
    client = RelayClient(url, SECRET, world="cz8")
    assert client.send(MAP, MAP_DATA.read_text(encoding="utf-8"))
    assert client.send(BATTLEGROUND, SAMPLE.read_text(encoding="utf-8"))

    assert engine.snapshot is not None
    # The capture is a fixed moment in the past, so evaluate it at its own time — the same
    # trick `bap-alert preview --at capture` uses. Note the earliest lock on the map is not
    # the earliest lock *in scope*, so the moment has to come from the events themselves.
    locks = [p.locked_until for p in engine.snapshot.provinces if p.locked_until]
    events = engine.upcoming(min(locks) - 60)
    assert events, "the scheduler should now know about upcoming openings"
    # the map asset came through too, so unnamed provinces have their grid label
    assert all(e.label and not e.label.startswith("#") for e in events)

    at_capture = events[0].opens_at - 60          # one minute before the first one in scope
    sent = engine.tick(at_capture)
    assert sent, "the first opening is inside the lead, so it should go out"
    assert notifier.sent and notifier.sent[0].count("\n") + 1 == len(sent)


def test_the_client_appends_the_path_so_a_bare_host_works(relay):
    """People will configure `--to http://1.2.3.4:8770`; that has to be enough."""
    _, _, receiver, url = relay
    assert RelayClient(url, SECRET).url.endswith(RELAY_PATH)
    assert RelayClient(url + RELAY_PATH, SECRET).url.endswith(RELAY_PATH)
    assert RelayClient(url + "/", SECRET).send(BATTLEGROUND,
                                               SAMPLE.read_text(encoding="utf-8"))
    assert receiver.accepted == 1


def test_a_second_collector_posting_the_same_snapshot_is_harmless(relay):
    """Several people may run a collector; the group must still hear each opening once."""
    engine, notifier, _, url = relay
    body = SAMPLE.read_text(encoding="utf-8")
    RelayClient(url, SECRET).send(BATTLEGROUND, body)
    RelayClient(url, SECRET).send(BATTLEGROUND, body)
    assert engine.snapshot is not None
    assert notifier.sent == []                  # nothing sent merely by arriving


def test_an_unreachable_scheduler_does_not_take_the_collector_down():
    """The collector rides along in someone's browser session; it must never raise."""
    client = RelayClient("http://127.0.0.1:1", "secret")     # nothing listens on port 1
    assert client.send(BATTLEGROUND, "{}") is False
    assert client.failed == 1


# ------------------------------------------------------------------ stale guard

def test_a_stale_snapshot_stops_the_scheduler_talking(tmp_path, now):
    """If every collector goes offline the times are still plausible but wrong — say nothing
    rather than send the group to a province that opened an hour ago."""
    engine, notifier = _engine(tmp_path, max_snapshot_age_minutes=60)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=300)]), now=now)
    assert engine.tick(now) != []                            # fresh: speaks

    engine2, notifier2 = _engine(tmp_path / "b", max_snapshot_age_minutes=60)
    # an opening still ahead at the later moment, so only the guard can silence it
    engine2.on_snapshot(battleground([province(1, owner=ME, opens_in=3 * 3600 + 300)]),
                        now=now)
    assert engine2.tick(now + 3 * 3600) == []                # snapshot 3 h old: quiet
    assert notifier2.sent == []
    assert "TOO OLD" in engine2.status_line(now + 3 * 3600)


def test_a_fresh_snapshot_ends_the_quiet_period(tmp_path, now):
    engine, notifier = _engine(tmp_path, max_snapshot_age_minutes=60)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=3 * 3600 + 300)]),
                       now=now)
    assert engine.tick(now + 3 * 3600) == []
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=3 * 3600 + 300)]),
                       now=now + 3 * 3600)                   # a collector came back online
    assert [e.province_id for e in engine.tick(now + 3 * 3600)] == [1]


def test_the_guard_can_be_switched_off(tmp_path, now):
    engine, _ = _engine(tmp_path, max_snapshot_age_minutes=0)
    engine.on_snapshot(battleground([province(1, owner=ME, opens_in=10 * 3600 + 300)]),
                       now=now)
    assert engine.tick(now + 10 * 3600) != []
