from __future__ import annotations

from enum import Enum


class ObservationKind(Enum):
    """What kind of fact a vision analyzer extracted from an image."""

    TEXT = "text"                      # recognized text (OCR or AI-read)
    TEMPLATE_MATCH = "template_match"  # a known reference image was found
    OBJECT = "object"                  # a detected/classified object
    CUSTOM = "custom"                  # plugin-defined; semantics in attributes
