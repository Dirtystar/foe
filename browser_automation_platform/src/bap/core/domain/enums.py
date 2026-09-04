from __future__ import annotations

from enum import Enum


class ObservationKind(Enum):
    """What kind of fact a vision analyzer extracted from an image."""

    TEXT = "text"                      # recognized text (OCR or AI-read)
    TEMPLATE_MATCH = "template_match"  # a known reference image was found
    OBJECT = "object"                  # a detected/classified object
    CUSTOM = "custom"                  # plugin-defined; semantics in attributes


class BrowserOwnership(Enum):
    """Whether BAP owns the browser process, or is a read-only guest of one the
    operator owns.

    MANAGED  — BAP launched the browser and owns its lifecycle: Open starts it,
               Close stops it, and application exit tears it down.
    EXTERNAL — the operator launched Chrome and owns it; BAP attaches over CDP as
               a guest. Attach connects, Disconnect detaches, and BAP NEVER closes
               the process — not on Disconnect, not on Stop, not on exit.

    This is the single, explicit source of ownership for the browser lifecycle;
    adapters declare it and the BrowserController reads it, so there is no
    mutable per-call flag deciding whether a close kills the operator's browser.
    """

    MANAGED = "managed"
    EXTERNAL = "external"
