"""GUI boundary guard + a real end-to-end run on the stub runtime."""

import time
from pathlib import Path

import pytest

import bap

SRC = Path(bap.__file__).parent


def _py_files(package: str):
    return (SRC / package).rglob("*.py")


def test_core_and_config_never_import_pyside():
    offenders = []
    for package in ("core", "config"):
        for path in _py_files(package):
            text = path.read_text(encoding="utf-8")
            if "PySide6" in text or "PyQt" in text:
                offenders.append(path.name)
    assert offenders == [], f"core/config must not import a GUI toolkit: {offenders}"


# --- end-to-end with the real service + stub application ----------------------

STUB_CONFIG = """
rule_packs:
  demo:
    - id: always
      condition: { type: exists, field: page.ready }
      actions:
        - type: log
          params: {}
profiles:
  - id: demo
    rule_pack: demo
    session: { interval_ms: 10 }
    capture_bindings:
      - name: page
        target: full_page
        analyzers:
          - type: ocr
            settings: { emit: { ready: true } }
"""


def test_gui_runs_against_stub_runtime(qapp):
    pytest.importorskip("PySide6")
    from bap.app.composition import create_application
    from bap.config.config_loader import load_config_from_string
    from bap.gui.main_window import MainWindow
    from bap.gui.qt_bridge import QtReportBridge
    from bap.gui.runtime_service import RuntimeService

    config = load_config_from_string(STUB_CONFIG)
    bridge = QtReportBridge()
    app = create_application(config, on_report=bridge.on_report)  # all stubs
    service = RuntimeService(app)
    service.on_state_change = bridge.on_state_change
    service.on_error = bridge.on_error
    service.start_loop()
    window = MainWindow(service, bridge)

    try:
        # One real manual tick, driven through the background thread + bridge.
        service.tick_once().result(timeout=5)

        # Deliver the queued cross-thread signal onto the UI thread.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            if window.table.item(0, 2) and window.table.item(0, 2).text() == "1":
                break
            time.sleep(0.01)

        assert window.table.item(0, 0).text() == "demo"
        assert window.table.item(0, 2).text() == "1"  # last tick number
        assert window.table.item(0, 1).text() == "completed"
        assert "[demo] tick #1" in window.log.toPlainText()
    finally:
        window.close()
