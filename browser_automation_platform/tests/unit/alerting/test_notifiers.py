"""Transports: the Green API call shape, retries, and the safe fallbacks."""

from __future__ import annotations

import io
import json

from bap.alerting.config import AlertConfig
from bap.alerting.notifiers import (
    ConsoleNotifier,
    GreenApiNotifier,
    WebhookNotifier,
    build_notifier,
)


class FakeOpener:
    """Stands in for urllib.request.urlopen: records requests, replays canned answers."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers) or [{"idMessage": "ABC"}]
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, req, timeout=None):
        body = getattr(req, "data", None)
        self.calls.append((req.full_url, json.loads(body) if body else {}))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return _Response(json.dumps(answer))


class _Response(io.BytesIO):
    def __init__(self, text: str) -> None:
        super().__init__(text.encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_green_api_posts_chat_id_and_message():
    opener = FakeOpener({"idMessage": "3EB0"})
    api = GreenApiNotifier("1101", "tok", "12036@g.us", base_url="https://x.test",
                           opener=opener)
    assert api.send("16:25 🔵 A1X") is True
    url, payload = opener.calls[0]
    assert url == "https://x.test/waInstance1101/sendMessage/tok"
    assert payload == {"chatId": "12036@g.us", "message": "16:25 🔵 A1X"}


def test_green_api_retries_then_gives_up_quietly():
    opener = FakeOpener(OSError("boom"))
    api = GreenApiNotifier("1", "t", "c", opener=opener, retries=2, sleep=lambda s: None)
    assert api.send("x") is False                 # no exception escapes into the watcher
    assert len(opener.calls) == 3                 # first try + 2 retries


def test_green_api_recovers_on_a_retry():
    opener = FakeOpener(OSError("boom"), {"idMessage": "ok"})
    api = GreenApiNotifier("1", "t", "c", opener=opener, retries=1, sleep=lambda s: None)
    assert api.send("x") is True


def test_green_api_reports_a_rejected_message():
    opener = FakeOpener({"error": "quota"})
    api = GreenApiNotifier("1", "t", "c", opener=opener, retries=0)
    assert api.send("x") is False


def test_green_api_state():
    api = GreenApiNotifier("1", "t", "c", opener=FakeOpener({"stateInstance": "authorized"}))
    assert api.state()["stateInstance"] == "authorized"


def test_webhook_posts_text():
    opener = FakeOpener({})
    assert WebhookNotifier("https://hook.test/x", opener=opener).send("hi") is True
    assert opener.calls[0][1] == {"text": "hi"}


def test_build_notifier_selects_green_api(monkeypatch):
    monkeypatch.setenv("GREEN_API_ID_INSTANCE", "1101")
    monkeypatch.setenv("GREEN_API_TOKEN", "tok")
    monkeypatch.setenv("GREEN_API_CHAT_ID", "12036@g.us")
    cfg = AlertConfig.from_dict({"notifier": "green_api"})
    assert isinstance(build_notifier(cfg), GreenApiNotifier)


def test_incomplete_green_api_config_prints_instead_of_going_silent():
    cfg = AlertConfig.from_dict({"notifier": "green_api", "green_api": {"chat_id": "c"}})
    assert isinstance(build_notifier(cfg), ConsoleNotifier)


def test_unknown_notifier_falls_back_to_console():
    assert isinstance(build_notifier(AlertConfig.from_dict({"notifier": "carrier-pigeon"})),
                      ConsoleNotifier)
    assert isinstance(build_notifier(AlertConfig.from_dict({"notifier": "webhook"})),
                      ConsoleNotifier)          # webhook selected but no url
