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
from bap.alerting.labels import LabelBook, _best_auto_labels
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


def _layout_for(ap, map_data_arg) -> object | None:
    """Bootstrap labels from a saved map asset instead of waiting to catch a live one.

    Opt-in only (no bundled default): a stale asset from a past season would produce
    confidently *wrong* codes, which is worse for the guild than the honest ``#<id>``
    fallback — the same "stale beats silent" tradeoff ``AlertEngine`` already makes for
    snapshot age. Prefer letting ``run``/``serve`` catch the live ``/map/data`` response.
    """
    if not map_data_arg:
        return None
    return parse_map_data(_read_json(ap, map_data_arg))


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
        window = int(args.window * 60)
        batch = [e for e in events if e.opens_at <= events[0].opens_at + window]
        print(f"\nWhatsApp message for the first batch ({args.window:g} min window, "
              f"{len(batch)} of {len(events)} openings):")
        print("-" * 28)
        print(format_message(batch))
        print("-" * 28)
    return 0


# ---------------------------------------------------------------------- labels

def cmd_labels(args, ap) -> int:
    obj = _read_json(ap, args.file)
    layout = parse_map_data(obj, map_id=args.map_id or None)
    if layout is None:
        print("That file is not a GBG map asset (expected the map/data/<mapId> body).")
        return 1
    existing = LabelBook.build(path=args.labels or None).overrides
    auto = _best_auto_labels(layout, existing)
    print(f"map {layout.map_id or '?'}  {len(auto)} provinces  ({layout.width}x{layout.height})")
    for pid in sorted(auto):
        x, y = layout.flags[pid]
        mine = existing.get(pid, "")
        print(f"  province {pid:<3} code {auto[pid]:<4} flag ({int(x):>4},{int(y):>4})"
              f"{'   guild name: ' + mine if mine else ''}")
    if args.write:
        out = {"map_id": layout.map_id,
               "_comment": "province id -> the name your guild uses (e.g. \"A1X\"). "
                           "Values are pre-filled with the computed ring/sector code; "
                           "overwrite them where the guild says something different.",
               "labels": {str(pid): existing.get(pid, auto[pid]) for pid in sorted(auto)}}
        Path(args.write).write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
        print(f"\nwrote {args.write} — replace the generated values with your guild's names.")
    return 0


# ----------------------------------------------------------------------- check

def cmd_check(args, ap) -> int:
    cfg = AlertConfig.load(args.config)
    print(f"world={cfg.world}  scope={cfg.scope}  "
          f"batch={cfg.trigger_lead_minutes:g} min lead / {cfg.window_minutes:g} min window  "
          f"side={cfg.side_rule}  notifier={cfg.notifier}")
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
    layout = _layout_for(ap, args.map_data)
    engine = AlertEngine(cfg, notifier, SentLog(cfg.state_file),
                         _labels_for(cfg.labels_file, layout))
    if layout is not None:
        print(f"labels bootstrapped from {args.map_data} — remove --map-data to rely on the "
              f"live map instead if this season's map may differ.")
    print(f"FoE Alerting — world {cfg.world}, scope {cfg.scope}, batch "
          f"{cfg.trigger_lead_minutes:g}/{cfg.window_minutes:g} min, "
          f"via {getattr(notifier, 'name', '?')}"
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


# ------------------------------------------------------------ collect / serve

def cmd_collect(args, ap) -> int:  # pragma: no cover - needs a live browser
    """Watch the world's tab and forward snapshots to a scheduler. Decides nothing itself."""
    from bap.alerting.relay import RelayClient, make_relay_handler, secret_from_env
    from bap.alerting.watcher import run_watch
    from bap.forge.gbg_data.live import LiveGbgReader

    cfg = AlertConfig.load(args.config)
    secret = secret_from_env(args.secret)
    if not secret:
        ap.error("no shared secret — set ALERT_RELAY_SECRET (same value as the scheduler)")
    client = RelayClient(args.to, secret, world=cfg.world)
    handler = make_relay_handler(LiveGbgReader(), client)
    print(f"FoE Alerting collector — world {cfg.world} → {client.url}")
    print("Open Guild Battlegrounds on that world. Nothing is sent to the group from here.\n"
          "Ctrl-C to stop.")

    def _status(_engine, _sent):
        if args.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] forwarded {client.sent}, "
                  f"failed {client.failed}", flush=True)

    return run_watch(cfg, None, handler=handler, endpoint=args.cdp,
                     refresh_minutes=args.refresh_minutes, on_status=_status)


def cmd_serve(args, ap) -> int:  # pragma: no cover - a long-running server
    """Hold the newest snapshot, decide, and send. The half that needs no game."""
    from bap.alerting.relay import SnapshotReceiver, secret_from_env, serve_relay

    cfg = AlertConfig.load(args.config)
    notifier = NullNotifier() if args.dry_run else build_notifier(cfg)
    layout = _layout_for(ap, args.map_data)
    engine = AlertEngine(cfg, notifier, SentLog(cfg.state_file), _labels_for(cfg.labels_file, layout))
    receiver = SnapshotReceiver(engine)
    serve_relay(receiver, secret=secret_from_env(args.secret), port=args.port, host=args.host)
    print(f"FoE Alerting scheduler — world {cfg.world}, scope {cfg.scope}, "
          f"via {getattr(notifier, 'name', '?')}"
          f"{'  [dry run]' if args.dry_run else ''}")
    print("Waiting for collectors. Ctrl-C to stop.")
    try:
        while True:
            sent = engine.tick()
            if sent:
                print(f"[{time.strftime('%H:%M:%S')}] sent:\n{format_message(sent)}",
                      flush=True)
            elif args.verbose:
                print(f"[{time.strftime('%H:%M:%S')}] {engine.status_line()}", flush=True)
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        print()
    return 0


# --------------------------------------------------------------------------- ui

def cmd_ui(args, ap) -> int:
    """The local control panel: message format, labels, credentials, log."""
    from bap.alerting.webui import LogBuffer, UiState, serve

    buf = LogBuffer().attach()
    state = UiState(args.config, sample=args.sample or None,
                    map_data=args.map_data or None, log=buf)
    _, url = serve(state, port=args.port, open_browser=not args.no_browser)
    print(f"FoE Alerting panel: {url}\n"
          "The token in that URL is what authorises the page — treat it like a password.\n"
          "Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print()
    return 0


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
    p.add_argument("--window", type=float, default=30.0,
                   help="batch window in minutes for the sample message")
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
    p.add_argument("--map-data", default="",
                   help="bootstrap labels from a saved map asset instead of waiting to see "
                        "the live one (only use one you know matches this season's map)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("collect", help="forward this world's snapshots to a scheduler")
    p.add_argument("--to", required=True, help="scheduler base URL, e.g. http://1.2.3.4:8770")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--cdp", default="", help="Chrome CDP endpoint (default: the app's)")
    p.add_argument("--secret", default="", help="shared secret (default: $ALERT_RELAY_SECRET)")
    p.add_argument("--refresh-minutes", type=float, default=0.0,
                   help="reload the tab this often when nothing else refreshes GBG")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("serve", help="receive snapshots, decide, and post to the group")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--host", default="0.0.0.0", help="bind address")
    p.add_argument("--secret", default="", help="shared secret (default: $ALERT_RELAY_SECRET)")
    p.add_argument("--dry-run", action="store_true", help="decide everything, send nothing")
    p.add_argument("--map-data", default="",
                   help="bootstrap labels from a saved map asset instead of waiting for a "
                        "collector to forward the live one (only use one you know matches "
                        "this season's map)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("ui", help="local control panel: format, labels, credentials, log")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--sample", default="dataset/api_samples/getBattleground.sample.json",
                   help="captured snapshot the format preview renders against")
    p.add_argument("--map-data", default="", help="map asset JSON (for the labels table)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.set_defaults(func=cmd_ui)
    return ap


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args, ap)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
