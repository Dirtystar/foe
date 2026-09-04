"""Online revocation on top of the offline licence — free to run, offline-tolerant.

The offline HMAC key (``licensing``) proves the *tier* and *expiry* with no server. That can't be
**revoked** though — a leaked lifetime key would unlock forever. So this adds a light online check
against a key registry (a Cloudflare Worker + KV; see ``shop/keygen-worker.js``):

- On use, ask the verify endpoint whether the key is ``active`` or ``revoked`` (optionally checking
  the buyer's email), and **cache** the answer.
- **Offline-tolerant:** if the endpoint is unreachable, a previously-active key keeps working for a
  grace period (default 7 days) so a wifi blip never bricks a paying user; past that it drops to
  the free tier until it can verify again.
- **Opt-in:** if no verify URL is configured (``FOE_VERIFY_URL``), nothing changes — the app stays
  offline-only. Set the URL once the Worker is deployed to switch revocation on.

``entitlement()`` is the single call the app uses: it returns how many worlds to allow *now*,
combining the offline tier with the online status.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from bap.forge import licensing

VERIFY_URL = os.environ.get("FOE_VERIFY_URL", "")     # e.g. https://keys.example.workers.dev/verify
GRACE_SECONDS = 7 * 86400
TIMEOUT = 4
CACHE_FILE = os.path.join(os.path.expanduser("~"), ".forge_gbg_farmer_lic_cache.json")


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "forge-gbg-farmer"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - https worker URL
        return json.loads(r.read().decode("utf-8"))


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


def check_status(key: str, email: str | None = None, *, fetch=_http_get_json,
                 now: int | None = None) -> dict:
    """Return ``{online, status, reason}`` for a key. ``status`` is ``active``/``revoked``/
    ``unknown``. Reaches the verify endpoint (caching the result); on failure falls back to a
    cached ``active`` within the grace window, else ``unknown``."""
    now = int(time.time()) if now is None else now
    if not VERIFY_URL:
        return {"online": False, "status": "unconfigured", "reason": "no verify URL"}
    q = {"key": key}
    if email:
        q["email"] = email
    url = f"{VERIFY_URL}?{urllib.parse.urlencode(q)}"
    try:
        data = fetch(url)
        status = str(data.get("status", "unknown"))
        cache = _load_cache()
        cache[key] = {"status": status, "ts": now}
        _save_cache(cache)
        return {"online": True, "status": status, "reason": str(data.get("reason", ""))}
    except Exception:  # noqa: BLE001 - network/parse: fall back to cache
        c = _load_cache().get(key)
        if c and c.get("status") == "active" and now - int(c.get("ts", 0)) <= GRACE_SECONDS:
            left = GRACE_SECONDS - (now - int(c["ts"]))
            return {"online": False, "status": "active",
                    "reason": f"offline; cached, ~{left // 86400}d grace left"}
        return {"online": False, "status": "unknown", "reason": "cannot verify online"}


def entitlement(key: str | None, email: str | None = None, *, fetch=_http_get_json,
                now: int | None = None) -> tuple[int, str]:
    """How many worlds to allow right now, plus a human note. Combines the offline tier with the
    online revocation status. Falls back to the free tier for revoked / unverifiable paid keys."""
    offline = licensing.allowed_worlds(key, now)
    lic = licensing.verify_key(key) if key else None
    if not VERIFY_URL or not key or lic is None or not lic.is_valid(now):
        # Online checks off, or no valid paid key → behave exactly as offline.
        return offline, licensing.describe(lic, now)
    st = check_status(key, email, fetch=fetch, now=now)
    if st["status"] == "revoked":
        return licensing.FREE_WORLDS, "Licence revoked — dropped to the free tier (1 world)."
    if st["status"] == "email_mismatch":
        return licensing.FREE_WORLDS, "Email doesn't match this licence — enter the purchase email."
    if st["status"] in ("unknown",):
        return licensing.FREE_WORLDS, "Couldn't verify the licence online — connect to the internet."
    # active (fresh or within grace) → grant the offline tier.
    note = licensing.describe(lic, now)
    if not st["online"]:
        note += "  (offline — " + st["reason"] + ")"
    return offline, note


__all__ = ["check_status", "entitlement", "VERIFY_URL", "GRACE_SECONDS"]
