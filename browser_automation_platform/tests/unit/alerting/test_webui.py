"""The control panel: it really serves, it refuses anything unauthenticated, and it never
writes credentials where they don't belong.

These start a real server on an ephemeral port and talk to it over HTTP — the guards are the
point of the module, so testing them through the socket is the only honest way.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from bap.alerting.webui import UiState, load_secrets, save_secrets, serve

SAMPLE = "dataset/api_samples/getBattleground.sample.json"
MAP_DATA = "dataset/api_samples/map_data.volcano_archipelago.sample.json"


@pytest.fixture
def panel(tmp_path):
    state = UiState(tmp_path / "alerting.json", sample=SAMPLE, map_data=MAP_DATA)
    httpd, url = serve(state, port=0, open_browser=False)
    base, token = url.split("/?")[0], url.split("?t=")[1]
    try:
        yield state, base, token
    finally:
        httpd.shutdown()


def _get(base, path, token=None, headers=None):
    url = f"{base}{path}" + (f"?t={token}" if token else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}),
                                timeout=5) as resp:
        return resp.status, resp.read()


def _post(base, path, token, body):
    req = urllib.request.Request(f"{base}{path}?t={token}",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _status(base, path, token=None, headers=None):
    try:
        return _get(base, path, token, headers)[0]
    except urllib.error.HTTPError as exc:
        return exc.code


# ------------------------------------------------------------------------ guards

def test_the_page_needs_the_token(panel):
    _, base, token = panel
    assert _status(base, "/api/state") == 403
    assert _status(base, "/api/state", "wrong-token") == 403
    assert _status(base, "/api/state", token) == 200


def test_a_foreign_host_header_is_refused(panel):
    """DNS rebinding: a page on another origin resolving to 127.0.0.1 must not get in, even
    holding a guessed token."""
    _, base, token = panel
    assert _status(base, "/api/state", token, {"Host": "evil.example.com"}) == 403


def test_it_binds_loopback_only(tmp_path):
    state = UiState(tmp_path / "alerting.json")
    httpd, _ = serve(state, port=0, open_browser=False)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.shutdown()


# ------------------------------------------------------------------------- panel

def test_state_describes_the_config_and_the_map(panel):
    _, base, token = panel
    body = json.loads(_get(base, "/api/state", token)[1])
    assert len(body["labels"]) == 60                  # every province on the captured map
    assert body["labels"][0]["generated"]             # the 4x4 grid hint is filled in
    assert "labeled" in body["scopes"] and "battle_type" in body["side_rules"]
    assert body["creds"]["has_token"] is False        # nothing configured in a fresh dir


def test_preview_renders_a_custom_template(panel):
    _, base, token = panel
    out = _post(base, "/api/preview", token,
                {"template": "{time} {label} ({side})", "show_attrition": True,
                 "header": "GBG"})
    lines = out["text"].split("\n")
    assert lines[0] == "GBG"
    assert lines[1].endswith("(attack)") or lines[1].endswith("(defence)")
    assert "%" not in lines[1]                        # {pct} was not in the template


def test_preview_leaves_no_gap_when_a_province_has_no_badge(panel):
    _, base, token = panel
    out = _post(base, "/api/preview", token,
                {"template": "{time} {emoji} {label} {pct}", "show_attrition": True,
                 "header": ""})
    assert not any(line.endswith(" ") or "  " in line for line in out["text"].split("\n"))


def test_saving_labels_feeds_straight_back_into_the_preview(panel, tmp_path, monkeypatch):
    state, base, token = panel
    monkeypatch.chdir(tmp_path)
    first = json.loads(_get(base, "/api/state", token)[1])["labels"][0]["id"]
    _post(base, "/api/labels", token, {"labels": {str(first): "ZZ9"}})
    assert state.labels.label(first) == "ZZ9"


def test_config_is_saved_without_the_credentials(panel, tmp_path):
    state, base, token = panel
    _post(base, "/api/credentials", token,
          {"creds": {"id_instance": "1101", "api_token": "sekret", "chat_id": "1@g.us"},
           "persist": False})
    _post(base, "/api/config", token, {"config": {"window_minutes": 45}})
    written = json.loads((tmp_path / "alerting.json").read_text(encoding="utf-8"))
    assert written["window_minutes"] == 45
    assert "sekret" not in json.dumps(written)        # credentials never land in the config


def test_credentials_stay_in_memory_until_explicitly_saved(panel, tmp_path, monkeypatch):
    state, base, token = panel
    monkeypatch.chdir(tmp_path)
    out = _post(base, "/api/credentials", token,
                {"creds": {"api_token": "sekret"}, "persist": False})
    assert out["ok"] and "paměti" in out["detail"]
    assert not (tmp_path / "alerting.secrets.json").exists()
    assert state.creds["api_token"] == "sekret"       # …but usable for a test send


def test_saving_credentials_writes_only_the_secrets_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_secrets({"api_token": "sekret"})
    assert load_secrets() == {"api_token": "sekret"}
    assert (tmp_path / "alerting.secrets.json").stat().st_mode & 0o077 == 0


def test_check_reports_missing_credentials_instead_of_calling_out(tmp_path):
    """No network: an unconfigured instance must fail fast, not hang on a request."""
    state = UiState(tmp_path / "alerting.json")
    state.creds = {"id_instance": "", "api_token": "", "chat_id": ""}
    out = state.check()
    assert out["ok"] is False and "chybí" in out["detail"]


def test_attach_makes_info_actually_reach_the_buffer(tmp_path, monkeypatch):
    """Without setting the level the panel sits empty and reads as broken."""
    import logging

    from bap.alerting.webui import LogBuffer

    monkeypatch.chdir(tmp_path)
    log = logging.getLogger("bap.alerting")
    monkeypatch.setattr(log, "handlers", list(log.handlers))
    level = log.level
    try:
        log.setLevel(logging.WARNING)
        buf = LogBuffer().attach()
        logging.getLogger("bap.alerting").info("hello from the engine")
        assert any("hello from the engine" in line for line in buf.tail())
    finally:
        log.setLevel(level)


def test_the_startup_log_line_does_not_carry_the_token(panel):
    """The log panel is what gets screenshotted; the token is a credential."""
    state, _, token = panel
    assert not any(token in line for line in state.log.tail())


def test_the_log_panel_shows_what_the_alerter_logged(panel):
    state, base, token = panel
    state.log.lines.append("12:00:00  INFO    sent 3 opening(s)")
    body = json.loads(_get(base, "/api/log", token)[1])
    assert any("sent 3 opening(s)" in line for line in body["lines"])
