"""Live GBG data reader — watch the running game's ``/game/json`` responses and keep a
fresh ranked-target view, read-only.

Two layers, cleanly separated so the logic is testable without a browser:

- :class:`LiveGbgReader` — transport-agnostic core. You ``feed()`` it raw ``/game/json``
  response bodies (str / dict / list) as they arrive; it keeps the latest
  :class:`~bap.forge.gbg_data.model.Battleground` snapshot and exposes ``targets()``.
  A body that carries no battleground (most ``/game/json`` calls don't) is ignored and the
  last good snapshot is kept. Fully unit-tested.

- :func:`run_live` / :func:`main` — the thin Playwright wiring that connects to your already
  running Chrome over CDP (``connect_over_cdp``), listens for ``/game/json`` responses, and
  feeds the reader. Passive: it never sends game requests and never clicks. (This layer
  needs a real browser to exercise; the reader core does not.)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from bap.forge.gbg_data.advisor import TargetSuggestion, rank_targets
from bap.forge.gbg_data.model import Battleground, PlayerState
from bap.forge.gbg_data.parser import parse, parse_player_from_game_json

logger = logging.getLogger("bap.forge.gbg_data.live")

_GAME_JSON = "/game/json"


class LiveGbgReader:
    """Holds the latest battleground snapshot plus the freshest player attrition.

    Attrition updates two ways: a full ``getBattleground`` (on GBG open) and a partial
    ``getPlayerParticipant`` (bundled in every battle response, so it climbs live while you
    fight). ``attrition_level`` returns whichever is newest."""

    def __init__(self) -> None:
        self._bg: Battleground | None = None
        self._player: PlayerState | None = None
        self._updates = 0

    @property
    def snapshot(self) -> Battleground | None:
        return self._bg

    @property
    def update_count(self) -> int:
        return self._updates

    @property
    def attrition_level(self) -> int | None:
        if self._player is not None and self._player.attrition_level is not None:
            return self._player.attrition_level
        if self._bg is not None and self._bg.player is not None:
            return self._bg.player.attrition_level
        return None

    def feed(self, body) -> bool:
        """Parse a ``/game/json`` response body. A full battleground replaces the snapshot;
        a bare ``getPlayerParticipant`` (during battles) updates just the attrition. Returns
        True when anything was updated. Never raises."""
        try:
            obj = json.loads(body) if isinstance(body, (str, bytes, bytearray)) else body
        except Exception:
            return False
        observed = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        updated = False
        bg = parse(obj, observed_at=observed)
        if bg is not None:
            self._bg = bg
            if bg.player is not None:
                self._player = bg.player
            updated = True
        player = parse_player_from_game_json(obj)
        if player is not None and player.attrition_level is not None:
            self._player = player
            updated = True
        if updated:
            self._updates += 1
        return updated

    def targets(self, **kw) -> list[TargetSuggestion]:
        if self._bg is None:
            return []
        return rank_targets(self._bg, **kw)


def _looks_like_game_json(url: str) -> bool:
    return _GAME_JSON in url


def make_response_handler(reader: LiveGbgReader, on_update=None):
    """Build the ``response`` event handler: filter to ``/game/json``, read the body, feed
    the reader, and call ``on_update(reader)`` on a real snapshot update. Never raises — a
    body it can't read is skipped. Extracted so it can be tested without a browser."""
    def _handle(resp) -> None:
        try:
            if not _looks_like_game_json(getattr(resp, "url", "")):
                return
            body = resp.text()
        except BaseException:
            # includes asyncio.CancelledError (a BaseException) raised when the
            # connection tears down mid-read — best-effort telemetry, swallow it.
            return
        if reader.feed(body) and on_update is not None:
            on_update(reader)
    return _handle


def render(reader: LiveGbgReader, *, limit: int = 10, include_locked: bool = False) -> str:
    """A compact text view of the current snapshot + ranked targets (for the CLI)."""
    bg = reader.snapshot
    if bg is None:
        return "waiting for GBG data… (open/refresh Guild Battlegrounds in the game)"
    me = bg.participants.get(bg.player.participant_id)
    lines = [
        f"[{bg.observed_at}]  {bg.map_id}   "
        f"you: {me.clan_name if me else bg.player.participant_id} "
        f"({me.colour if me else '?'})  attrition {bg.player.attrition_level}",
    ]
    targets = reader.targets(include_locked=include_locked)
    if not targets:
        lines.append("  no open attack targets right now")
    for i, t in enumerate(targets[:limit], 1):
        flags = ("  siege" if t.under_siege else "") + ("  locked" if t.locked else "")
        lines.append(f"  {i:2}. province {t.province_id:<3} "
                     f"attrition {str(t.gain_attrition_chance)+'%':<5} "
                     f"owner {t.owner_colour or '?':<7} {t.building_fraction or '-'}{flags}")
    return "\n".join(lines)


def run_live(endpoint: str, *, connect=None, on_update=None,
             include_locked: bool = False) -> int:  # pragma: no cover - needs a live browser
    """Connect to Chrome at ``endpoint`` (e.g. ``http://localhost:9222``), watch every
    ``/game/json`` response, and feed a :class:`LiveGbgReader`. Calls ``on_update(reader)``
    whenever a battleground snapshot arrives (defaults to printing the ranked view).

    ``connect`` is injectable for testing; by default it uses Playwright's sync
    ``connect_over_cdp``. Blocks until interrupted (Ctrl-C). Read-only throughout.
    """
    reader = LiveGbgReader()

    def _default_on_update(r: LiveGbgReader) -> None:
        print("\033[2J\033[H" + render(r, include_locked=include_locked), flush=True)

    on_update = on_update or _default_on_update
    _handle_response = make_response_handler(reader, on_update)

    if connect is None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint)
            _attach(browser, _handle_response)
            print(f"Connected to {endpoint}. Watching /game/json … (Ctrl-C to stop)\n"
                  "Open or refresh Guild Battlegrounds in the game to see data.", flush=True)
            _pump(browser)
        return 0
    # Injected connect (tests / alternative transport)
    browser = connect(endpoint)
    _attach(browser, _handle_response)
    _pump(browser)
    return 0


def _attach(browser, handler) -> None:  # pragma: no cover - thin glue
    # Listen at the context level so every page (current and future) is covered.
    for ctx in browser.contexts:
        ctx.on("response", handler)
    browser.on("disconnected", lambda: None)


def _pump(browser) -> None:  # pragma: no cover - blocking event loop
    # Keep the sync event loop alive so response events keep arriving.
    page = None
    for ctx in browser.contexts:
        if ctx.pages:
            page = ctx.pages[0]
            break
    try:
        while True:
            if page is not None:
                page.wait_for_timeout(1000)
            else:
                import time
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped.", flush=True)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    ap = argparse.ArgumentParser(
        prog="bap-forge-gbg-live",
        description="Live GBG target advisor — watch the running game's /game/json.")
    from bap.forge.browser_settings import DEFAULT_CDP_ENDPOINT

    ap.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT,
                    help="Chrome CDP endpoint (same as the app; Chrome must run with "
                         "--remote-debugging-port)")
    ap.add_argument("--include-locked", action="store_true",
                    help="also show locked provinces (planning ahead)")
    args = ap.parse_args(argv)
    try:
        return run_live(args.cdp, include_locked=args.include_locked)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not connect to Chrome at {args.cdp}: {exc}\n"
              "Start Chrome with --remote-debugging-port=9222 and open Forge first.")
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
