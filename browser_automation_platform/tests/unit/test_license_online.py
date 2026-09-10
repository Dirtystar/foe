"""Online revocation layer: active/revoked/email, offline grace, and opt-in behaviour."""

from __future__ import annotations

import time

import pytest

from bap.forge import license_online as lo
from bap.forge import licensing


@pytest.fixture
def key():
    return licensing.generate_key("lifetime", days=0, name="buyer@x.com")


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(lo, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(lo, "VERIFY_URL", "https://verify.example/verify")


def _fetch(status):
    return lambda url: {"status": status}


def test_unconfigured_is_offline_only(key, monkeypatch):
    monkeypatch.setattr(lo, "VERIFY_URL", "")            # no URL → behave exactly offline
    worlds, _ = lo.entitlement(key, fetch=_fetch("revoked"))
    assert worlds >= 8                                    # revoked ignored when checks are off


def test_active_grants_tier(key):
    worlds, note = lo.entitlement(key, "buyer@x.com", fetch=_fetch("active"))
    assert worlds >= 8 and "revoked" not in note


def test_revoked_drops_to_free(key):
    worlds, note = lo.entitlement(key, "buyer@x.com", fetch=_fetch("revoked"))
    assert worlds == licensing.FREE_WORLDS and "revoked" in note.lower()


def test_email_mismatch_drops_to_free(key):
    worlds, note = lo.entitlement(key, "wrong@x.com", fetch=_fetch("email_mismatch"))
    assert worlds == licensing.FREE_WORLDS and "email" in note.lower()


def _boom(url):
    raise OSError("offline")


def test_offline_within_grace_keeps_working(key):
    lo.check_status(key, fetch=_fetch("active"))          # seed cache = active now
    worlds, note = lo.entitlement(key, fetch=_boom)       # now offline
    assert worlds >= 8 and "offline" in note.lower()


def test_offline_past_grace_drops_to_free(key):
    lo.check_status(key, fetch=_fetch("active"), now=int(time.time()) - 30 * 86400)
    worlds, _ = lo.entitlement(key, fetch=_boom)          # cache is 30d old > 7d grace
    assert worlds == licensing.FREE_WORLDS


def test_offline_no_cache_drops_to_free(key):
    worlds, note = lo.entitlement(key, fetch=_boom)       # never verified + offline
    assert worlds == licensing.FREE_WORLDS and "verify" in note.lower()


def test_free_key_stays_free_without_network(monkeypatch):
    worlds, _ = lo.entitlement(None, fetch=_fetch("active"))
    assert worlds == licensing.FREE_WORLDS
