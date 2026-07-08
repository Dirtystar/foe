"""SessionManager: composition layer between browser lifecycle and Scheduler.

Owns the runtime set of sessions: it starts the browser (through BrowserPort,
never a concrete adapter), opens one tab per profile, asks an injected
factory to build the session for that tab, and registers the session with
the Scheduler. It contains zero automation knowledge — how a session is
assembled (bindings, rules, handlers) is the factory's business, what a
session does each tick is TabSession's, and when it ticks is the
Scheduler's. The manager only sequences lifecycles and enforces capacity.

Failure discipline: create_session either fully succeeds or leaves no trace
— every partially acquired resource (an opened tab, a registered job) is
released on the way out of a failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bap.core.domain.models import TabHandle, TabProfile
from bap.core.engine.scheduler import ScheduledJob, Scheduler, Tickable
from bap.core.ports.browser_port import BrowserPort


class SessionManagerError(Exception):
    """Base class for session-management errors."""


class DuplicateSessionError(SessionManagerError):
    pass


class SessionLimitError(SessionManagerError):
    pass


class SessionNotFoundError(SessionManagerError):
    pass


@dataclass(frozen=True)
class SessionSpec:
    """Everything the manager needs to run one session: what tab to open and
    how often to tick it. What the session does comes from the factory."""

    tab_profile: TabProfile
    interval_ms: int
    jitter_ms: int = 0

    @property
    def profile_id(self) -> str:
        return self.tab_profile.id

    def __post_init__(self) -> None:
        if self.interval_ms <= 0:
            raise ValueError(f"interval_ms must be > 0, got {self.interval_ms}.")
        if self.jitter_ms < 0:
            raise ValueError(f"jitter_ms must be >= 0, got {self.jitter_ms}.")


SessionFactory = Callable[[SessionSpec, TabHandle], Tickable]
"""Builds a ready-to-tick session for an opened tab. Injected by the
composition root, which is the only place that knows how to assemble the
automation stack (capture bindings, rule engine, action executor)."""


@dataclass
class _SessionEntry:
    spec: SessionSpec
    tab: TabHandle
    session: Tickable


class SessionManager:
    def __init__(
        self,
        *,
        browser: BrowserPort,
        scheduler: Scheduler,
        session_factory: SessionFactory,
        max_sessions: int = 8,
    ) -> None:
        if max_sessions <= 0:
            raise ValueError(f"max_sessions must be > 0, got {max_sessions}.")
        self._browser = browser
        self._scheduler = scheduler
        self._session_factory = session_factory
        self._max_sessions = max_sessions
        self._entries: dict[str, _SessionEntry] = {}
        self._browser_started = False

    @property
    def profile_ids(self) -> tuple[str, ...]:
        """Active sessions, in creation order."""
        return tuple(self._entries)

    @property
    def session_count(self) -> int:
        return len(self._entries)

    async def create_session(self, spec: SessionSpec) -> str:
        """Open a tab for the spec, build its session, register it for
        scheduling. All-or-nothing: on any failure, acquired resources are
        released and no state is recorded."""
        profile_id = spec.profile_id
        if profile_id in self._entries:
            raise DuplicateSessionError(f"Session '{profile_id}' already exists.")
        if len(self._entries) >= self._max_sessions:
            raise SessionLimitError(
                f"Cannot create session '{profile_id}': max_sessions={self._max_sessions} reached."
            )

        await self._ensure_browser_started()
        tab = await self._browser.open_tab(spec.tab_profile)
        try:
            session = self._session_factory(spec, tab)
            await self._with_scheduler_paused(
                lambda: self._scheduler.add_job(
                    ScheduledJob(
                        session=session, interval_ms=spec.interval_ms, jitter_ms=spec.jitter_ms
                    )
                )
            )
        except Exception:
            await self._browser.close_tab(tab)
            raise

        self._entries[profile_id] = _SessionEntry(spec=spec, tab=tab, session=session)
        return profile_id

    async def close_session(self, profile_id: str) -> None:
        """Deregister from the scheduler, close the tab, forget the session.
        The registry is cleaned up even if closing the tab fails."""
        entry = self._entries.pop(profile_id, None)
        if entry is None:
            raise SessionNotFoundError(f"Session '{profile_id}' does not exist.")
        await self._with_scheduler_paused(lambda: self._scheduler.remove_job(profile_id))
        await self._browser.close_tab(entry.tab)

    async def recover_session(self, profile_id: str) -> str:
        """Recreate a session's tab and rebuild it from its stored spec.

        This is the lifecycle side of recovery (the policy decision lives in
        HealthMonitor, above this class). The flow is exactly the create flow
        replayed on a fresh tab: deregister the old job, close the old tab
        (best-effort — it may already be dead), open a new tab from the
        stored spec, rebuild the session via the factory, re-register it.

        Cooldowns: the factory builds a FRESH RuleEngine, so rule cooldown
        state is intentionally reset on recovery. This is deliberate, not a
        silent in-place reset — after a tab restart the page is in a clean
        state, so cooldowns accumulated against the old (broken) tab no longer
        reflect reality and must not suppress the first action on the new one.

        On failure the session is dropped (so it stops ticking rather than
        looping) and the error is raised for the caller to report.
        """
        entry = self._entries.get(profile_id)
        if entry is None:
            raise SessionNotFoundError(f"Session '{profile_id}' does not exist.")

        was_running = self._scheduler.running
        if was_running:
            await self._scheduler.stop()
        try:
            try:
                self._scheduler.remove_job(profile_id)
            except ValueError:
                pass  # already deregistered
            try:
                await self._browser.close_tab(entry.tab)
            except Exception:
                pass  # old tab may already be gone; recovery continues

            await self._ensure_browser_started()
            new_tab = None
            try:
                new_tab = await self._browser.open_tab(entry.spec.tab_profile)
                new_session = self._session_factory(entry.spec, new_tab)
                self._scheduler.add_job(
                    ScheduledJob(
                        session=new_session,
                        interval_ms=entry.spec.interval_ms,
                        jitter_ms=entry.spec.jitter_ms,
                    )
                )
            except Exception:
                if new_tab is not None:
                    try:
                        await self._browser.close_tab(new_tab)
                    except Exception:
                        pass
                self._entries.pop(profile_id, None)  # drop it; do not keep ticking a broken session
                raise

            self._entries[profile_id] = _SessionEntry(
                spec=entry.spec, tab=new_tab, session=new_session
            )
        finally:
            if was_running:
                await self._scheduler.start()
        return profile_id

    async def shutdown(self) -> tuple[tuple[str, Exception], ...]:
        """Stop scheduling, close every tab, stop the browser. Best-effort:
        one session failing to close never blocks the others; failures are
        returned as data. The manager is fully restartable afterwards."""
        if self._scheduler.running:
            await self._scheduler.stop()

        errors: list[tuple[str, Exception]] = []
        for profile_id, entry in list(self._entries.items()):
            try:
                self._scheduler.remove_job(profile_id)
            except Exception as exc:  # keep going; the tab still gets closed
                errors.append((profile_id, exc))
            try:
                await self._browser.close_tab(entry.tab)
            except Exception as exc:
                errors.append((profile_id, exc))
        self._entries.clear()

        if self._browser_started:
            try:
                await self._browser.stop()
            finally:
                self._browser_started = False
        return tuple(errors)

    # --- internals ---------------------------------------------------------------

    async def _ensure_browser_started(self) -> None:
        if not self._browser_started:
            await self._browser.start()
            self._browser_started = True

    async def _with_scheduler_paused(self, mutate: Callable[[], None]) -> None:
        """Apply a job-registry mutation, pausing the scheduler around it if
        it is currently running (its registry is fixed while running)."""
        was_running = self._scheduler.running
        if was_running:
            await self._scheduler.stop()
        try:
            mutate()
        finally:
            if was_running:
                await self._scheduler.start()


__all__ = [
    "DuplicateSessionError",
    "SessionFactory",
    "SessionLimitError",
    "SessionManager",
    "SessionManagerError",
    "SessionNotFoundError",
    "SessionSpec",
]
