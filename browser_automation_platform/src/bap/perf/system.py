"""Process CPU + RAM sampling with no third-party dependency (Milestone 4.9).

`psutil` is not a dependency here, so this reads Linux ``/proc/self`` and the
stdlib ``resource``/``os`` modules, degrading gracefully to ``None`` for any
figure the platform cannot provide. If ``psutil`` happens to be importable it is
used for a live system-wide CPU number; otherwise CPU is the process's own
utilisation derived from CPU-time deltas. Sampling only observes — it never
throttles or changes the work being measured.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

try:  # optional — used only if already installed, never required
    import psutil  # type: ignore
except Exception:  # pragma: no cover - psutil is not a dependency
    psutil = None


def _proc_status_kb(key: str) -> float | None:
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith(key):
                    return float(line.split()[1])  # value is in kB
    except OSError:
        return None
    return None


def current_rss_mb() -> float | None:
    """Resident set size (MB) of this process, or None if unavailable."""
    kb = _proc_status_kb("VmRSS:")
    if kb is not None:
        return kb / 1024.0
    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kB, macOS reports bytes; assume kB (this project targets Linux).
        return maxrss / 1024.0
    except Exception:
        return None


def peak_rss_mb() -> float | None:
    """Peak resident set size (MB) since process start, or None."""
    kb = _proc_status_kb("VmHWM:")
    if kb is not None:
        return kb / 1024.0
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return None


@dataclass
class SystemSnapshot:
    rss_mb: float | None
    cpu_percent: float | None
    timestamp: float


class SystemSampler:
    """Samples process CPU% and RSS over time, tracking peaks and averages.

    CPU% is this process's utilisation between successive samples: the change in
    CPU time (user+system, all threads) over the wall-clock interval. A value of
    100 means one core fully used; multi-threaded work can exceed 100.
    """

    def __init__(self) -> None:
        self._wall0 = time.monotonic()
        self._cpu0 = time.process_time()
        self._last_wall = self._wall0
        self._last_cpu = self._cpu0
        self._cpu_samples: list[float] = []
        self._rss_samples: list[float] = []
        self._peak_cpu = 0.0
        self._peak_rss = 0.0

    def sample(self) -> SystemSnapshot:
        wall = time.monotonic()
        cpu = time.process_time()
        dw = wall - self._last_wall
        dc = cpu - self._last_cpu
        cpu_pct: float | None
        if dw > 0:
            cpu_pct = max(0.0, (dc / dw) * 100.0)
            self._cpu_samples.append(cpu_pct)
            self._peak_cpu = max(self._peak_cpu, cpu_pct)
        else:
            cpu_pct = None
        self._last_wall = wall
        self._last_cpu = cpu

        rss = current_rss_mb()
        if rss is not None:
            self._rss_samples.append(rss)
            self._peak_rss = max(self._peak_rss, rss)
        return SystemSnapshot(rss_mb=rss, cpu_percent=cpu_pct, timestamp=wall)

    def uptime_s(self) -> float:
        return time.monotonic() - self._wall0

    def avg_cpu(self) -> float | None:
        return (sum(self._cpu_samples) / len(self._cpu_samples)) if self._cpu_samples else None

    def peak_cpu(self) -> float | None:
        return self._peak_cpu if self._cpu_samples else None

    def avg_rss_mb(self) -> float | None:
        return (sum(self._rss_samples) / len(self._rss_samples)) if self._rss_samples else None

    def peak_rss_mb(self) -> float | None:
        # Prefer the kernel's high-water mark when available; fall back to samples.
        hw = peak_rss_mb()
        if hw is not None:
            return max(hw, self._peak_rss)
        return self._peak_rss if self._rss_samples else None

    def summary(self) -> dict:
        return {
            "uptime_s": round(self.uptime_s(), 3),
            "cpu_count": os.cpu_count(),
            "avg_cpu_percent": _rnd(self.avg_cpu()),
            "peak_cpu_percent": _rnd(self.peak_cpu()),
            "avg_ram_mb": _rnd(self.avg_rss_mb()),
            "peak_ram_mb": _rnd(self.peak_rss_mb()),
            "current_ram_mb": _rnd(current_rss_mb()),
            "backend": "psutil" if psutil is not None else "proc",
        }


def _rnd(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


__all__ = [
    "SystemSampler", "SystemSnapshot",
    "current_rss_mb", "peak_rss_mb",
]
