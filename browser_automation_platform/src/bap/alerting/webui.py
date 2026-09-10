"""A small local control panel for the alerter — ``bap-alert ui``.

Four things the command line is bad at:

* **the message format** — typing a template and seeing it rendered against real openings,
* **the labels book** — 60 rows of "province id → what the guild calls it",
* **the Green API credentials** — pasting them, checking the instance is authorised, and
  sending one test message to the group before ever pointing the alerter at it,
* **the log** — what was decided and what was sent, without reading a terminal.

Deliberately a local web page rather than a desktop toolkit: the alerting subproject has no
dependencies beyond the standard library (and should keep it that way, because the scheduler
half is meant to run on a cheap headless box), while a browser is available in both places.

Safety, since this page can hold WhatsApp credentials:

* it binds **127.0.0.1** only, never a public interface;
* every request must carry a random token minted at startup, which is why the URL printed on
  the console has ``?t=…`` on it — that stops any other page in the browser from POSTing to
  this server behind your back;
* the ``Host`` header must be loopback, which closes DNS-rebinding;
* credentials entered here stay **in memory** unless you explicitly save them, and then they
  go to a separate ``alerting.secrets.json`` (mode 600), never into ``alerting.json``.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bap.alerting.config import DEFAULT_CONFIG_PATH, AlertConfig
from bap.alerting.labels import LabelBook, auto_labels
from bap.alerting.notifiers import GreenApiNotifier
from bap.alerting.render import PLACEHOLDERS, format_message
from bap.alerting.schedule import SCOPES, SIDE_RULES, unlock_events

logger = logging.getLogger("bap.alerting")

SECRETS_PATH = "alerting.secrets.json"

#: Czech wording for the page. Keyed by placeholder; anything missing falls back to the
#: English description in :data:`bap.alerting.render.PLACEHOLDERS`.
PLACEHOLDER_CS = {
    "{time}": "čas otevření, pražský, HH:MM",
    "{emoji}": "🔴 útok / 🔵 obrana",
    "{label}": "souřadnice gildy, např. D4A",
    "{pct}": "oslabení jako [20%] — prázdné, když hra žádné nehlásí",
    "{pct_num}": "totéž jen číslo, např. 20 — prázdné, když žádné není",
    "{side}": "slovem: attack / defence",
    "{id}": "id provincie, jak ho používá hra",
}
_LOG_LINES = 300


class LogBuffer(logging.Handler):
    """Keeps the last few hundred log lines so the page can show them."""

    def __init__(self, capacity: int = _LOG_LINES) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=capacity)

    def attach(self, name: str = "bap.alerting") -> "LogBuffer":
        """Hook this buffer onto the alerter's logger *and* make sure INFO actually reaches
        it — without the level the page would sit there empty and look broken."""
        log = logging.getLogger(name)
        log.addHandler(self)
        if log.getEffectiveLevel() > logging.INFO:
            log.setLevel(logging.INFO)
        return self

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stamp = logging.Formatter("%(asctime)s", "%H:%M:%S").formatTime(record, "%H:%M:%S")
            self.lines.append(f"{stamp}  {record.levelname:<7} {record.getMessage()}")
        except Exception:                      # a UI log must never break the alerter
            pass

    def tail(self, n: int = _LOG_LINES) -> list[str]:
        return list(self.lines)[-n:]


def load_secrets(path=SECRETS_PATH) -> dict:
    """Credentials saved from the UI. Missing or unreadable → nothing, never an error."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def save_secrets(values: dict, path=SECRETS_PATH) -> None:
    """Write the credentials to their own file, readable only by this user."""
    p = Path(path)
    p.write_text(json.dumps(values, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass                                   # Windows and odd filesystems: best effort


class UiState:
    """Everything the page reads and writes. One instance per ``bap-alert ui``."""

    def __init__(self, config_path=DEFAULT_CONFIG_PATH, *, sample=None, map_data=None,
                 log: LogBuffer | None = None) -> None:
        self.config_path = Path(config_path)
        self.log = log or LogBuffer()
        self.cfg = AlertConfig.load(self.config_path)
        self.creds = {"id_instance": self.cfg.green_api.id_instance,
                      "api_token": self.cfg.green_api.api_token,
                      "chat_id": self.cfg.green_api.chat_id}
        self.creds.update({k: v for k, v in load_secrets().items() if v})
        self._sample = _read_json(sample)
        self._layout = _map_layout(_read_json(map_data))
        self.labels = LabelBook.build(path=self.cfg.labels_file or None,
                                      layout=self._layout)

    # ------------------------------------------------------------------ preview

    def preview_events(self, limit: int = 12):
        """Openings from the captured sample, so the format can be tried offline."""
        from bap.forge.gbg_data import parse

        if not self._sample:
            return []
        bg = parse(self._sample)
        if bg is None:
            return []
        locks = [p.locked_until for p in bg.provinces if p.locked_until]
        now = (min(locks) - 60) if locks else 0
        events = unlock_events(bg, labels=self.labels, scope=self.cfg.scope, now=now,
                               horizon_seconds=self.cfg.horizon_seconds,
                               side_rule=self.cfg.side_rule)
        return events[:limit]

    def preview_text(self, template: str, *, show_attrition: bool, header: str) -> str:
        events = self.preview_events()
        if not events:
            return "(žádná ukázková data — spusť s --sample nad zachyceným payloadem)"
        return format_message(events, header=header, show_attrition=show_attrition,
                              template=template)

    # ------------------------------------------------------------------- labels

    def map_view(self) -> dict:
        """The flag positions, so the panel can draw the map instead of asking someone to
        match sixty numbers to sixty flags by eye. Empty when no map asset has been seen."""
        layout = self._layout
        flags = dict(getattr(layout, "flags", None) or {})
        if not flags:
            return {"flags": [], "width": 0, "height": 0, "map_id": ""}
        return {
            "flags": [{"id": pid, "x": x, "y": y} for pid, (x, y) in sorted(flags.items())],
            "width": getattr(layout, "width", 0) or 0,
            "height": getattr(layout, "height", 0) or 0,
            "map_id": getattr(layout, "map_id", "") or "",
        }

    def label_rows(self) -> list[dict]:
        """One row per province the map asset knows about: the generated grid position and
        whatever the guild has named it."""
        generated = auto_labels(self._layout) if self._layout is not None else {}
        ids = sorted(set(generated) | set(self.labels.overrides))
        return [{"id": pid, "generated": generated.get(pid, ""),
                 "name": self.labels.overrides.get(pid, "")} for pid in ids]

    def save_labels(self, mapping: dict) -> str:
        path = self.cfg.labels_file or f"province_labels.{self.cfg.world}.json"
        clean = {str(int(k)): str(v).strip() for k, v in mapping.items() if str(v).strip()}
        body = {"labels": clean}
        map_id = getattr(self._layout, "map_id", "") or ""
        if map_id:                             # the asset body often carries no id at all
            body = {"map_id": map_id, "labels": clean}
        Path(path).write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")
        self.labels = LabelBook.build(path=path, layout=self._layout)
        logger.info("labels: saved %d name(s) to %s", len(clean), path)
        return path

    # -------------------------------------------------------------------- config

    def save_config(self, values: dict) -> None:
        """Merge the page's settings into ``alerting.json``, leaving unknown keys alone and
        never writing credentials into it."""
        try:
            current = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except Exception:
            current = {}
        current.update(values)
        current.pop("green_api", None)
        self.config_path.write_text(json.dumps(current, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
        self.cfg = AlertConfig.load(self.config_path)
        logger.info("config: saved %s", self.config_path)

    # ----------------------------------------------------------------- green api

    def notifier(self) -> GreenApiNotifier:
        return GreenApiNotifier(self.creds.get("id_instance", ""),
                                self.creds.get("api_token", ""),
                                self.creds.get("chat_id", ""),
                                base_url=self.cfg.green_api.base_url)

    def check(self) -> dict:
        missing = [k for k in ("id_instance", "api_token") if not self.creds.get(k)]
        if missing:
            return {"ok": False, "detail": f"chybí: {', '.join(missing)}"}
        try:
            state = self.notifier().state()
        except Exception as exc:
            logger.warning("green-api check failed: %s", exc)
            return {"ok": False, "detail": str(exc)}
        ok = str(state.get("stateInstance", "")).lower() == "authorized"
        logger.info("green-api check: %s", state.get("stateInstance", state))
        return {"ok": ok, "detail": json.dumps(state, ensure_ascii=False)}

    def send_test(self, text: str) -> dict:
        if not self.creds.get("chat_id"):
            return {"ok": False, "detail": "chybí: chat_id"}
        ok = self.notifier().send(text)
        logger.info("green-api test send: %s", "delivered" if ok else "FAILED")
        return {"ok": ok, "detail": "odesláno" if ok else "brána zprávu odmítla"}


def _read_json(path):
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _map_layout(obj):
    if not obj:
        return None
    try:
        from bap.forge.gbg_data import parse_map_data

        return parse_map_data(obj)
    except Exception:
        return None


# --------------------------------------------------------------------------- http


class _Handler(BaseHTTPRequestHandler):
    server_version = "bap-alert-ui"
    state: UiState
    token: str

    def log_message(self, fmt, *args):          # keep the console for the alerter's own log
        pass

    # -- guards ------------------------------------------------------------

    def _authorised(self, query: dict) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            return False                        # DNS rebinding
        supplied = (self.headers.get("X-Ui-Token") or (query.get("t") or [""])[0])
        return secrets.compare_digest(supplied, self.token)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # -- routes ------------------------------------------------------------

    def do_GET(self):                            # noqa: N802 (http.server's spelling)
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")   # the browser asks unauthenticated
        if not self._authorised(query):
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        if url.path == "/":
            return self._send(200, PAGE.replace("__TOKEN__", self.token).encode("utf-8"),
                              "text/html; charset=utf-8")
        if url.path == "/api/state":
            return self._json(self._state_payload())
        if url.path == "/api/log":
            return self._json({"lines": self.state.log.tail()})
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):                           # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorised(query):
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json({"ok": False, "detail": "poškozený požadavek"}, 400)
        try:
            return self._json(self._dispatch(url.path, payload))
        except Exception as exc:                 # a UI slip must not kill the server
            logger.warning("ui: %s failed: %s", url.path, exc)
            return self._json({"ok": False, "detail": str(exc)}, 500)

    def _dispatch(self, path: str, payload: dict) -> dict:
        st = self.state
        if path == "/api/preview":
            return {"ok": True, "text": st.preview_text(
                payload.get("template") or "",
                show_attrition=bool(payload.get("show_attrition", True)),
                header=str(payload.get("header") or ""))}
        if path == "/api/config":
            st.save_config(payload.get("config") or {})
            return {"ok": True, "detail": f"uloženo do {st.config_path}"}
        if path == "/api/labels":
            return {"ok": True, "detail": f"uloženo do {st.save_labels(payload.get('labels') or {})}"}
        if path == "/api/credentials":
            st.creds.update({k: str(v).strip() for k, v in (payload.get("creds") or {}).items()})
            if payload.get("persist"):
                save_secrets(st.creds)
                return {"ok": True, "detail": f"uloženo do {SECRETS_PATH} (práva 600)"}
            return {"ok": True, "detail": "drženo jen v paměti — na disk nic nezapsáno"}
        if path == "/api/check":
            return st.check()
        if path == "/api/test":
            return st.send_test(str(payload.get("text") or "test"))
        return {"ok": False, "detail": "neznámý endpoint"}

    def _state_payload(self) -> dict:
        st = self.state
        cfg = st.cfg
        return {
            "config": {
                "world": cfg.world, "scope": cfg.scope,
                "trigger_lead_minutes": cfg.trigger_lead_minutes,
                "window_minutes": cfg.window_minutes,
                "side_rule": cfg.side_rule, "show_attrition": cfg.show_attrition,
                "message_template": cfg.message_template, "header": cfg.header,
                "quiet_hours": list(cfg.quiet_hours) if cfg.quiet_hours else None,
                "notifier": cfg.notifier,
            },
            "scopes": list(SCOPES),
            "side_rules": list(SIDE_RULES),
            "placeholders": [{"key": k, "what": PLACEHOLDER_CS.get(k, w)}
                             for k, w in PLACEHOLDERS],
            "creds": {"id_instance": st.creds.get("id_instance", ""),
                      "chat_id": st.creds.get("chat_id", ""),
                      "has_token": bool(st.creds.get("api_token"))},
            "labels": st.label_rows(),
            "map": st.map_view(),
            "config_path": str(st.config_path),
            "log": st.log.tail(60),
        }


def serve(state: UiState, *, port: int = 8765, open_browser: bool = True):
    """Start the panel and return the server (already serving on its own thread)."""
    token = secrets.token_urlsafe(24)
    handler = type("_BoundHandler", (_Handler,), {"state": state, "token": token})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{httpd.server_port}/?t={token}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    # The token is a credential: the console gets the full URL, the log panel does not —
    # that panel is exactly what someone screenshots when asking for help.
    logger.info("ui: listening on http://127.0.0.1:%d/ (token in the console URL)",
                httpd.server_port)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return httpd, url


PAGE = """<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><title>FoE Alerting</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{--bg:#14161a;--panel:#1c1f26;--line:#2b3038;--ink:#e6e8ec;--dim:#98a0ad;
       --acc:#5b9dd9;--ok:#4a9d6b;--bad:#c25a5a}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif}
 header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;
        align-items:baseline;gap:12px}
 h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.02em}
 .sub{color:var(--dim);font-size:12px}
 main{max-width:1000px;margin:0 auto;padding:20px;display:grid;gap:16px}
 section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px}
 h2{font-size:13px;margin:0 0 12px;font-weight:600;text-transform:uppercase;
    letter-spacing:.06em;color:var(--dim)}
 label{display:block;font-size:12px;color:var(--dim);margin:10px 0 4px}
 input,select,textarea{width:100%;background:#111317;color:var(--ink);
   border:1px solid var(--line);border-radius:5px;padding:7px 9px;font:inherit}
 textarea{font-family:ui-monospace,Menlo,Consolas,monospace;resize:vertical}
 input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc)}
 .row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0 12px}
 button{background:#262b34;color:var(--ink);border:1px solid var(--line);border-radius:5px;
        padding:7px 14px;font:inherit;cursor:pointer}
 button:hover{border-color:var(--acc)}
 button.primary{background:var(--acc);border-color:var(--acc);color:#0d1116;font-weight:600}
 .bar{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;align-items:center}
 pre{background:#0e1014;border:1px solid var(--line);border-radius:5px;padding:12px;
     margin:0;overflow:auto;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
 .msg{white-space:pre-wrap}
 .hint{font-size:12px;color:var(--dim);margin-top:8px}
 .hint code{color:var(--acc)}
 #mapwrap{position:relative;margin:0 0 14px;background:#0e1014;border:1px solid var(--line);
          border-radius:6px;padding:10px}
 #map{display:block;width:100%;height:auto}
 #map .flag{cursor:pointer}
 #map .dot{fill:#3a4048;stroke:#565e6b;stroke-width:6}
 #map .flag.named .dot{fill:var(--acc);stroke:#8fc4ee}
 #map .flag.sel .dot{stroke:#fff;stroke-width:12}
 #map .flag:hover .dot{stroke:#fff}
 #map text{fill:var(--ink);font:600 34px ui-monospace,Menlo,Consolas,monospace;
           text-anchor:middle;pointer-events:none}
 #map .flag.named text{fill:#0d1116}
 .lrow{display:flex;gap:8px;margin-bottom:6px;align-items:center}
 .lrow select{width:170px;font-family:ui-monospace,Menlo,Consolas,monospace}
 .lrow input{flex:1}
 .lrow button{padding:7px 10px;color:var(--dim)}
 .lrow button:hover{color:var(--bad);border-color:var(--bad)}
 .flash{font-size:12px;padding:6px 0}
 .flash.ok{color:var(--ok)} .flash.bad{color:var(--bad)}
 .logbox{max-height:260px;min-height:64px}
 .warn{border-left:2px solid #8a6d3b;padding-left:10px;color:var(--dim);font-size:12px}
</style></head><body>
<header><h1>FoE Alerting</h1><span class="sub" id="where"></span></header>
<main>

<section><h2>Formát zprávy</h2>
  <label>Šablona jednoho řádku</label>
  <input id="tpl">
  <div class="row">
    <div><label>Hlavička (nepovinná)</label><input id="header"></div>
    <div><label>Procento oslabení</label>
      <select id="pct"><option value="1">zobrazovat</option>
                       <option value="0">skrýt</option></select></div>
  </div>
  <div class="hint" id="ph"></div>
  <label>Náhled na zachycených datech</label>
  <pre class="msg" id="prev">…</pre>
  <div class="bar"><button onclick="preview()">Přepočítat náhled</button>
    <button class="primary" onclick="saveCfg()">Uložit formát</button>
    <span class="flash" id="f-cfg"></span></div>
</section>

<section><h2>Dávkování a rozsah</h2>
  <div class="row">
    <div><label>Předstih (min)</label><input id="lead" type="number" step="0.5"></div>
    <div><label>Okno (min)</label><input id="win" type="number" step="1"></div>
    <div><label>Rozsah</label><select id="scope"></select></div>
    <div><label>Pravidlo barev</label><select id="side"></select></div>
  </div>
  <div class="hint">Mlčí, dokud nejbližší neohlášené otevření není <code>předstih</code>
    daleko, pak pošle všechno, co se otevře do <code>okna</code>, v jedné zprávě.</div>
  <div class="bar"><button class="primary" onclick="saveCfg()">Uložit</button>
    <span class="flash" id="f-cfg2"></span></div>
</section>

<section><h2>Labely provincií</h2>
  <div class="hint">Pojmenuj jen ty provincie, které gilda opravdu řeší — nepojmenované se
    ohlásí vygenerovanou pozicí v mřížce (v závorce u čísla). Přidávej si řádky podle
    potřeby; se scope <code>labeled</code> se hlásí právě jen ty pojmenované.</div>
  <div id="mapwrap"><svg id="map"></svg></div>
  <div class="hint" id="maphint" style="margin-top:-6px"></div>
  <div id="labels"></div>
  <div class="bar"><button onclick="addLabelRow()">+ Přidat</button>
    <button class="primary" onclick="saveLabels()">Uložit labely</button>
    <span class="flash" id="f-lab"></span></div>
</section>

<section><h2>WhatsApp (Green API)</h2>
  <div class="row">
    <div><label>idInstance</label><input id="gid" autocomplete="off"></div>
    <div><label>apiTokenInstance</label><input id="gtok" type="password" autocomplete="off"
         placeholder="(nezměněno)"></div>
  </div>
  <label>chatId skupiny (končí na @g.us)</label><input id="gchat" autocomplete="off">
  <div class="bar">
    <button onclick="creds(false)">Použít</button>
    <button onclick="creds(true)">Uložit na disk</button>
    <button onclick="check()">Ověřit instanci</button>
    <button class="primary" onclick="test()">Poslat testovací zprávu</button>
    <span class="flash" id="f-wa"></span></div>
  <pre id="wa-out" style="margin-top:10px">–</pre>
  <div class="hint warn">„Uložit na disk“ zapíše údaje do
    <code>alerting.secrets.json</code> (práva 600), ne do <code>alerting.json</code>.
    Bez toho platí jen do konce běhu tohoto okna.</div>
</section>

<section><h2>Log</h2>
  <pre class="logbox" id="log">(zatím nic)</pre>
  <div class="bar"><button onclick="loadLog()">Obnovit</button>
    <label style="margin:0"><input type="checkbox" id="auto" checked style="width:auto">
      auto (5 s)</label></div>
</section>
</main>
<script>
const T = "__TOKEN__";
const api = (p, body) => fetch(p + "?t=" + T, body ? {method:"POST",
    headers:{"Content-Type":"application/json","X-Ui-Token":T},
    body: JSON.stringify(body)} : {headers:{"X-Ui-Token":T}}).then(r => r.json());
const $ = id => document.getElementById(id);
const flash = (id, ok, msg) => { const e = $(id);
    e.className = "flash " + (ok ? "ok" : "bad"); e.textContent = msg;
    setTimeout(() => { e.textContent = ""; }, 6000); };

let ST = null;

function fill(sel, values, chosen) {
  sel.innerHTML = "";
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v; if (v === chosen) o.selected = true;
    sel.appendChild(o);
  }
}

async function load() {
  ST = await api("/api/state");
  const c = ST.config;
  $("where").textContent = c.world + " · " + ST.config_path;
  $("tpl").value = c.message_template;
  $("header").value = c.header || "";
  $("pct").value = c.show_attrition ? "1" : "0";
  $("lead").value = c.trigger_lead_minutes;
  $("win").value = c.window_minutes;
  fill($("scope"), ST.scopes, c.scope);
  fill($("side"), ST.side_rules, c.side_rule);
  $("ph").innerHTML = "Zástupné znaky: " +
      ST.placeholders.map(p => "<code>" + p.key + "</code> " + p.what).join(" · ");
  $("gid").value = ST.creds.id_instance;
  $("gchat").value = ST.creds.chat_id;
  if (!ST.creds.has_token) $("gtok").placeholder = "(nevyplněno)";
  drawLabels();
  $("log").textContent = ST.log.join("\\n") || "(zatím nic)";
  preview();
}

async function preview() {
  const r = await api("/api/preview", {template: $("tpl").value,
      show_attrition: $("pct").value === "1", header: $("header").value});
  $("prev").textContent = r.text || "(nic)";
}

async function saveCfg() {
  const cfg = {message_template: $("tpl").value, header: $("header").value,
      show_attrition: $("pct").value === "1",
      trigger_lead_minutes: parseFloat($("lead").value),
      window_minutes: parseFloat($("win").value),
      scope: $("scope").value, side_rule: $("side").value};
  const r = await api("/api/config", {config: cfg});
  flash("f-cfg", r.ok, r.detail); flash("f-cfg2", r.ok, r.detail);
  preview(); loadLog();
}

// The map has 60 provinces and the guild names a handful, so the panel is a short list you
// add to — not a 60-row table to scroll past every time.
function labelRow(pid, name) {
  const row = document.createElement("div");
  row.className = "lrow";
  const sel = document.createElement("select");
  for (const r of ST.labels) {
    const o = document.createElement("option");
    o.value = r.id;
    o.textContent = "#" + r.id + (r.generated ? "  (" + r.generated + ")" : "");
    if (r.id === pid) o.selected = true;
    sel.appendChild(o);
  }
  const inp = document.createElement("input");
  inp.value = name || "";
  inp.placeholder = "název gildy, např. A1X";
  const del = document.createElement("button");
  del.textContent = "✕"; del.title = "odebrat řádek";
  del.onclick = () => { row.remove(); if (!$("labels").children.length) addLabelRow(); };
  row.append(sel, inp, del);
  return row;
}

function firstUnusedProvince() {
  const used = new Set([...document.querySelectorAll(".lrow select")].map(s => +s.value));
  const free = ST.labels.find(r => !used.has(r.id));
  return free ? free.id : (ST.labels[0] ? ST.labels[0].id : 0);
}

function addLabelRow() {
  if (!ST.labels.length) return;
  $("labels").appendChild(labelRow(firstUnusedProvince(), ""));
}

// Sixty numbers against sixty flags is not a job for the eye. The map asset gives the real
// flag coordinates, so draw them: the constellation matches what the game shows, and clicking
// a flag jumps straight to naming it.
function drawMap() {
  const m = ST.map, svg = $("map"), wrap = $("mapwrap");
  if (!m || !m.flags.length) { wrap.style.display = "none"; return; }
  wrap.style.display = "";
  const named = new Map(ST.labels.filter(r => r.name).map(r => [r.id, r.name]));
  const xs = m.flags.map(f => f.x), ys = m.flags.map(f => f.y);
  const pad = 70;
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad;
  const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
  svg.innerHTML = m.flags.map(f => {
    const name = named.get(f.id);
    const text = name || f.id;
    const cls = "flag" + (name ? " named" : "");
    return `<g class="${cls}" data-id="${f.id}">` +
           `<circle class="dot" cx="${f.x}" cy="${f.y}" r="46"></circle>` +
           `<text x="${f.x}" y="${f.y + 12}">${String(text).slice(0, 4)}</text>` +
           `<title>provincie #${f.id}${name ? " — " + name : ""}</title></g>`;
  }).join("");
  svg.querySelectorAll(".flag").forEach(g => {
    g.onclick = () => focusProvince(+g.dataset.id);
  });
  const n = named.size;
  const word = n === 1 ? "pojmenovaná" : (n >= 2 && n <= 4 ? "pojmenované" : "pojmenovaných");
  $("maphint").textContent =
    `${m.flags.length} provincií${m.map_id ? " · mapa " + m.map_id : ""} · ` +
    `${n} ${word} — klikni na vlaječku a napiš, jak jí říkáte`;
}

// Clicking a flag should land the cursor in the right box, whether that row exists yet or not.
function focusProvince(pid) {
  const rows = [...document.querySelectorAll(".lrow")];
  let row = rows.find(r => +r.querySelector("select").value === pid);
  if (!row) {
    // Reuse an untouched row rather than leaving a trail of empty ones behind.
    row = rows.find(r => !r.querySelector("input").value.trim());
    if (row) row.querySelector("select").value = pid;
    else $("labels").appendChild(row = labelRow(pid, ""));
  }
  document.querySelectorAll(".flag").forEach(g => g.classList.remove("sel"));
  const dot = document.querySelector(`.flag[data-id="${pid}"]`);
  if (dot) dot.classList.add("sel");
  const input = row.querySelector("input");
  input.focus();
  input.select();
  row.scrollIntoView({block: "nearest"});
}

function drawLabels() {
  const box = $("labels");
  box.innerHTML = "";
  if (!ST.labels.length) {
    box.innerHTML = "<div class='hint'>Žádná data mapy — spusť s <code>--map-data</code>.</div>";
    return;
  }
  const named = ST.labels.filter(r => r.name);
  if (named.length) named.forEach(r => box.appendChild(labelRow(r.id, r.name)));
  else addLabelRow();                       // a fresh setup starts with one empty row
  drawMap();
}

async function saveLabels() {
  const out = {};
  document.querySelectorAll(".lrow").forEach(row => {
    const pid = row.querySelector("select").value;
    const name = row.querySelector("input").value.trim();
    if (name) out[pid] = name;
  });
  const r = await api("/api/labels", {labels: out});
  flash("f-lab", r.ok, r.detail);
  ST = await api("/api/state");
  drawLabels();
  preview(); loadLog();
}

async function creds(persist) {
  const c = {id_instance: $("gid").value, chat_id: $("gchat").value};
  if ($("gtok").value) c.api_token = $("gtok").value;
  const r = await api("/api/credentials", {creds: c, persist: persist});
  flash("f-wa", r.ok, r.detail);
  $("gtok").value = ""; $("gtok").placeholder = "(uloženo)";
  loadLog();
}

async function check() {
  await creds(false);
  $("wa-out").textContent = "…";
  const r = await api("/api/check", {});
  $("wa-out").textContent = r.detail;
  flash("f-wa", r.ok, r.ok ? "instance je autorizovaná" : "instance NENÍ připravená");
  loadLog();
}

async function test() {
  await creds(false);
  const r = await api("/api/test", {text: $("prev").textContent.split("\\n")[0] || "test"});
  $("wa-out").textContent = r.detail;
  flash("f-wa", r.ok, r.ok ? "odesláno do skupiny" : "neodesláno");
  loadLog();
}

async function loadLog() {
  const r = await api("/api/log");
  $("log").textContent = r.lines.join("\\n") || "(zatím nic)";
  $("log").scrollTop = $("log").scrollHeight;
}

setInterval(() => { if ($("auto").checked) loadLog(); }, 5000);
load();
</script></body></html>
"""


__all__ = ["LogBuffer", "UiState", "serve", "load_secrets", "save_secrets", "SECRETS_PATH"]
