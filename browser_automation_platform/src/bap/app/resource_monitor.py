"""ResourceMonitor: observes browser resource usage via the report stream.

A transparent middle layer in the report path (like Supervisor and
PersistenceSink): it forwards every report downstream and uses the report
cadence to trigger periodic resource collection off the callback (via
task_runner), so collection never blocks the runtime. Collected snapshots are
persisted (separate browser_metrics table) and pushed to observers; configured
limits are evaluated and the result handed to a pressure callback (empty
breaches included, so the policy can reset). It is pure collection + detection
— the escalation policy and any action live in the Supervisor.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from bap.core.engine.tab_session import TickReport
from bap.core.ports.browser_metrics_port import BrowserMetricsPort, BrowserResourceSnapshot
from bap.core.ports.state_store_port import BrowserResourceRecord

ReportSink = Callable[[TickReport], Any]
ResourceSink = Callable[[BrowserResourceSnapshot], Any]
PressureSink = Callable[[BrowserResourceSnapshot, tuple[str, ...]], Any]
TaskRunner = Callable[[Coroutine], Any]


def snapshot_to_record(s: BrowserResourceSnapshot) -> BrowserResourceRecord:
    return BrowserResourceRecord(
        timestamp=s.collected_at,
        browser_id=s.browser_id,
        memory_mb=s.memory_mb,
        cpu_percent=s.cpu_percent,
        pages=s.pages,
        contexts=s.contexts,
    )


class ResourceMonitor:
    def __init__(
        self,
        metrics: BrowserMetricsPort,
        *,
        collect_every: int = 50,
        max_memory_mb: int | None = None,
        max_pages: int | None = None,
        store=None,
        report_sink: ReportSink | None = None,
        on_resource: ResourceSink | None = None,
        on_pressure: PressureSink | None = None,
        task_runner: TaskRunner | None = None,
    ) -> None:
        self._metrics = metrics
        self._collect_every = max(1, collect_every)
        self._max_memory_mb = max_memory_mb
        self._max_pages = max_pages
        self._store = store
        self._report_sink = report_sink
        self._on_resource = on_resource
        self._on_pressure = on_pressure
        self._task_runner = task_runner or asyncio.ensure_future
        self._count = 0

    def on_report(self, report: TickReport) -> None:
        if self._report_sink is not None:
            self._report_sink(report)  # forward downstream first
        self._count += 1
        if self._count % self._collect_every == 0:
            self._task_runner(self._collect())  # off the callback — never blocks

    async def collect_now(self) -> BrowserResourceSnapshot | None:
        """Collect immediately (for tests / manual refresh). Returns the
        snapshot, or None if collection failed."""
        return await self._collect()

    async def _collect(self) -> BrowserResourceSnapshot | None:
        try:
            snapshot = await self._metrics.collect()
        except Exception:
            return None  # observational: collection failure never affects runtime
        if self._store is not None:
            try:
                self._store.record_resource(snapshot_to_record(snapshot))
            except Exception:
                pass
        if self._on_resource is not None:
            self._on_resource(snapshot)
        breaches = self._evaluate(snapshot)
        if self._on_pressure is not None:
            self._on_pressure(snapshot, breaches)
        return snapshot

    def _evaluate(self, s: BrowserResourceSnapshot) -> tuple[str, ...]:
        breaches: list[str] = []
        if self._max_memory_mb and s.memory_mb is not None and s.memory_mb > self._max_memory_mb:
            breaches.append(f"memory {s.memory_mb:.0f}MB > {self._max_memory_mb}MB")
        if self._max_pages and s.pages > self._max_pages:
            breaches.append(f"pages {s.pages} > {self._max_pages}")
        return tuple(breaches)


__all__ = ["ResourceMonitor", "snapshot_to_record"]
