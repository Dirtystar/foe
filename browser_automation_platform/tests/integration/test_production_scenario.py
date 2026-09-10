"""Production-hardening scenario: the whole stack, for real.

Skipped by default. Run with:  pytest -m integration
Exercises real Chromium + capture + OCR + template matching + actions, the
composition root, the GUI service/bridge/window, and the new tick metrics —
end to end. Skips gracefully if the browser binary or tesseract is missing.
"""

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("PySide6")
pytest.importorskip("cv2")
pytest.importorskip("pytesseract")

import cv2
import numpy as np
import pytesseract
from PySide6.QtWidgets import QApplication

from bap.adapters.actions.playwright_action_handlers import playwright_action_registry
from bap.adapters.browser.playwright_adapter import PlaywrightBrowserManager
from bap.adapters.capture.playwright_capture import PlaywrightCaptureAdapter
from bap.adapters.vision.registry import production_analyzer_registry
from bap.adapters.vision.template_match_opencv import TemplateMatchAnalyzer
from bap.app.composition import create_application
from bap.config.config_loader import load_config
from bap.core.domain.models import Rect, TabProfile
from bap.core.ports.vision_analyzer_port import AnalyzerContext
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge
from bap.gui.runtime_service import RuntimeService

_EXE = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
_CONFIG = Path(__file__).resolve().parents[2] / "config" / "demo.production.yaml"


def _tesseract_ready() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.skipif(not _tesseract_ready(), reason="tesseract binary not installed")
async def test_full_stack_scenario_with_gui_and_metrics(qapp):
    config = load_config(_CONFIG)

    reports = []
    bridge = QtReportBridge()

    def on_report(report):
        reports.append(report)
        bridge.on_report(report)

    app = create_application(
        config,
        on_report=on_report,
        browser=PlaywrightBrowserManager(
            headless=True, max_tabs=1, executable_path=_EXE
        ),
        capture_port=PlaywrightCaptureAdapter(),
        action_registry=playwright_action_registry(),
        analyzer_registry=production_analyzer_registry(),
    )
    service = RuntimeService(app)
    service.on_state_change = bridge.on_state_change
    service.on_error = bridge.on_error
    service.start_loop()
    window = MainWindow(service, bridge)

    try:
        try:
            service.tick_once().result(timeout=30)
        except Exception as exc:
            pytest.skip(f"real browser unavailable: {exc}")

        assert reports, "no tick report produced"
        report = reports[-1]
        assert report.completed, f"tick failed: {report.status} {report.error}"

        # real OCR read the stock number from the rendered page
        assert report.page_state.value_of("dashboard.number") == 7

        # the rule fired and the real click succeeded
        assert report.evaluation.actions, "expected the restock rule to match"
        assert report.execution.fully_succeeded

        # metrics were measured for the real stages
        m = report.metrics
        assert m is not None
        assert m.total_ms > 0.0
        assert m.capture_ms > 0.0
        assert m.vision_ms > 0.0  # real OCR is not free

        # the GUI reflected the tick, including the timing column
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            if window.table.item(0, 2) and window.table.item(0, 2).text() == "1":
                break
            time.sleep(0.01)
        assert window.table.item(0, 0).text() == "warehouse"
        assert window.table.item(0, 1).text() == "completed"
        assert "ms" in window.table.item(0, 6).text()  # Timing column populated
    finally:
        window.close()
        service.stop_loop()


@pytest.mark.skipif(not _tesseract_ready(), reason="tesseract binary not installed")
async def test_real_template_match_on_captured_region():
    """Real capture + real OpenCV template matching: screenshot a region,
    use it as its own template, and confirm a high-confidence match."""
    manager = PlaywrightBrowserManager(headless=True, max_tabs=1, executable_path=_EXE)
    try:
        await manager.start()
    except Exception as exc:
        pytest.skip(f"real browser unavailable: {exc}")

    try:
        page = "data:text/html,<html><body><div style='width:80px;height:40px;background:#39c'></div></body></html>"
        tab = await manager.open_tab(TabProfile(id="t", start_url=page))
        capture = PlaywrightCaptureAdapter()

        region_img = await capture.capture(tab, Rect(x=0, y=0, w=80, h=40))
        # persist the captured region as a template file
        import tempfile

        arr = cv2.imdecode(np.frombuffer(region_img.data, np.uint8), cv2.IMREAD_GRAYSCALE)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            cv2.imwrite(fh.name, arr)
            template_path = fh.name

        full = await capture.capture(tab)
        obs = await TemplateMatchAnalyzer().analyze(
            full,
            AnalyzerContext(
                profile_id="t", target_name="panel", settings={"template": template_path, "threshold": 0.7}
            ),
        )

        assert obs, "expected the captured region to match within the full page"
        assert obs[0].confidence > 0.9
        assert obs[0].region is not None
    finally:
        await manager.stop()
