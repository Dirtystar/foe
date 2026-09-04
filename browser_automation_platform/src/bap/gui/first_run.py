"""First-run wizard and browser-install dialog.

Pure presentation/controller wrappers over the ops-layer helpers: the dialogs
collect intent and show progress, while the actual work (installing Chromium)
lives in `bap.ops.browser_install`. Long-running work runs on a QThread so the
UI never freezes. No runtime/automation logic lives here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from bap.ops import browser_install
from bap.ops.paths import AppPaths, ensure_dirs, get_paths

_MARKER = ".first_run_done"


def is_first_run(paths: AppPaths | None = None) -> bool:
    paths = paths or get_paths()
    return not (paths.data_dir / _MARKER).exists()


def mark_setup_complete(paths: AppPaths | None = None) -> None:
    paths = ensure_dirs(paths or get_paths())
    (paths.data_dir / _MARKER).write_text("done\n", encoding="utf-8")


class _InstallThread(QThread):
    """Runs the (blocking) browser install off the UI thread."""

    progress = Signal(str)
    done = Signal(int)

    def __init__(self, install_fn: Callable[[Callable[[str], None]], int]) -> None:
        super().__init__()
        self._install = install_fn

    def run(self) -> None:  # executed on the worker thread
        try:
            code = self._install(self.progress.emit)
        except Exception as exc:  # never let the thread die silently
            self.progress.emit(f"Error: {exc}")
            code = 1
        self.done.emit(int(code))


class BrowserInstallDialog(QDialog):
    """Download Chromium for real automation, with a live progress log."""

    def __init__(self, parent=None, *, install_fn=None) -> None:
        super().__init__(parent)
        self._install_fn = install_fn or browser_install.install_chromium
        self._thread: _InstallThread | None = None

        self.setWindowTitle("Install browser")
        layout = QVBoxLayout(self)

        self._already = browser_install.is_chromium_installed()
        intro = (
            "Chromium is already installed — you can run real automation."
            if self._already
            else "Real automation needs Chromium (~300–450 MB). This downloads it "
            "into your user folder; no admin rights are required."
        )
        layout.addWidget(QLabel(intro, wordWrap=True))

        self.output = QPlainTextEdit(readOnly=True)
        self.output.setMaximumBlockCount(1000)
        layout.addWidget(self.output)

        buttons = QHBoxLayout()
        self.install_button = QPushButton("Install now")
        self.install_button.setEnabled(not self._already)
        self.close_button = QPushButton("Close")
        buttons.addStretch(1)
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.install_button.clicked.connect(self._start)
        self.close_button.clicked.connect(self.reject)

    # --- install flow -------------------------------------------------------

    def _start(self) -> None:
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self._append("Starting browser installation…")
        self._thread = _InstallThread(self._install_fn)
        self._thread.progress.connect(self._append)
        self._thread.done.connect(self._finished)
        self._thread.start()

    def _finished(self, code: int) -> None:
        if code == 0:
            self._append("Browser installed successfully.")
        else:
            self._append(f"Installation failed (code {code}). See the log above.")
            self.install_button.setEnabled(True)
        self.close_button.setEnabled(True)

    def _append(self, line: str) -> None:
        self.output.appendPlainText(line)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(30_000)
        super().closeEvent(event)


class FirstRunDialog(QDialog):
    """Shown once on first launch: explains stub vs real mode and offers to
    install the browser. Marks setup complete on close."""

    def __init__(self, parent=None, *, paths: AppPaths | None = None) -> None:
        super().__init__(parent)
        self._paths = paths or get_paths()
        self.setWindowTitle("Welcome to Browser Automation Platform")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<h3>Welcome!</h3>"))
        layout.addWidget(
            QLabel(
                "The app is ready to use. By default it runs in a safe "
                "<b>demo (stub) mode</b> — no browser and no network — so you can "
                "explore the monitor right away with <b>Start</b> / <b>Tick once</b>.",
                wordWrap=True,
            )
        )
        layout.addWidget(
            QLabel(
                "To drive a <b>real</b> browser later, install Chromium once. You "
                "can do that now, or anytime from the <b>Tools → Install browser</b> menu.",
                wordWrap=True,
            )
        )

        self.show_again = QCheckBox("Show this welcome next time")
        self.show_again.setChecked(False)
        layout.addWidget(self.show_again)

        row = QHBoxLayout()
        self.install_button = QPushButton("Install browser now…")
        row.addWidget(self.install_button)
        row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        row.addWidget(self.buttons)
        layout.addLayout(row)

        self.install_button.clicked.connect(self._install)
        self.buttons.accepted.connect(self.accept)

    def _install(self) -> None:
        BrowserInstallDialog(self).exec()

    def done(self, result: int) -> None:  # noqa: N802 - Qt override
        # Persist the "seen it" marker unless the user asked to see it again.
        if not self.show_again.isChecked():
            mark_setup_complete(self._paths)
        super().done(result)


def maybe_run_first_run(paths: AppPaths | None = None) -> bool:
    """Show the wizard if this is a first run. Returns True if it was shown."""
    paths = paths or get_paths()
    if not is_first_run(paths):
        return False
    FirstRunDialog(paths=paths).exec()
    return True


__all__ = [
    "BrowserInstallDialog",
    "FirstRunDialog",
    "is_first_run",
    "mark_setup_complete",
    "maybe_run_first_run",
]
