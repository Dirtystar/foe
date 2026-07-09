"""Load comparison: a CPU-bound analyzer inline vs offloaded.

Inline, a blocking analyzer stalls the single event loop, so the *other*
session barely ticks. Offloaded, the loop stays free and the other session
keeps ticking. Demonstrates the fix quantitatively.
"""

import asyncio
import time

import pytest

from bap.app.composition import create_application
from bap.app.registries import AnalyzerRegistry
from bap.app.stubs import StubBrowser, StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.core.engine.scheduler import Scheduler
from bap.core.ports.vision_analyzer_port import VisionAnalyzerPort

pytestmark = pytest.mark.load

CONFIG = """
settings:
  max_sessions: 2
rule_packs:
  noop: []
profiles:
  - id: slow
    rule_pack: noop
    session: { interval_ms: 5 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: blocking
  - id: fast
    rule_pack: noop
    session: { interval_ms: 5 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: quick
"""

BLOCK_S = 0.02  # 20 ms of CPU-bound work per slow tick


class BlockingAnalyzer(VisionAnalyzerPort):
    @property
    def name(self):
        return "blocking"

    async def analyze(self, image, context):
        time.sleep(BLOCK_S)  # simulates cv2/tesseract CPU work
        return []


class QuickAnalyzer(VisionAnalyzerPort):
    @property
    def name(self):
        return "quick"

    async def analyze(self, image, context):
        return []


def _registry() -> AnalyzerRegistry:
    r = AnalyzerRegistry()
    r.register("blocking", BlockingAnalyzer)
    r.register("quick", QuickAnalyzer)
    return r


async def _fast_ticks_in(window_s: float, *, vision_workers) -> int:
    counts = {"fast": 0}

    def sink(r):
        if r.profile_id == "fast":
            counts["fast"] += 1

    supervisor = Supervisor(monitor=HealthMonitor(), sink=sink)
    scheduler = Scheduler(sleep=lambda s: asyncio.sleep(0), on_report=supervisor.on_report)
    app = create_application(
        load_config_from_string(CONFIG),
        browser=StubBrowser(),
        capture_port=StubCapturePort(),
        analyzer_registry=_registry(),
        scheduler=scheduler,
        vision_workers=vision_workers,
    )
    supervisor.session_manager = app.manager

    await app.start()
    await asyncio.sleep(window_s)  # real time window
    await app.stop()
    return counts["fast"]


async def test_offload_keeps_other_sessions_ticking(capsys):
    window = 0.4
    inline = await _fast_ticks_in(window, vision_workers=None)
    offloaded = await _fast_ticks_in(window, vision_workers=2)

    with capsys.disabled():
        print(
            f"\n[load] fast-session ticks in {window}s "
            f"| inline vision={inline} | offloaded vision={offloaded}"
        )

    # inline: the blocking analyzer stalls the loop, throttling the fast
    # session to ~window/BLOCK_S ticks. offloaded: the loop is free, so the
    # fast session ticks far more often.
    assert offloaded > inline * 2
