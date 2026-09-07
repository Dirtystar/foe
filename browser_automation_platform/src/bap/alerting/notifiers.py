"""Where the message goes. One tiny interface, three transports, no new dependencies.

``send(text) -> bool``. That's the whole port, so swapping WhatsApp gateways later is a
config change, not a rewrite.

- :class:`GreenApiNotifier` — Green API, the practical choice for **groups**: Meta's official
  WhatsApp Cloud API and Twilio can only message individual numbers with approved templates,
  they cannot post into a group at all. Green API drives a linked WhatsApp account, so a group
  is just another ``chatId`` (``…@g.us``).
- :class:`WebhookNotifier` — POST the text as JSON anywhere (a self-hosted bridge, Telegram
  relay, Discord, n8n…). The escape hatch if the gateway ever has to change.
- :class:`ConsoleNotifier` / :class:`NullNotifier` — dry runs and tests.

Everything is stdlib ``urllib``: no extra install, and it honours the usual proxy env vars.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger("bap.alerting.notify")

GREEN_API_BASE = "https://api.green-api.com"


class ConsoleNotifier:
    """Prints instead of sending — the default until credentials are configured."""

    name = "console"

    def __init__(self, stream=None) -> None:
        self._stream = stream

    def send(self, text: str) -> bool:
        print(text, file=self._stream, flush=True)
        return True


class NullNotifier:
    """Swallows everything (used by ``--dry-run`` inside tests)."""

    name = "null"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        return True


def _post_json(url: str, payload: dict, *, timeout: float = 15.0, opener=None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body) if body else {}
    except ValueError:
        return {"raw": body}


class GreenApiNotifier:
    """Send a WhatsApp message through a Green API instance.

    ``chat_id`` is the group id, e.g. ``120363012345678901@g.us`` (a private chat would be
    ``420777123456@c.us``). ``id_instance``/``api_token`` come from the Green API console.
    """

    name = "green_api"

    def __init__(self, id_instance: str, api_token: str, chat_id: str, *,
                 base_url: str = GREEN_API_BASE, retries: int = 2, opener=None,
                 sleep=time.sleep) -> None:
        self.id_instance = str(id_instance)
        self.api_token = str(api_token)
        self.chat_id = str(chat_id)
        self.base_url = base_url.rstrip("/")
        self.retries = max(0, int(retries))
        self._opener = opener
        self._sleep = sleep

    def _url(self, method: str) -> str:
        return f"{self.base_url}/waInstance{self.id_instance}/{method}/{self.api_token}"

    def send(self, text: str) -> bool:
        """True when the gateway accepted the message. Network hiccups are retried with a
        short backoff; a permanent failure is logged, never raised — a missed alert must not
        take the watcher down."""
        payload = {"chatId": self.chat_id, "message": text}
        for attempt in range(self.retries + 1):
            try:
                out = _post_json(self._url("sendMessage"), payload, opener=self._opener)
                if out.get("idMessage"):
                    return True
                logger.warning("green-api replied without idMessage: %s", out)
                return False
            except Exception as exc:                       # noqa: BLE001 - transport of any kind
                if attempt >= self.retries:
                    logger.warning("green-api send failed: %s", exc)
                    return False
                self._sleep(2 ** attempt)
        return False

    def state(self) -> dict:
        """``getStateInstance`` — ``{"stateInstance": "authorized"}`` when the phone is linked.
        Used by ``bap-alert check`` to explain a silent instance."""
        req = urllib.request.Request(self._url("getStateInstance"))
        open_fn = self._opener or urllib.request.urlopen
        with open_fn(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")


class WebhookNotifier:
    """POST ``{"text": …}`` to any URL — a bridge, a relay, or a test server."""

    name = "webhook"

    def __init__(self, url: str, *, field: str = "text", extra: dict | None = None,
                 opener=None) -> None:
        self.url = url
        self.field = field
        self.extra = dict(extra or {})
        self._opener = opener

    def send(self, text: str) -> bool:
        try:
            _post_json(self.url, {**self.extra, self.field: text}, opener=self._opener)
            return True
        except Exception as exc:                           # noqa: BLE001
            logger.warning("webhook send failed: %s", exc)
            return False


def build_notifier(cfg, *, opener=None):
    """Build the transport named by :class:`~bap.alerting.config.AlertConfig`.
    Falls back to the console when a gateway is selected but not configured, so a missing
    secret produces visible output instead of silence."""
    kind = (getattr(cfg, "notifier", "") or "console").lower()
    if kind in ("console", ""):
        return ConsoleNotifier()
    if kind == "null":
        return NullNotifier()
    if kind == "webhook":
        url = getattr(cfg, "webhook_url", "")
        if not url:
            logger.warning("notifier=webhook but no webhook_url — printing instead")
            return ConsoleNotifier()
        return WebhookNotifier(url, opener=opener)
    if kind in ("green_api", "greenapi", "green-api"):
        g = getattr(cfg, "green_api", None)
        if not (g and g.id_instance and g.api_token and g.chat_id):
            logger.warning("notifier=green_api but credentials/chat id are missing — "
                           "printing instead")
            return ConsoleNotifier()
        return GreenApiNotifier(g.id_instance, g.api_token, g.chat_id,
                                base_url=g.base_url, opener=opener)
    logger.warning("unknown notifier %r — printing instead", kind)
    return ConsoleNotifier()


__all__ = ["ConsoleNotifier", "NullNotifier", "GreenApiNotifier", "WebhookNotifier",
           "build_notifier", "GREEN_API_BASE"]
