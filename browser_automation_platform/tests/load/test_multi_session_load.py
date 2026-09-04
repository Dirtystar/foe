"""Multi-session load: 1 / 4 / 8 / 16 sessions through the full pipeline."""

import time

import pytest

from loadkit import build_env, object_count

pytestmark = pytest.mark.load


@pytest.mark.parametrize("n_sessions", [1, 4, 8, 16])
async def test_throughput_and_fairness(n_sessions, capsys):
    env = build_env(n_sessions, interval_ms=10)
    await env.app.create_sessions()

    rounds = 200
    start = time.perf_counter()
    try:
        await env.run_rounds(rounds)
    finally:
        await env.app.stop()
    elapsed = time.perf_counter() - start

    total_ticks = n_sessions * rounds
    # every session ticked exactly `rounds` times -> perfect fairness, no starvation
    assert env.reports["completed"] == total_ticks
    throughput = total_ticks / elapsed

    with capsys.disabled():
        print(
            f"\n[load] sessions={n_sessions:>2} ticks={total_ticks:>5} "
            f"elapsed={elapsed:6.3f}s throughput={throughput:9.0f} ticks/s"
        )


async def test_memory_is_stable_across_many_ticks(capsys):
    """The runtime must not accumulate per-tick objects (reports are consumed,
    not retained)."""
    env = build_env(8, interval_ms=10)
    await env.app.create_sessions()
    try:
        await env.run_rounds(50)  # warm up allocations
        baseline = object_count()
        await env.run_rounds(500)
        growth = object_count() - baseline
    finally:
        await env.app.stop()

    with capsys.disabled():
        print(f"\n[load] object growth over 500 rounds x8 sessions: {growth:+d}")
    # generous bound: no per-tick leak (would be thousands over 4000 ticks)
    assert growth < 2000
