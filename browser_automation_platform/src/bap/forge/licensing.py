"""Licensing for the Forge GBG Farmer — tiers, prices, and offline key checks.

A licence key is a short, self-contained token the customer pastes into the app. It encodes a
**tier** (how many worlds they may farm) and an **expiry date**, signed with an HMAC secret so it
can't be edited or forged. The app verifies it **offline** (no server call) and simply caps how
many worlds the farmer will drive.

    Tier        Worlds   Price (USD / month)
    ---------------------------------------
    solo          1        4
    duo           2        7
    quad          4        12
    octa          8        20
    unlimited     ∞        30

Owner side (you), to mint a key::

    python -m bap.forge.licensing gen --tier quad --days 30
    python -m bap.forge.licensing gen --tier unlimited --days 365 --name "Customer"

Customer side (the app) verifies with :func:`verify_key`. The signing secret lives in
``FOE_LICENSE_SECRET`` (env) if set, else the built-in default below — change it before you sell,
and keep it private (only key *generation* needs it; verification uses the same value baked in).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

# Change this before distributing. Anyone with this secret can mint keys.
_DEFAULT_SECRET = "forge-gbg-farmer-CHANGE-ME"


def _secret() -> bytes:
    return (os.environ.get("FOE_LICENSE_SECRET") or _DEFAULT_SECRET).encode("utf-8")


@dataclass(frozen=True)
class Tier:
    name: str
    worlds: int | None          # None = unlimited
    price_usd: int
    one_time: bool = False       # True = pay once, no expiry (lifetime); else monthly

    @property
    def price_label(self) -> str:
        return f"${self.price_usd} one-time" if self.one_time else f"${self.price_usd}/mo"


# The product's tiers, cheapest first. Prices are placeholders — tune freely. ``lifetime`` is a
# one-time purchase for unlimited worlds that never expires (key minted with days<=0).
TIERS: dict[str, Tier] = {
    "solo": Tier("solo", 1, 4),
    "duo": Tier("duo", 2, 7),
    "quad": Tier("quad", 4, 12),
    "octa": Tier("octa", 8, 20),
    "unlimited": Tier("unlimited", None, 30),
    "lifetime": Tier("lifetime", None, 199, one_time=True),
}


@dataclass(frozen=True)
class License:
    """A verified licence: which tier, until when, for whom."""

    tier: str
    expires: int                # unix seconds; 0 = never expires
    name: str = ""

    @property
    def worlds(self) -> int | None:
        t = TIERS.get(self.tier)
        return t.worlds if t else 0

    @property
    def unlimited(self) -> bool:
        return self.worlds is None

    def is_valid(self, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else now
        return self.tier in TIERS and (self.expires == 0 or now < self.expires)

    def max_worlds(self, now: int | None = None) -> int:
        """How many worlds may run: the tier's cap, or 0 if the licence is invalid/expired.
        Unlimited returns a large number so callers can ``min(len(worlds), max_worlds())``."""
        if not self.is_valid(now):
            return 0
        return 9999 if self.unlimited else int(self.worlds or 0)


def _b32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _unb32(s: str) -> bytes:
    pad = "=" * (-len(s) % 8)
    return base64.b32decode(s + pad)


def _sign(payload: str) -> str:
    mac = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b32(mac)[:16]


def generate_key(tier: str, *, days: int = 30, name: str = "") -> str:
    """Mint a licence key for ``tier`` valid ``days`` from now (``days<=0`` → never expires).
    Owner-only: needs the signing secret. Format: ``FOE-<PAYLOAD>-<SIG>`` (base32)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; choose from {', '.join(TIERS)}")
    expires = 0 if days <= 0 else int(time.time()) + days * 86400
    body = f"{tier}|{expires}|{name}"
    payload = _b32(body.encode("utf-8"))
    return f"FOE-{payload}-{_sign(payload)}"


def verify_key(key: str) -> License | None:
    """Return the :class:`License` a key encodes if the signature checks out, else ``None``.
    Does **not** check expiry — call :meth:`License.is_valid` for that. Never raises."""
    try:
        parts = (key or "").strip().split("-")
        if len(parts) != 3 or parts[0] != "FOE":
            return None
        _, payload, sig = parts
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        tier, expires, name = _unb32(payload).decode("utf-8").split("|", 2)
        return License(tier=tier, expires=int(expires), name=name)
    except Exception:
        return None


def describe(lic: License | None, now: int | None = None) -> str:
    """One-line human status for the UI/CLI."""
    if lic is None:
        return "No valid licence — running in free mode (1 world)."
    if not lic.is_valid(now):
        return f"Licence expired ({lic.tier}). Renew to keep {lic.tier} access."
    worlds = "unlimited" if lic.unlimited else f"{lic.worlds}"
    exp = "never" if lic.expires == 0 else time.strftime("%Y-%m-%d", time.gmtime(lic.expires))
    who = f" for {lic.name}" if lic.name else ""
    return f"Licence: {lic.tier} ({worlds} worlds){who}, valid until {exp}."


# Free tier when there is no key at all — one world, so the app is usable/try-able.
FREE_WORLDS = 1


def allowed_worlds(key: str | None, now: int | None = None) -> int:
    """The number of worlds the given key permits right now (0 never happens — invalid/expired
    keys fall back to the free tier). This is the single gate the app enforces."""
    lic = verify_key(key) if key else None
    if lic is not None and lic.is_valid(now):
        return lic.max_worlds(now)
    return FREE_WORLDS


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    ap = argparse.ArgumentParser(prog="bap-forge-license",
                                 description="Generate / check Forge GBG Farmer licence keys.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="mint a key (owner only)")
    g.add_argument("--tier", required=True, choices=list(TIERS))
    g.add_argument("--days", type=int, default=30, help="valid for N days (<=0 = never expires)")
    g.add_argument("--name", default="", help="customer name stamped into the key")
    c = sub.add_parser("check", help="verify a key")
    c.add_argument("key")
    t = sub.add_parser("tiers", help="list tiers and prices")
    args = ap.parse_args(argv)

    if args.cmd == "gen":
        key = generate_key(args.tier, days=args.days, name=args.name)
        print(key)
        print(describe(verify_key(key)))
        return 0
    if args.cmd == "check":
        lic = verify_key(args.key)
        print(describe(lic))
        return 0 if (lic and lic.is_valid()) else 1
    if args.cmd == "tiers":
        print(f"{'tier':<12}{'worlds':<10}{'price'}")
        for t in TIERS.values():
            print(f"{t.name:<12}{('∞' if t.worlds is None else t.worlds)!s:<10}{t.price_label}")
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
