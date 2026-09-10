"""Frozen-app entry point for the CLI (bundled by PyInstaller).

Exposes the `bap` dispatcher (run / validate-config / gui) as a console exe so
beta users can validate configs and run headless from a terminal.
"""

from bap.cli import main

if __name__ == "__main__":
    main()
