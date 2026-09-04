"""Local crash bundles."""

from __future__ import annotations

import json
import logging

from bap.ops.crash import CrashReporter, LogTailHandler, install


def _reporter(tmp_path) -> CrashReporter:
    tail = LogTailHandler(capacity=5)
    tail.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    return CrashReporter(version="9.9.9", crashes_dir=tmp_path / "crashes", log_tail=tail)


def _raise(exc: Exception):
    try:
        raise exc
    except Exception as e:  # noqa: BLE001
        return type(e), e, e.__traceback__


def test_log_tail_is_bounded():
    tail = LogTailHandler(capacity=3)
    tail.setFormatter(logging.Formatter("%(message)s"))
    for i in range(10):
        tail.emit(logging.LogRecord("t", logging.INFO, __file__, 0, f"line{i}", None, None))
    assert tail.tail() == ["line7", "line8", "line9"]


def test_bundle_contains_required_fields(tmp_path):
    reporter = _reporter(tmp_path)
    reporter.set_status("degraded")
    reporter._log_tail.emit(
        logging.LogRecord("bap", logging.WARNING, __file__, 0, "something odd", None, None)
    )
    bundle = reporter.build_bundle(*_raise(ValueError("kaboom")))

    assert bundle["version"] == "9.9.9"
    assert bundle["last_status"] == "degraded"
    assert bundle["exception"]["type"] == "ValueError"
    assert bundle["exception"]["message"] == "kaboom"
    assert "Traceback" in bundle["exception"]["traceback"]
    assert set(bundle["os"]) >= {"platform", "system", "machine", "python", "sys_platform"}
    assert any("something odd" in line for line in bundle["log_tail"])
    assert "timestamp" in bundle


def test_write_produces_a_valid_json_file(tmp_path):
    reporter = _reporter(tmp_path)
    path = reporter.write(*_raise(RuntimeError("boom")))

    assert path is not None and path.exists()
    assert path.parent == tmp_path / "crashes"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["exception"]["type"] == "RuntimeError"


def test_write_never_raises_on_bad_directory(tmp_path):
    # crashes_dir path collides with an existing *file* -> mkdir fails, but
    # write() must swallow it and return None rather than raising.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    reporter = CrashReporter(
        version="0", crashes_dir=blocker / "crashes", log_tail=LogTailHandler()
    )
    assert reporter.write(*_raise(RuntimeError("x"))) is None


def test_install_attaches_the_tail_handler():
    reporter = _reporter_tmp()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        install(reporter)
        assert reporter._log_tail in logging.getLogger().handlers
    finally:
        root.handlers[:] = before


def _reporter_tmp() -> CrashReporter:
    import tempfile
    from pathlib import Path

    return CrashReporter(
        version="0", crashes_dir=Path(tempfile.gettempdir()) / "bap-x", log_tail=LogTailHandler()
    )
