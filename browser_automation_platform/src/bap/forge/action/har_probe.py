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
# Substrings in a building code that smell like the GBG entrance.
_GBG_ENTRANCE_HINTS = ("battleground", "guild_battle", "gbg", "guildbattle")


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
    """Every city entity we can find in the HAR: {code, x, y, id}. Deepest source wins."""
    found: dict = {}

    def _walk(node):
        if _looks_like_entity(node):
            code = _entity_code(node)
            x, y = _entity_xy(node)
            key = node.get("id") or (code, x, y)
            found[key] = {"code": code, "x": x, "y": y, "id": node.get("id")}
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for _url, body in _iter_game_json(har):
        _walk(body)
    return list(found.values())


def gbg_entrance_candidates(entities: list[dict]) -> list[dict]:
    out = []
    for ent in entities:
        code = str(ent.get("code") or "").lower()
        if any(h in code for h in _GBG_ENTRANCE_HINTS):
            out.append(ent)
    return out


def run(path: str, grep: str | None = None) -> int:
    try:
        with open(path, encoding="utf-8") as fh:
            har = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"Could not read HAR {path}: {exc}", flush=True)
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
    print("\n=== GBG-entrance candidates (by building code) ===", flush=True)
    if cands:
        for ent in cands:
            print(f"  ★ code={ent['code']}  grid=({ent['x']},{ent['y']})  id={ent['id']}",
                  flush=True)
        print("\nThat grid position + the live city camera transform places the entrance at\n"
              "any zoom/scroll — no pixel calibration. Next: read the camera transform live\n"
              "(same marker/arrow trick as the GBG map) and project this grid point.",
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
    args = ap.parse_args(argv)
    return run(args.har, grep=args.grep)


if __name__ == "__main__":
    sys.exit(main())
