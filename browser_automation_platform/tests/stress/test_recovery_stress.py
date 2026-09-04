"""Recovery stress: crashes and repeated failures under multi-session load."""

import pytest

from bap.core.engine.health import SessionHealth
from loadkit import FlakyCapture, build_env

pytestmark = pytest.mark.stress


async def test_one_crashing_session_recovers_others_untouched():
    # s2 fails its first 2 captures then recovers; the rest never fail.
    capture = FlakyCapture(fail_plan={"s2": 2})
    env = build_env(8, interval_ms=10, capture=capture, recreate_after=2)
    await env.app.create_sessions()
    try:
        await env.run_rounds(5)
        healthy = tuple(env.app.manager.profile_ids)
    finally:
        await env.app.stop()

    assert env.monitor.health_of("s2") is SessionHealth.HEALTHY  # recovered
    assert env.browser.opens["s2"] == 2  # original + one recreate
    # the other seven were opened once and never recreated
    assert all(env.browser.opens[f"s{i}"] == 1 for i in range(8) if i != 2)
    assert set(healthy) == {f"s{i}" for i in range(8)}


async def test_recovery_attempts_are_bounded_and_session_disabled(capsys):
    capture = FlakyCapture(fail_plan={"s0": 10_000})  # permanently broken
    env = build_env(4, interval_ms=10, capture=capture, recreate_after=1, max_recovery_attempts=3)
    await env.app.create_sessions()
    try:
        await env.run_rounds(30)
        active = tuple(env.app.manager.profile_ids)
    finally:
        await env.app.stop()

    # bounded: at most max_recovery_attempts recreates, then disabled
    assert env.browser.opens["s0"] <= 1 + 3  # original + <=3 recreates
    assert env.monitor.health_of("s0") is SessionHealth.FAILED
    assert "s0" not in active  # disabled -> removed
    assert {"s1", "s2", "s3"} <= set(active)  # others survive

    with capsys.disabled():
        print(f"\n[stress] broken session recreated {env.browser.opens['s0'] - 1}x then disabled")


async def test_disabled_session_stops_consuming_resources():
    capture = FlakyCapture(fail_plan={"s0": 10_000})
    env = build_env(3, interval_ms=10, capture=capture, recreate_after=1, max_recovery_attempts=2)
    await env.app.create_sessions()
    try:
        await env.run_rounds(10)
        # once disabled, s0 must not tick again
        opens_after_disable = env.browser.opens["s0"]
        capture.calls.clear()
        await env.run_rounds(10)
    finally:
        await env.app.stop()

    # no further tab opens and no further capture calls for the disabled session
    assert env.browser.opens["s0"] == opens_after_disable
    assert capture.calls.get("s0", 0) == 0
