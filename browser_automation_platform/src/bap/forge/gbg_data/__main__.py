"""Show ranked GBG attack targets from a saved game response — the Phase-1 advisor.

    python -m bap.forge.gbg_data <file.json> [--limit N] [--include-locked]

`<file.json>` may be a raw `/game/json` array, a `getBattleground` responseData object, or
a single ServerResponse wrapper (e.g. the sanitized `dataset/api_samples/getBattleground.sample.json`).
Read-only: it parses and explains, it never touches the game.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bap.forge.gbg_data.advisor import rank_targets
from bap.forge.gbg_data.parser import parse


def _fmt_time(ts: int | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bap-forge-gbg", description="Rank GBG attack targets from the game's JSON.")
    ap.add_argument("file", help="a /game/json array or a getBattleground responseData JSON")
    ap.add_argument("--limit", type=int, default=10, help="how many targets to show")
    ap.add_argument("--include-locked", action="store_true",
                    help="also list locked provinces (planning ahead)")
    args = ap.parse_args(argv)

    path = Path(args.file)
    if not path.is_file():
        ap.error(f"not a file: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        ap.error(f"could not read JSON: {exc}")

    bg = parse(obj)
    if bg is None:
        print("No Guild-Battlegrounds data found in that file.")
        return 1

    me = bg.participants.get(bg.player.participant_id)
    print(f"Battleground: {bg.map_id}   observed {bg.observed_at}")
    print(f"You: {me.clan_name if me else bg.player.participant_id} "
          f"({me.colour if me else '?'})   attrition level: {bg.player.attrition_level}")
    print(f"Provinces: {len(bg.provinces)}   season ends {_fmt_time(bg.ends_at)}")
    if bg.pending_province_ids:
        print(f"Next change: province(s) {list(bg.pending_province_ids)} at "
              f"{_fmt_time(bg.pending_update_at)}")

    targets = rank_targets(bg, include_locked=args.include_locked)
    print(f"\nBest attack targets ({min(args.limit, len(targets))} of {len(targets)}):")
    if not targets:
        print("  (none currently open)")
    for i, t in enumerate(targets[:args.limit], 1):
        siege = f"  siege" if t.under_siege else ""
        lock = f"  opens {_fmt_time(t.locked_until)}" if t.locked else ""
        print(f"  {i:2}. province {t.province_id:<3} attrition {str(t.gain_attrition_chance)+'%':<5} "
              f"owner {t.owner_colour or '?':<7} {t.building_fraction or '-'}{siege}{lock}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
