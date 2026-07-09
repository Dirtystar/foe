"""Scheduler: the timing driver for TabSessions.

Owns exactly two things: when each session ticks, and the lifecycle of the
loops doing so. It knows nothing about capture, vision, rules or actions —
its whole view of a session is the Tickable protocol (a profile_id and an
async tick() returning a report), which is also what makes it replaceable:
any future runtime (desktop app loop, distributed worker) that can call
tick() on a schedule can substitute for this class without TabSession
changing.

Time is injected: `sleep` (defaults to asyncio.sleep) and `rng` (defaults to
random.random) are constructor dependencies, so tests run deterministically
with fakes and never wait on a wall clock.
"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from bap.core.engine.tab_session import TickReport


class Tickable(Protocol):
    """What the Scheduler requires of a session — nothing more."""

    @property
    def profile_id(self) -> str: ...

    async def tick(self) -> TickReport: ...


SleepFn = Callable[[float], Awaitable[None]]
"""Async sleep taking seconds."""

RandomFn = Callable[[], float]
"""Returns a float in [0.0, 1.0); drives jitter."""

ReportCallback = Callable[[TickReport], object]
"""Called with every TickReport; may be sync or async."""


@dataclass(frozen=True)
class ScheduledJob:
    """Timing configuration for one session.

    Each cycle sleeps `interval_ms + rng() * jitter_ms` after the tick;
    jitter spreads sessions apart so N tabs do not capture in lockstep.
    """

    session: Tickable
    interval_ms: int
    jitter_ms: int = 0

    def __post_init__(self) -> None:
        if self.interval_ms <= 0:
            raise ValueError(f"interval_ms must be > 0, got {self.interval_ms}.")
        if self.jitter_ms < 0:
            raise ValueError(f"jitter_ms must be >= 0, got {self.jitter_ms}.")


@dataclass(frozen=True)
class JobRun:
    """Outcome of one driven tick: the report, or the contained exception if
    the session violated its never-raise contract."""

    profile_id: str
    report: TickReport | None = None
    error: Exception | None = None


class Scheduler:
    """Drives registered jobs, each in its own independent asyncio task.

    Per-task isolation means one session's misbehavior cannot stall the
    others. TabSession.tick() never raises by contract, but the loop
    boundary is protected anyway — a raising session is recorded and its
    loop continues. Business policy (cooldowns, retries) stays where it
    already lives; the scheduler never duplicates it.
    """

    def __init__(
        self,
        *,
        sleep: SleepFn | None = None,
        rng: RandomFn | None = None,
        on_report: ReportCallback | None = None,
    ) -> None:
        self._sleep: SleepFn = sleep if sleep is not None else asyncio.sleep
        self._rng: RandomFn = rng if rng is not None else random.random
        self._on_report = on_report
        self._jobs: dict[str, ScheduledJob] = {}
        self._runs: dict[str, int] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        # Per-job cancel events: setting one stops that job at its next await
        # boundary (the sleep) without interrupting an in-flight tick.
        self._cancels: dict[str, asyncio.Event] = {}
        self._stop_event: asyncio.Event | None = None
        self._started = False
        # Serializes structural mutations (register/unregister/replace) so
        # concurrent recoveries cannot duplicate or lose jobs. Held only around
        # the synchronous registry edits, never around the tick-reaping await.
        self._mutation_lock = asyncio.Lock()

    # --- registration ---------------------------------------------------------

    def add_job(self, job: ScheduledJob) -> None:
        if self.running:
            raise RuntimeError("Cannot add jobs while the scheduler is running.")
        profile_id = job.session.profile_id
        if profile_id in self._jobs:
            raise ValueError(f"A job for profile '{profile_id}' is already registered.")
        self._jobs[profile_id] = job
        self._runs[profile_id] = 0

    def remove_job(self, profile_id: str) -> None:
        if self.running:
            raise RuntimeError("Cannot remove jobs while the scheduler is running.")
        if profile_id not in self._jobs:
            raise ValueError(f"No job registered for profile '{profile_id}'.")
        del self._jobs[profile_id]
        del self._runs[profile_id]

    @property
    def profile_ids(self) -> tuple[str, ...]:
        return tuple(self._jobs)

    def runs_of(self, profile_id: str) -> int:
        return self._runs[profile_id]

    @property
    def running(self) -> bool:
        # A flag, not len(_tasks): unregistering the last job must not flip the
        # scheduler to "stopped" (a later register must still spawn a task).
        return self._started

    # --- runtime job mutation (safe while ticking) -----------------------------

    async def register_job(self, job: ScheduledJob) -> None:
        """Add a job. If the scheduler is running, its loop starts immediately;
        otherwise it starts on the next start(). Other jobs are unaffected."""
        profile_id = job.session.profile_id
        async with self._mutation_lock:
            if profile_id in self._jobs:
                raise ValueError(f"A job for profile '{profile_id}' is already registered.")
            self._install(job)

    async def unregister_job(self, profile_id: str) -> None:
        """Remove a job. If it is mid-tick, that tick finishes normally; the
        job then stops before its next tick. Tolerant of an already-absent
        job so it is safe under concurrent close/recovery. Does not block the
        event loop — other jobs keep ticking while this awaits the reap."""
        async with self._mutation_lock:
            task = self._detach(profile_id)
        if task is not None:
            await task  # waits out any in-flight tick, then the loop exits

    async def replace_job(self, profile_id: str, new_job: ScheduledJob) -> None:
        """Swap the session behind a profile without pausing the scheduler.

        The old job's in-flight tick (if any) finishes normally, its loop
        exits, and only then is the new job installed — so there is never more
        than one task per profile and no duplicate execution. Other sessions
        keep ticking throughout.
        """
        if new_job.session.profile_id != profile_id:
            raise ValueError(
                f"replace_job profile mismatch: '{profile_id}' vs "
                f"'{new_job.session.profile_id}'"
            )
        async with self._mutation_lock:
            old_task = self._detach(profile_id)
        if old_task is not None:
            await old_task  # reap the old loop (outside the lock; others tick on)
        async with self._mutation_lock:
            self._install(new_job)

    def _detach(self, profile_id: str) -> asyncio.Task | None:
        """Remove a job from the registry and signal its loop to stop. Returns
        the running task (if any) for the caller to await. Synchronous and
        atomic — no await, so it cannot interleave with another mutation."""
        self._jobs.pop(profile_id, None)
        self._runs.pop(profile_id, None)
        cancel = self._cancels.pop(profile_id, None)
        task = self._tasks.pop(profile_id, None)
        if cancel is not None:
            cancel.set()
        return task

    def _install(self, job: ScheduledJob) -> None:
        """Register a job and, if the scheduler is running, spawn its loop."""
        profile_id = job.session.profile_id
        self._jobs[profile_id] = job
        self._runs[profile_id] = 0
        if self._started:
            cancel = asyncio.Event()
            self._cancels[profile_id] = cancel
            self._tasks[profile_id] = asyncio.create_task(
                self._run_job(job, cancel), name=f"scheduler:{profile_id}"
            )

    # --- one-shot execution ----------------------------------------------------

    async def run_once(self) -> tuple[JobRun, ...]:
        """Tick every job exactly once, sequentially, in registration order.
        For tests and manual/step-through execution."""
        if self.running:
            raise RuntimeError("run_once() is not available while the scheduler is running.")
        return tuple([await self._tick_job(job) for job in self._jobs.values()])

    # --- lifecycle ---------------------------------------------------------------

    async def start(self) -> None:
        """Start one loop task per job. Idempotent."""
        if self._started:
            return
        self._stop_event = asyncio.Event()
        self._started = True
        for profile_id, job in self._jobs.items():
            cancel = asyncio.Event()
            self._cancels[profile_id] = cancel
            self._tasks[profile_id] = asyncio.create_task(
                self._run_job(job, cancel), name=f"scheduler:{profile_id}"
            )

    async def stop(self) -> None:
        """Graceful shutdown: in-flight ticks complete, sleeps are interrupted.
        Idempotent; the scheduler can be started again afterwards."""
        if not self._started:
            return
        assert self._stop_event is not None
        self._stop_event.set()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._cancels.clear()
        self._stop_event = None
        self._started = False

    # --- internals -----------------------------------------------------------------

    async def _run_job(self, job: ScheduledJob, cancel: asyncio.Event) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set() and not cancel.is_set():
            await self._tick_job(job)  # never interrupted; runs to completion
            if self._stop_event.is_set() or cancel.is_set():
                break  # removed/stopped during the tick: no further tick
            delay_ms = job.interval_ms + (
                self._rng() * job.jitter_ms if job.jitter_ms else 0.0
            )
            await self._interruptible_sleep(delay_ms / 1000.0, cancel)

    async def _tick_job(self, job: ScheduledJob) -> JobRun:
        profile_id = job.session.profile_id
        try:
            report = await job.session.tick()
            run = JobRun(profile_id=profile_id, report=report)
        except Exception as exc:
            run = JobRun(profile_id=profile_id, error=exc)
        # The job may have been unregistered during this tick; only record the
        # run if it is still registered (avoids resurrecting a removed entry).
        if profile_id in self._runs:
            self._runs[profile_id] += 1
        if run.report is not None:
            await self._dispatch(run.report)
        return run

    async def _dispatch(self, report: TickReport) -> None:
        if self._on_report is None:
            return
        try:
            result = self._on_report(report)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # A broken observer must never stall the timing loop. Observers
            # that care about their own errors handle them themselves.
            pass

    async def _interruptible_sleep(self, seconds: float, cancel: asyncio.Event) -> None:
        """Sleep, but wake immediately when stop() is called or this job is
        unregistered/replaced (its cancel event fires)."""
        assert self._stop_event is not None
        sleep_task = asyncio.ensure_future(self._sleep(seconds))
        stop_task = asyncio.ensure_future(self._stop_event.wait())
        cancel_task = asyncio.ensure_future(cancel.wait())
        try:
            await asyncio.wait(
                {sleep_task, stop_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (sleep_task, stop_task, cancel_task):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                elif task.exception() is not None:
                    pass  # a broken injected sleep must not kill the loop


__all__ = ["JobRun", "ScheduledJob", "Scheduler", "SleepFn", "RandomFn", "Tickable"]
