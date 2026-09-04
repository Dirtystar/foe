"""CDP-targeted action layer for Forge — click the game tab over CDP (opt-in)."""

from bap.forge.action.cdp_click import CdpClicker, connect_and_run, run_click_loop

__all__ = ["CdpClicker", "run_click_loop", "connect_and_run"]
