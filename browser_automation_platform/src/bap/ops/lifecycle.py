"""Signal handling and idempotent shutdown helpers for the headless service."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable


def install_signal_handlers(loop: asyncio.AbstractEventLoop, on_stop: Callable[[str], None]) -> None:
    """Route SIGTERM/SIGINT to `on_stop(signal_name)` on the given loop.

    Uses loop.add_signal_handler where supported; on platforms/threads where
    it is not (e.g. non-main thread), it is a no-op — the caller's
    KeyboardInterrupt path still applies.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, ValueError, RuntimeError):
            loop.add_signal_handler(sig, on_stop, sig.name)


class IdempotentShutdown:
    """Runs an async shutdown routine at most once, even under concurrent or
    repeated triggers (signal + finally block + GUI close)."""

    def __init__(self, routine: Callable[[], Awaitable[None]]) -> None:
        self._routine = routine
        self._done = False
        self._lock = asyncio.Lock()

    @property
    def done(self) -> bool:
        return self._done

    async def __call__(self) -> None:
        async with self._lock:
            if self._done:
                return
            self._done = True
            await self._routine()


__all__ = ["IdempotentShutdown", "install_signal_handlers"]
