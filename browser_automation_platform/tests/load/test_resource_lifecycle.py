"""Resource lifecycle: repeated create/close leaks no tasks, threads, or tabs."""

import asyncio

import pytest

from loadkit import build_env, live_task_count, thread_count

pytestmark = pytest.mark.load


async def test_repeated_create_close_releases_tabs():
    env = build_env(4, interval_ms=10)

    for _ in range(20):
        await env.app.create_sessions()
        await env.app.stop()

    # every opened tab was closed; opens and closes balance per profile
    assert dict(env.browser.opens) == dict(env.browser.closes)
    assert all(env.browser.opens[f"s{i}"] == 20 for i in range(4))
    assert env.app.manager.session_count == 0


async def test_no_leaked_asyncio_tasks_after_shutdown():
    env = build_env(8, interval_ms=10)
    baseline = live_task_count()

    await env.app.create_sessions()
    await env.app.scheduler.start()
    # let the loops spin
    for _ in range(50):
        await asyncio.sleep(0)
    await env.app.stop()
    for _ in range(50):
        await asyncio.sleep(0)  # allow cancelled tasks to settle

    assert live_task_count() <= baseline  # scheduler job tasks all terminated


async def test_no_leaked_threads_across_store_lifecycles(capsys):
    from bap.adapters.persistence.sqlite_store import SqliteStateStore

    baseline = thread_count()
    import tempfile
    import os

    for _ in range(10):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        store = SqliteStateStore(path)
        store.close()
        os.unlink(path)

    settled = thread_count()
    with capsys.disabled():
        print(f"\n[load] threads baseline={baseline} after 10 store lifecycles={settled}")
    assert settled <= baseline  # every writer thread joined on close()


async def test_scheduler_start_stop_cycles_are_clean():
    env = build_env(4, interval_ms=10)
    await env.app.create_sessions()
    try:
        for _ in range(10):
            await env.app.scheduler.start()
            for _ in range(5):
                await asyncio.sleep(0)
            await env.app.scheduler.stop()
            assert not env.app.scheduler.running
    finally:
        await env.app.stop()
