"""Mine a browser HAR for the data-driven way into GBG — no canvas pixel needed.

The idea (the user's): every city building has a backend identity, so instead of
clicking a *pixel* on the WebGL city we should learn the building from **data**. A HAR
recorded while you log in and click the GBG entrance carries exactly that — you just have
to read it out of the ``/game/json`` traffic. This tool does the reading.

Clicking a canvas building is hit-tested **in the browser**, so the click's screen
coordinate is never on the wire. What *is* on the wire, and what this extracts, are the two
things that actually let us skip the pixel:

1. **The entrance's request fingerprint** — the ordered list of ``requestClass.method``
   calls the click fires (chiefly ``GuildBattlegroundService.getBattleground``). That both
   confirms entry and is the call we may be able to invoke directly (no click at all).
2. **The city map** — the startup/city payload lists every city entity with its **grid
   position** (x, y) and its **cityentity_id / building code**. The GBG entrance is one of
   those entities; from its grid coords + the live city camera we can place it at any zoom
   or scroll, deterministically.

Usage::

    python -m bap.forge.action.har_probe path/to/foe.har
    python -m bap.forge.action.har_probe foe.har --grep battleground   # filter the fingerprint

Pure stdlib, read-only, no browser. How to record the HAR: open DevTools → Network,
tick "Preserve log", reload the world, click the GBG entrance, then right-click the
request list → "Save all as HAR".
"""

from __future__ import annotations

import json
import sys
from collections import Counter

# City-entity keys that, if present in a response item, mark it as the city map.
_CITY_HINT_KEYS = ("cityentity_id", "cityEntityId", "city_entity_id")
# The entrance PORTAL reads as "battleground" but NOT "gbg" — the "gbg" codes are the season
# **prize buildings** you won and placed (W_MultiAge_GBG25C2 …), normal grid, normal ids. The
# portal is a virtual entity: "battleground" in its code, a system id (>= _SYSTEM_ID_MIN), and
# often an off-grid (negative) coord. Confirmed real code: V_IronAge_BattlegroundDiamond.
_ENTRANCE_HINTS = ("battleground", "guild_battle", "guildbattle")
_PRIZE_HINT = "gbg"
_SYSTEM_ID_MIN = 2_000_000_000


def _iter_game_json(har: dict):
    """Yield (url, parsed_response_body) for every /game/json entry with a JSON body."""
    for e in (har.get("log", {}) or {}).get("entries", []) or []:
        url = (e.get("request", {}) or {}).get("url", "") or ""
        if "/game/json" not in url:
            continue
        text = ((e.get("response", {}) or {}).get("content", {}) or {}).get("text")
        if not text:
            continue
        try:
            yield url, json.loads(text)
        except (ValueError, TypeError):
            continue


def _server_items(body):
    """A /game/json response body is normally a list of ServerResponse dicts. Normalise."""
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        return [body]
    return []


# Keys that would carry a leader's sector mark (Cíl / Stop / strategy) — the marks are native
# game data, readable by any guild member, so they must ride on some /game/json field.
_MARK_KEY = __import__("re").compile(
    r"strateg|priorit|\btarget|ignore|focus|\bstop|annotat|\bnote|sector|\bhand|\bmark", __import__("re").I)


def scan_marks(har: dict) -> None:
    """Find where the leader's Stop/Cíl marks live: list every GuildBattleground* call, and print
    any object anywhere in /game/json whose keys look like a sector mark/strategy."""
    calls = {}
    hits = []
    seen = set()

    def _walk(node, path):
        if isinstance(node, dict):
            if any(_MARK_KEY.search(k) for k in node.keys()):
                sig = tuple(sorted(node.keys()))
                if sig not in seen:
                    seen.add(sig)
                    hits.append((path, node))
            for k, v in node.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node[:3]:               # a few items is enough to see the shape
                _walk(v, path + "[]")

    for _url, body in _iter_game_json(har):
        for it in _server_items(body):
            rc = it.get("requestClass") or ""
            rm = it.get("requestMethod") or ""
            if "battleground" in str(rc).lower():
                calls[f"{rc}.{rm}"] = calls.get(f"{rc}.{rm}", 0) + 1
            _walk(it.get("responseData", it), rc or "?")

    print("=== GuildBattleground* calls seen ===", flush=True)
    for k, n in sorted(calls.items()):
        print(f"  {n:3}x  {k}", flush=True)
    print(f"\n=== objects with mark/strategy-like keys: {len(hits)} ===", flush=True)
    for path, obj in hits[:25]:
        keys = ", ".join(list(obj.keys())[:12])
        print(f"  [{path}]  keys: {keys}", flush=True)
        print("    " + json.dumps(obj, ensure_ascii=False)[:300], flush=True)
    if not hits:
        print("  none — the marks may only appear when set. Record the HAR on a map the leader has "
              "marked (open GBG, and open the guild strategy/marks panel if there is one).",
              flush=True)


def method_fingerprint(har: dict) -> list[tuple[str, str]]:
    """Ordered (requestClass, requestMethod) across every /game/json response item.

    This is the click's signature: replaying the browser flow, the entrance click shows up
    as its own short burst of calls (getBattleground and friends) near the end.
    """
    seq: list[tuple[str, str]] = []
    for _url, body in _iter_game_json(har):
        for it in _server_items(body):
            rc = it.get("requestClass") or it.get("__class__") or "?"
            rm = it.get("requestMethod") or it.get("method") or ""
            seq.append((str(rc), str(rm)))
    return seq


def _looks_like_entity(d) -> bool:
    return isinstance(d, dict) and any(k in d for k in _CITY_HINT_KEYS)


def _entity_code(d: dict):
    return d.get("cityentity_id") or d.get("cityEntityId") or d.get("city_entity_id")


def _entity_xy(d: dict):
    x = d.get("x")
    y = d.get("y")
    if x is None or y is None:
        coords = d.get("coordinates") or d.get("position") or {}
        if isinstance(coords, dict):
            x, y = coords.get("x"), coords.get("y")
    return x, y


def find_city_entities(har: dict) -> list[dict]:
    """Every city entity we can find: {code, x, y, id, raw}. Deepest source wins (``raw`` is
    the full entity dict, kept for --dump-id)."""
    found: dict = {}

    def _walk(node):
        if _looks_like_entity(node):
            code = _entity_code(node)
            x, y = _entity_xy(node)
            key = node.get("id") or (code, x, y)
            found[key] = {"code": code, "x": x, "y": y, "id": node.get("id"), "raw": node}
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for _url, body in _iter_game_json(har):
        _walk(body)
    return list(found.values())


def _is_system_id(v) -> bool:
    try:
        return int(v) >= _SYSTEM_ID_MIN
    except (TypeError, ValueError):
        return False


def gbg_entrance_candidates(entities: list[dict]) -> list[dict]:
    """The entry portal(s): code says 'battleground' (not a 'gbg' prize building). Sorted so
    the strongest signal — system id and/or off-grid coord — comes first."""
    out = []
    for ent in entities:
        code = str(ent.get("code") or "").lower()
        if _PRIZE_HINT in code:
            continue  # a placed GBG-season prize building, not the entrance
        if not any(h in code for h in _ENTRANCE_HINTS):
            continue
        x, y = ent.get("x"), ent.get("y")
        off_grid = (isinstance(x, int) and x < 0) or (isinstance(y, int) and y < 0)
        ent = {**ent, "system_id": _is_system_id(ent.get("id")), "off_grid": off_grid}
        out.append(ent)
    out.sort(key=lambda e: (not e["system_id"], not e["off_grid"]))
    return out


def run(path: str, grep: str | None = None, dump_id=None, marks=False) -> int:
    try:
        with open(path, encoding="utf-8") as fh:
            har = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"Could not read HAR {path}: {exc}", flush=True)
        return 1

    if marks:
        scan_marks(har)
        return 0

    if dump_id is not None:
        want = str(dump_id)
        for ent in find_city_entities(har):
            if str(ent.get("id")) == want:
                print(json.dumps(ent["raw"], indent=2, ensure_ascii=False), flush=True)
                return 0
        print(f"No city entity with id {dump_id} in this HAR.", flush=True)
        return 1

    seq = method_fingerprint(har)
    if not seq:
        print("No /game/json responses in this HAR. Record with DevTools → Network → "
              "'Preserve log', reload the world, click the GBG entrance, Save all as HAR.",
              flush=True)
        return 1

    print(f"=== /game/json call fingerprint ({len(seq)} calls) ===", flush=True)
    g = (grep or "").lower()
    for i, (rc, rm) in enumerate(seq):
        label = f"{rc}.{rm}" if rm else rc
        if g and g not in label.lower():
            continue
        print(f"  [{i:3}] {label}", flush=True)

    counts = Counter(f"{rc}.{rm}" if rm else rc for rc, rm in seq)
    print("\n=== call counts (most common) ===", flush=True)
    for label, n in counts.most_common(15):
        print(f"  {n:3}x  {label}", flush=True)

    entities = find_city_entities(har)
    print(f"\n=== city entities with grid coords: {len(entities)} ===", flush=True)
    if entities:
        for ent in entities[:8]:
            print(f"  code={ent['code']}  grid=({ent['x']},{ent['y']})  id={ent['id']}",
                  flush=True)
        if len(entities) > 8:
            print(f"  … and {len(entities) - 8} more", flush=True)

    cands = gbg_entrance_candidates(entities)
    print("\n=== GBG-entrance PORTAL candidates (code=battleground, not a 'gbg' prize) ===",
          flush=True)
    if cands:
        for ent in cands:
            tags = []
            if ent["system_id"]:
                tags.append("system-id")
            if ent["off_grid"]:
                tags.append("off-grid")
            tag = ("  [" + ", ".join(tags) + "]") if tags else ""
            print(f"  ★ code={ent['code']}  grid=({ent['x']},{ent['y']})  id={ent['id']}{tag}",
                  flush=True)
        best = cands[0]
        print(f"\nBest guess: id={best['id']} ({best['code']}). Dump its full record with\n"
              f"  python -m bap.forge.action.har_probe {path!r} --dump-id {best['id']}\n"
              "Then: grid + the live city camera → screen pixel at any zoom/scroll (no hard-\n"
              "coded coord). Or better — trigger GBG entry the way the click does (the\n"
              "GuildBattlegroundService.getBattleground call at the tail of the fingerprint).",
              flush=True)
    elif entities:
        print("  none matched the name hints — paste the code list above and we'll pick the\n"
              "  entrance by elimination (it's the entity whose click fired getBattleground).",
              flush=True)
    else:
        print("  no city-entity payload in this HAR. Make sure the recording starts BEFORE\n"
              "  the world finishes loading (the city map arrives during login).", flush=True)
    return 0


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="bap-forge-har-probe",
        description="Mine a FoE HAR for the GBG entry fingerprint + the city map building codes.")
    ap.add_argument("har", help="path to a .har recorded while clicking the GBG entrance")
    ap.add_argument("--grep", default=None, help="only print fingerprint lines containing this")
    ap.add_argument("--dump-id", default=None, help="print the full JSON of the city entity "
                    "with this id (learn the entrance's schema)")
    ap.add_argument("--marks", action="store_true",
                    help="find the leader Stop/Cíl sector marks in the /game/json (native, no Helper)")
    args = ap.parse_args(argv)
    return run(args.har, grep=args.grep, dump_id=args.dump_id, marks=args.marks)


if __name__ == "__main__":
    sys.exit(main())
