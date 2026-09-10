"""Threading bridge between the Qt UI and the asyncio runtime.

The runtime is asyncio; Qt owns its own event loop. This service runs the
application on a dedicated thread with its own asyncio loop and exposes
thread-safe, non-blocking control methods that schedule coroutines onto it.
Results and errors are surfaced through plain callbacks (set by the GUI to
Qt-signal emitters) — this module imports no Qt, so it stays testable
headless and keeps the UI/runtime separation strict.

It is a controller, not a decision maker: it starts, stops, and single-steps
the runtime the composition root already built. It never constructs browsers,
sessions, rules, or handlers.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Protocol


class _Runnable(Protocol):
    """The slice of Application this service drives (structural, for testing)."""

    session_specs: tuple
    scheduler: object

    async def create_sessions(self) -> None: ...
    async def start(self) -> None: ...
    async def stop_automation(self): ...
    async def stop(self): ...
    async def open_browser(self) -> None: ...
    async def close_browser(self) -> None: ...
    async def add_world_session(self, spec) -> None: ...
    async def remove_world_session(self, profile_id: str) -> None: ...
    async def edit_world_session(self, spec) -> None: ...


class RuntimeService:
    def __init__(self, app: _Runnable) -> None:
        self._app = app
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._state = "stopped"
        # Wired by the GUI to thread-safe Qt signal emitters.
        self.on_state_change: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None

    # --- loop lifecycle -----------------------------------------------------

    def start_loop(self) -> None:
        if self._thread is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="bap-runtime", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop_loop(self) -> None:
        """Stop the runtime loop thread. Best-effort; safe to call once."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def profile_ids(self) -> tuple[str, ...]:
        return tuple(spec.profile_id for spec in self._app.session_specs)

    # --- controls (thread-safe, non-blocking) -------------------------------

    def start_runtime(self) -> Future:
        self._set_state("running")
        return self._submit(self._app.start())

    def stop_runtime(self) -> Future:
        """Stop automation only. The browser window and its tabs stay open —
        Stop is not Close Browser and never was meant to be."""
        future = self._submit(self._app.stop_automation())
        future.add_done_callback(lambda _f: self._set_state("stopped"))
        return future

    def shutdown_runtime(self) -> Future:
        """Full graceful teardown for application exit: stop automation, then
        close the browser and release the vision executor."""
        future = self._submit(self._app.stop())
        future.add_done_callback(lambda _f: self._set_state("stopped"))
        return future

    def tick_once(self) -> Future:
        """Run exactly one tick per session, self-contained: ensure the browser
        is open, create sessions, run one round, detach. Independent of
        start/stop so it cannot collide with an already-running runtime's
        session set, and it never closes the browser."""
        return self._submit(self._single_tick())

    # --- attended browser controls (thread-safe, non-blocking) --------------

    def open_browser(self) -> Future:
        """Open the visible attended browser (idempotent). The user then drives it."""
        return self._submit(self._app.open_browser())

    def close_browser(self) -> Future:
        """Close the attended browser window explicitly (idempotent)."""
        return self._submit(self._app.close_browser())

    def scan_tabs(self) -> Future:
        """Return the tabs currently open in the attended browser
        (Future resolves to list[BrowserTab])."""
        return self._submit(self._app.browser.scan_tabs())

    # --- Forge hot World CRUD (thread-safe; runs on the runtime loop) --------

    def add_world_session(self, spec) -> Future:
        """Add a world to the live session plan (no restart)."""
        return self._submit(self._app.add_world_session(spec))

    def remove_world_session(self, profile_id: str) -> Future:
        """Remove a world from the plan and stop its session; tab is untouched."""
        return self._submit(self._app.remove_world_session(profile_id))

    def edit_world_session(self, spec) -> Future:
        """Apply edited world settings live (rebuilds a running session in place)."""
        return self._submit(self._app.edit_world_session(spec))

    def capture_world(self, tab_id: str, capture_port) -> Future:
        """Read-only capture of a world's tab (Future resolves to PNG bytes, or
        None). Uses the same CDP capture as the runtime — no clicking, no focus."""

        async def _cap():
            tab = await self._app.browser.adopt_tab(tab_id)
            image = await capture_port.capture(tab)
            return image.data

        return self._submit(_cap())

    async def _single_tick(self) -> None:
        await self._app.open_browser()
        await self._app.create_sessions()
        try:
            await self._app.scheduler.run_once()
        finally:
            await self._app.stop_automation()

    # --- internals ----------------------------------------------------------

    def _submit(self, coro) -> Future:
        if self._loop is None:
            raise RuntimeError("start_loop() must be called before submitting work")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(self._report_failure)
        return future

    def _report_failure(self, future: Future) -> None:
        try:
            future.result()
        except Exception as exc:  # surfaced to the UI, never raised into a thread
            if self.on_error is not None:
                self.on_error(f"{type(exc).__name__}: {exc}")

    def _set_state(self, state: str) -> None:
        self._state = state
        if self.on_state_change is not None:
            self.on_state_change(state)


__all__ = ["RuntimeService"]
