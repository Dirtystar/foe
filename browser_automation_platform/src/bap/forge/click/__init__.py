"""M6A.1 — Manual Open & Verify (single click + independent panel verification).

The first real click: one operator-confirmed left click on the validated map badge,
used to open the province/detail panel for an *independent* second reading of the
percentage, then STOP. No battle loop, scheduler, retry, or repeated clicking.

- `port.ClickPort` — the narrow single-click boundary (separate from the movement-
  only cursor port).
- `open_verify.OpenAndVerifyController` — the gated one-click flow.
- `panel_reader.PanelReader` — the independent, fail-closed panel percentage reader.
- `panel_calibration` — measurement-only tool for the next panel control's position.
- `audit.ClickAudit` — append-only, fail-closed click trail.
"""

from __future__ import annotations

from bap.forge.click.port import FORBIDDEN_INPUT_METHODS, ClickPort

__all__ = ["ClickPort", "FORBIDDEN_INPUT_METHODS"]
