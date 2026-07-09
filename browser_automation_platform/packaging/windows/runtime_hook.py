"""PyInstaller runtime hook — runs inside the frozen app before user code.

Points Playwright at a per-user browser directory under %LOCALAPPDATA%/BAP so
first-run `playwright install` writes there (a writable, roaming-safe location)
rather than into Program Files. Also stops Playwright from trying to re-download
during any bundled npm postinstall. Kept dependency-free and defensive: any
failure here must not stop the app from launching.
"""

import os


def _bap_home() -> str:
    override = os.environ.get("BAP_HOME")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    return os.path.join(base, "BAP")


try:
    _browsers = os.path.join(_bap_home(), "data", "ms-playwright")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _browsers)
    os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")
except Exception:
    pass
