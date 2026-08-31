"""`python -m bap.forge.action` → the CDP click CLI."""

from __future__ import annotations

import sys

from bap.forge.action.cdp_click import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
