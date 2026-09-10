"""Frozen-app entry point for the GUI (bundled by PyInstaller).

A thin launcher so PyInstaller has a concrete script to analyse; all behaviour
lives in bap.gui.gui_main.
"""

from bap.gui.gui_main import main

if __name__ == "__main__":
    main()
