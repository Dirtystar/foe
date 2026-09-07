"""``bap-alert`` — FoE Alerting CLI (subproject; one world, read-only).

    bap-alert preview dataset/api_samples/getBattleground.sample.json --at capture
    bap-alert labels  dataset/api_samples/map_data.*.sample.json --write province_labels.cz8.json
    bap-alert check   --config alerting.json --send "test"
    bap-alert run     --config alerting.json [--dry-run]

``preview`` and ``labels`` work entirely from saved JSON — no game, no browser — which is how
the message format and the province naming get settled before anything is posted to a group.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from bap.alerting.config import DEFAULT_CONFIG_PATH, AlertConfig
from bap.alerting.engine import AlertEngine
from bap.alerting.labels import LabelBook, auto_labels
from bap.alerting.notifiers import GreenApiNotifier, NullNotifier, build_notifier
from bap.alerting.render import format_message, format_schedule
from bap.alerting.schedule import SCOPES, unlock_events
from bap.alerting.state import SentLog
from bap.forge.gbg_data.map_layout import parse_map_data
from bap.forge.gbg_data.parser import parse


def _read_json(ap, path):
    p = Path(path)
    if not p.is_file():
        ap.error(f"not a file: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                       # noqa: BLE001
        ap.error(f"could not read JSON: {exc}")


def _labels_for(cfg_labels, layout=None) -> LabelBook:
    return LabelBook.build(path=cfg_labels or None, layout=layout)


# --------------------------------------------------------------------- preview

def cmd_preview(args, ap) -> int:
    bg = parse(_read_json(ap, args.file))
    if bg is None:
        print("No Guild-Battlegrounds data in that file.")
        return 1
    layout = None
    if args.map_data:
        layout = parse_map_data(_read_json(ap, args.map_data))
    labels = _labels_for(args.labels, layout)

    if args.at == "capture":
        locks = [p.locked_until for p in bg.provinces if p.locked_until]
        now = (min(locks) - 60) if locks else time.time()
    elif args.at:
        now = float(args.at)
    else:
        now = time.time()

    events = unlock_events(bg, labels=labels, scope=args.scope, now=now,
                           horizon_seconds=int(args.horizon * 3600))
    me = bg.participants.get(bg.player.participant_id)
    print(f"map {bg.map_id}   you: {me.clan_name if me else bg.player.participant_id} "
          f"({me.colour if me else '?'})   scope={args.scope}")
    print(f"{len(events)} upcoming opening(s) in the next {args.horizon:g} h:")
    print(format_schedule(events, limit=args.limit))
    if events:
        print("\nWhatsApp message for the next opening(s):")
        first = [e for e in events if e.opens_at == events[0].opens_at]
        print("-" * 24)
        print(format_message(first))
        print("-" * 24)
    return 0


# ---------------------------------------------------------------------- labels

def cmd_labels(args, ap) -> int:
    obj = _read_json(ap, args.file)
    layout = parse_map_data(obj, map_id=args.map_id or None)
    if layout is None:
        print("That file is not a GBG map asset (expected the map/data/<mapId> body).")
        return 1
    auto = auto_labels(layout)
    existing = LabelBook.build(path=args.labels or None).overrides
    print(f"map {layout.map_id or '?'}  {len(auto)} provinces  ({layout.width}x{layout.height})")
    for pid in sorted(auto):
        x, y = layout.flags[pid]
        mine = existing.get(pid, "")
        print(f"  province {pid:<3} grid {auto[pid]:<4} flag ({int(x):>4},{int(y):>4})"
              f"{'   guild name: ' + mine if mine else ''}")
    if args.write:
        out = {"map_id": layout.map_id,
               "_comment": "province id -> the name your guild uses (e.g. \"A1X\"). "
                           "Values are pre-filled with a generated grid label; overwrite them.",
               "labels": {str(pid): existing.get(pid, auto[pid]) for pid in sorted(auto)}}
        Path(args.write).write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
        print(f"\nwrote {args.write} — replace the generated values with your guild's names.")
    return 0


# ----------------------------------------------------------------------- check

def cmd_check(args, ap) -> int:
    cfg = AlertConfig.load(args.config)
    print(f"world={cfg.world}  scope={cfg.scope}  lead={cfg.lead_minutes:g} min  "
          f"notifier={cfg.notifier}")
    if cfg.notifier.startswith("green"):
        g = cfg.green_api
        missing = [n for n, v in (("id_instance", g.id_instance), ("api_token", g.api_token),
                                  ("chat_id", g.chat_id)) if not v]
        if missing:
            print(f"green-api not configured: missing {', '.join(missing)} "
                  f"(set GREEN_API_ID_INSTANCE / GREEN_API_TOKEN / GREEN_API_CHAT_ID)")
            return 1
        api = GreenApiNotifier(g.id_instance, g.api_token, g.chat_id, base_url=g.base_url)
        try:
            state = api.state()
        except Exception as exc:                    # noqa: BLE001
            print(f"could not reach green-api: {exc}")
            return 1
        print(f"instance state: {state.get('stateInstance', state)}")
        if state.get("stateInstance") != "authorized":
            print("→ link the phone in the Green API console before messages will send.")
            return 1
    if args.send:
        ok = build_notifier(cfg).send(args.send)
        print("test message sent" if ok else "test message FAILED")
        return 0 if ok else 1
    return 0


# ------------------------------------------------------------------------- run

def cmd_run(args, ap) -> int:  # pragma: no cover - needs a live browser
    from bap.alerting.watcher import run_watch

    cfg = AlertConfig.load(args.config)
    notifier = NullNotifier() if args.dry_run else build_notifier(cfg)
    engine = AlertEngine(cfg, notifier, SentLog(cfg.state_file),
                         _labels_for(cfg.labels_file))
    print(f"FoE Alerting — world {cfg.world}, scope {cfg.scope}, "
          f"{cfg.lead_minutes:g} min lead, via {getattr(notifier, 'name', '?')}"
          f"{'  [dry run]' if args.dry_run else ''}")
    print("Open Guild Battlegrounds on that world; every entry refreshes the schedule.\n"
          "Ctrl-C to stop.")

    def _status(eng, sent):
        if sent:
            print(f"[{time.strftime('%H:%M:%S')}] sent:\n{format_message(sent)}", flush=True)
        elif args.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] {eng.status_line()}", flush=True)

    return run_watch(cfg, engine, endpoint=args.cdp, refresh_minutes=args.refresh_minutes,
                     on_status=_status)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bap-alert",
                                 description="FoE Alerting — announce GBG province openings.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preview", help="schedule + message from a saved snapshot (no browser)")
    p.add_argument("file", help="a /game/json array or a getBattleground responseData JSON")
    p.add_argument("--scope", choices=SCOPES, default="relevant")
    p.add_argument("--labels", default="", help="province labels JSON")
    p.add_argument("--map-data", default="", help="map asset JSON (for generated grid labels)")
    p.add_argument("--at", default="", help="unix time to evaluate at, or 'capture'")
    p.add_argument("--horizon", type=float, default=12.0, help="hours ahead to list")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("labels", help="list provinces with generated grid labels / write a template")
    p.add_argument("file", help="the map/data/<mapId> asset JSON")
    p.add_argument("--labels", default="", help="existing labels JSON to merge")
    p.add_argument("--map-id", default="", help="stamp this map id into the written template "
                                                "(the asset body itself doesn't carry one)")
    p.add_argument("--write", default="", help="write a labels template to this path")
    p.set_defaults(func=cmd_labels)

    p = sub.add_parser("check", help="verify config + gateway, optionally send a test message")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--send", default="", help="send this text to the configured chat")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="watch the world's tab and post openings as they come due")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--cdp", default="", help="Chrome CDP endpoint (default: the app's)")
    p.add_argument("--dry-run", action="store_true", help="decide everything, send nothing")
    p.add_argument("--refresh-minutes", type=float, default=0.0,
                   help="reload the tab this often when nothing else refreshes GBG")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_run)
    return ap


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args, ap)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
