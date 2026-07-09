"""Signal handling and idempotent shutdown."""

from __future__ import annotations

import asyncio
import signal

import pytest

from bap.ops.lifecycle import IdempotentShutdown, install_signal_handlers


async def test_idempotent_shutdown_runs_once_under_concurrency() -> None:
    calls = 0

    async def routine() -> None:
        nonlocal calls
        await asyncio.sleep(0)
        calls += 1

    shutdown = IdempotentShutdown(routine)
    await asyncio.gather(*(shutdown() for _ in range(5)))
    assert calls == 1
    assert shutdown.done is True

    await shutdown()  # a later trigger is still a no-op
    assert calls == 1


def test_install_signal_handlers_tolerates_unsupported_loop() -> None:
    class _FailingLoop:
        def add_signal_handler(self, *_a, **_k):
            raise NotImplementedError

    # Must not raise: unsupported platforms/threads degrade to a no-op.
    install_signal_handlers(_FailingLoop(), lambda name: None)


async def test_sigterm_triggers_graceful_stop() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    previous = signal.getsignal(signal.SIGTERM)
    install_signal_handlers(loop, lambda name: stop.set())
    try:
        signal.raise_signal(signal.SIGTERM)  # our handler overrides the default
        await asyncio.wait_for(stop.wait(), timeout=1.0)
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        loop.remove_signal_handler(signal.SIGINT)
        signal.signal(signal.SIGTERM, previous)
    assert stop.is_set()
