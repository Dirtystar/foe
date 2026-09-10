from bap.adapters.browser import playwright_metrics as pm
from bap.adapters.browser.playwright_metrics import (
    PlaywrightBrowserMetrics,
    _chromium_process_tree_stats,
)


class FakeManager:
    def __init__(self, counts):
        self._counts = counts

    def context_and_page_counts(self):
        return self._counts


async def test_collect_reads_counts_and_process_stats(monkeypatch):
    monkeypatch.setattr(pm, "_chromium_process_tree_stats", lambda: (512.0, 12.0))

    snap = await PlaywrightBrowserMetrics(FakeManager((2, 5)), browser_id="b1").collect()

    assert (snap.contexts, snap.pages) == (2, 5)
    assert snap.memory_mb == 512.0
    assert snap.cpu_percent == 12.0
    assert snap.browser_id == "b1"
    assert snap.collected_at is not None


async def test_missing_process_is_handled_as_none(monkeypatch):
    monkeypatch.setattr(pm, "_chromium_process_tree_stats", lambda: (None, None))

    snap = await PlaywrightBrowserMetrics(FakeManager((0, 0))).collect()

    assert snap.memory_mb is None
    assert snap.cpu_percent is None
    assert (snap.pages, snap.contexts) == (0, 0)


def test_process_stats_never_raise_without_a_chromium_process():
    # In a test environment there is no Chromium child (and psutil may be
    # absent): the helper must degrade to (None, None), never raise.
    memory, cpu = _chromium_process_tree_stats()
    assert memory is None or isinstance(memory, float)
    assert cpu is None or isinstance(cpu, float)


def test_process_stats_return_none_when_psutil_missing(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "psutil", None)  # makes `import psutil` raise
    assert _chromium_process_tree_stats() == (None, None)
