"""Input adapters for the single-click boundary (Milestone 6A.1).

`FakeClick` (records, never touches the OS) is the default in tests; the real
`WindowsSingleClick` performs one Win32 left click. Both implement
:class:`bap.forge.click.port.ClickPort` and expose **only** ``click_at``.
"""

from __future__ import annotations

from bap.adapters.input.fake_click import FakeClick

__all__ = ["FakeClick"]
