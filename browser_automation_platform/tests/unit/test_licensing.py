"""Licence keys: round-trip, tamper-proofing, expiry, and the world cap."""

from __future__ import annotations

import time

from bap.forge import licensing as lic


def test_generate_verify_round_trip():
    key = lic.generate_key("quad", days=30, name="Radek")
    L = lic.verify_key(key)
    assert L is not None
    assert L.tier == "quad" and L.name == "Radek"
    assert L.worlds == 4 and L.is_valid()


def test_each_tier_world_count():
    assert lic.TIERS["solo"].worlds == 1
    assert lic.TIERS["duo"].worlds == 2
    assert lic.TIERS["quad"].worlds == 4
    assert lic.TIERS["octa"].worlds == 8
    assert lic.TIERS["unlimited"].worlds is None
    assert lic.verify_key(lic.generate_key("unlimited")).max_worlds() >= 8


def test_tampered_key_rejected():
    key = lic.generate_key("octa", days=30)
    # flip a character in the payload → signature must fail
    bad = key[:6] + ("A" if key[6] != "A" else "B") + key[7:]
    assert lic.verify_key(bad) is None


def test_wrong_secret_rejected(monkeypatch):
    key = lic.generate_key("duo", days=30)
    monkeypatch.setenv("FOE_LICENSE_SECRET", "a-different-secret")
    assert lic.verify_key(key) is None            # signed with the old secret → invalid now


def test_expiry():
    key = lic.generate_key("solo", days=1)
    L = lic.verify_key(key)
    assert L.is_valid(now=int(time.time()))
    assert not L.is_valid(now=int(time.time()) + 2 * 86400)
    assert L.max_worlds(now=int(time.time()) + 2 * 86400) == 0


def test_never_expires():
    L = lic.verify_key(lic.generate_key("solo", days=0))
    assert L.expires == 0 and L.is_valid(now=10**12)


def test_allowed_worlds_gate():
    assert lic.allowed_worlds(None) == lic.FREE_WORLDS           # no key → free tier
    assert lic.allowed_worlds("garbage") == lic.FREE_WORLDS      # invalid → free tier
    assert lic.allowed_worlds(lic.generate_key("octa", days=30)) == 8
    expired = lic.generate_key("quad", days=-0)                  # days<=0 = never; use real expiry
    # a properly expired key falls back to free
    past = lic.generate_key("quad", days=1)
    assert lic.allowed_worlds(past, now=int(time.time()) + 5 * 86400) == lic.FREE_WORLDS


def test_garbage_never_raises():
    for k in ["", "FOE", "FOE-x", "not-a-key", "FOE-AAAA-BBBB", None]:
        assert lic.verify_key(k) is None
