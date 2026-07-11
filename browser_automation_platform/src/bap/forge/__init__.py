"""Forge of Empires domain: the product layer on top of the generic engine.

Everything Forge-specific lives here — persistent Worlds, badge detection,
capture configuration — so the core engine stays site-agnostic. Nothing in
`bap.core` imports from this package; the dependency only runs the other way.
"""
