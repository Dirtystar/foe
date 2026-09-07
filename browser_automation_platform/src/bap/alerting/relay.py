"""Splitting the alerter in two, so the sending half does not need the game.

The problem this solves: a snapshot describes ~3.7 h of openings, but somebody's browser has
to *produce* one, and that browser is only on while somebody is playing. Meanwhile the part
that decides "say this at 21:31" needs nothing but a clock — and running the whole thing on
several people's PCs at once means the group gets every message once per person.

So:

**Collector** (``bap-alert collect``) — needs the game, a browser and an account. Watches one
world's tab exactly like ``bap-alert run`` does, but instead of deciding anything it forwards
the raw response body to a scheduler. Several people can run one; duplicates are harmless
because the scheduler keeps only the newest snapshot.

**Scheduler** (``bap-alert serve``) — needs a clock and internet. Holds the latest snapshot,
runs the engine, sends to WhatsApp. **One of these exists**, which is what makes the message
arrive once. It never sees a game credential, so a compromise there cannot reach an account.

The wire format is the game's own response body, forwarded verbatim and parsed on the far side
by the same :class:`~bap.forge.gbg_data.live.LiveGbgReader`. Nothing is re-encoded in between,
so the scheduler cannot disagree with the collector about what the game said.

Authentication is a shared secret in ``Authorization: Bearer``, from ``ALERT_RELAY_SECRET`` on
both sides. It is not a user account: anyone holding it can feed the scheduler snapshots, which
is why the scheduler ignores anything that does not parse as the world it watches.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("bap.alerting.relay")

SECRET_ENV = "ALERT_RELAY_SECRET"
RELAY_PATH = "/snapshot"

#: A getBattleground body is ~20 KB; the map asset is bigger. Anything past this is not ours.
MAX_BODY_BYTES = 4 * 1024 * 1024

BATTLEGROUND = "battleground"
MAP = "map"


def secret_from_env(explicit: str = "") -> str:
    return explicit or os.environ.get(SECRET_ENV, "")


# --------------------------------------------------------------------- collector


class RelayClient:
    """Posts response bodies to the scheduler. Failures are logged, never raised — a
    collector that dies because the scheduler restarted is worse than one that retries."""

    def __init__(self, url: str, secret: str, *, world: str = "", timeout: float = 15.0,
                 opener=None) -> None:
        self.url = url.rstrip("/")
        if not self.url.endswith(RELAY_PATH):
            self.url += RELAY_PATH
        self.secret = secret
        self.world = world
        self.timeout = timeout
        self._opener = opener
        self.sent = 0
        self.failed = 0

    def send(self, kind: str, body: str) -> bool:
        payload = json.dumps({"kind": kind, "world": self.world, "body": body,
                              "sent_at": time.time()}).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.secret}"})
        open_fn = self._opener or urllib.request.urlopen
        try:
            with open_fn(req, timeout=self.timeout) as resp:
                resp.read()
            self.sent += 1
            return True
        except urllib.error.HTTPError as exc:
            self.failed += 1
            # 401 means the two sides disagree about the secret; saying so beats "failed".
            logger.warning("relay rejected the %s snapshot: HTTP %s%s", kind, exc.code,
                           " — check ALERT_RELAY_SECRET" if exc.code == 401 else "")
        except Exception as exc:                       # noqa: BLE001 - any transport problem
            self.failed += 1
            logger.warning("relay unreachable (%s snapshot): %s", kind, exc)
        return False


def make_relay_handler(reader, client: RelayClient):
    """Playwright ``response`` handler that forwards what the reader recognises.

    The reader is used purely as a filter here — the game's tab carries plenty of traffic we
    have no business shipping anywhere, so only a body it accepts as GBG data goes out.
    """
    from bap.alerting.watcher import _DATA_URLS

    def _handle(resp) -> None:
        try:
            url = getattr(resp, "url", "") or ""
            if not any(u in url for u in _DATA_URLS):
                return
            body = resp.text()
        except BaseException:          # includes CancelledError on a torn-down connection
            return
        before_snapshot = reader.snapshot
        before_layout = reader.map_layout
        if not reader.feed(body):
            return
        if reader.map_layout is not None and reader.map_layout is not before_layout:
            client.send(MAP, body)
        if reader.snapshot is not None and reader.snapshot is not before_snapshot:
            client.send(BATTLEGROUND, body)
    return _handle


# --------------------------------------------------------------------- scheduler


class _RelayHandler(BaseHTTPRequestHandler):
    server_version = "bap-alert-relay"
    secret: str
    on_body = None

    def log_message(self, fmt, *args):          # the alerter's own log is the useful one
        pass

    def _reply(self, code: int, detail: str) -> None:
        body = json.dumps({"ok": 200 <= code < 300, "detail": detail}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return secrets.compare_digest(header[len(prefix):], self.secret)

    def do_GET(self):                            # noqa: N802 - http.server's spelling
        # Unauthenticated on purpose: a host checker should not need the secret, and this
        # says nothing a stranger can use.
        if self.path.rstrip("/") in ("", "/health"):
            return self._reply(200, "alive")
        return self._reply(404, "not found")

    def do_POST(self):                           # noqa: N802
        if self.path.rstrip("/") != RELAY_PATH:
            return self._reply(404, "not found")
        if not self._authorised():
            return self._reply(401, "bad or missing bearer token")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._reply(400, "bad length")
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._reply(413, "body too large")
        try:
            payload = json.loads(self.rfile.read(length))
            kind = str(payload.get("kind") or "")
            body = payload.get("body")
        except Exception:
            return self._reply(400, "unreadable payload")
        if not isinstance(body, str) or kind not in (BATTLEGROUND, MAP):
            return self._reply(400, "unexpected payload")
        try:
            accepted = bool(type(self).on_body(kind, body))
        except Exception as exc:                 # noqa: BLE001 - a bad body must not kill us
            logger.warning("relay could not use a %s snapshot: %s", kind, exc)
            return self._reply(400, "could not parse that as GBG data")
        return self._reply(200 if accepted else 202, "accepted" if accepted else "ignored")


class SnapshotReceiver:
    """The scheduler's inbox: feeds whatever arrives into an engine, newest wins."""

    def __init__(self, engine, *, reader=None) -> None:
        from bap.forge.gbg_data.live import LiveGbgReader

        self.engine = engine
        self.reader = reader or LiveGbgReader()
        self.accepted = 0
        self._lock = threading.Lock()

    def feed(self, kind: str, body: str) -> bool:
        """True when the body actually produced something we could use."""
        with self._lock:                         # several collectors can post at once
            if not self.reader.feed(body):
                return False
            used = False
            if kind == MAP and self.reader.map_layout is not None:
                self.engine.on_layout(self.reader.map_layout)
                used = True
            if kind == BATTLEGROUND and self.reader.snapshot is not None:
                self.engine.on_snapshot(self.reader.snapshot)
                used = True
            if used:
                self.accepted += 1
                logger.info("relay: accepted a %s snapshot (%d so far)", kind, self.accepted)
            return used


def serve_relay(receiver: SnapshotReceiver, *, secret: str, port: int = 8770,
                host: str = "0.0.0.0"):
    """Start the ingest server on its own thread and return it. Refuses to run without a
    secret: an open relay on a public host would let anyone drive the guild's alerts."""
    if not secret:
        raise SystemExit(
            f"refusing to start without a shared secret — set {SECRET_ENV} on the scheduler "
            f"and on every collector")
    handler = type("_BoundRelayHandler", (_RelayHandler,),
                   {"secret": secret, "on_body": staticmethod(receiver.feed)})
    httpd = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("relay: listening on http://%s:%d%s", host, port, RELAY_PATH)
    return httpd


__all__ = ["BATTLEGROUND", "MAP", "MAX_BODY_BYTES", "RELAY_PATH", "SECRET_ENV",
           "RelayClient", "SnapshotReceiver", "make_relay_handler", "secret_from_env",
           "serve_relay"]
