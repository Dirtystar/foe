"""Read-only Guild-Battlegrounds structured-data reader (the game's own JSON).

Parse the game's `/game/json` GBG payload into a typed model and rank attack targets
directly from the exact fields — no pixels, no OCR, no calibration. See
`docs/design/GBG_API_SCHEMA.md`.
"""

from bap.forge.gbg_data.advisor import TargetSuggestion, rank_targets
from bap.forge.gbg_data.model import (
    Battleground,
    ConquestProgress,
    Participant,
    PlayerState,
    Province,
)
from bap.forge.gbg_data.live import LiveGbgReader, make_response_handler, render
from bap.forge.gbg_data.parser import parse, parse_battleground, parse_game_json

__all__ = [
    "Battleground", "Province", "Participant", "PlayerState", "ConquestProgress",
    "parse", "parse_battleground", "parse_game_json",
    "rank_targets", "TargetSuggestion",
    "LiveGbgReader", "make_response_handler", "render",
]
