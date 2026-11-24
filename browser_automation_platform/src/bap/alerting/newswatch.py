"""Watch InnoGames support/KB pages (events, announcements) for new entries and post them.

Unrelated to GBG or the reminders — same WhatsApp chat, same notifier, but the trigger is
"a new article appeared on the page" rather than a schedule. Pages aren't necessarily listed
chronologically (confirmed live on the events page), so instead of trusting order this diffs
the set of article ids against what was posted before: anything with an id we haven't seen is
new, regardless of where it sits in the list.

Parsing is regex-based, not a full HTML parser — the structure is a flat, repeating
``<a href="/kb/.../<id>/<slug>"><span>Title</span>`` list (confirmed against the live pages),
simple enough that stdlib ``re`` is less code than bringing in an HTML parser for it. If
InnoGames changes the markup, :func:`fetch_list` just returns nothing new rather than raising
— a silent miss is safer than a crash that stops the reminders in the same workflow run.

A short excerpt for each new article comes from its own page's ``og:description`` meta tag
(every article has one; it's already a clean plain-text sentence, no markdown to strip).
Translation to Czech is best-effort via MyMemory's free, keyless API — if that fails for any
reason, the original English text is sent rather than dropping the message.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://support.innogames.com"

#: Both watched pages are explicitly titled "BETA Events" / "Beta Announcements" — this is
#: BETA content, not a live-server announcement, so every posted message says so rather than
#: implying the change is live now.
BETA_DISCLAIMER = "⚠️ Z BETA serveru — na live to dorazí až s odstupem a může se lišit."

_ENTRY_RE = re.compile(
    r'href="(?P<href>/kb/[^"]+/(?P<id>\d+)/[^"]+)"[^>]*>\s*<span>(?P<title>[^<]+)</span>',
    re.S)
_OG_DESC_TAG_RE = re.compile(r'<meta[^>]*property="og:description"[^>]*>')
_CONTENT_RE = re.compile(r'content="([^"]*)"')


@dataclass(frozen=True)
class NewsItem:
    id: str
    title: str
    url: str


def _get(url: str, *, opener=None, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_list(url: str, *, opener=None) -> list[NewsItem]:
    """Every article entry on a KB listing page, in document order (not necessarily
    chronological — callers should diff ids, not trust position)."""
    try:
        body = _get(url, opener=opener)
    except Exception:                                   # noqa: BLE001
        return []
    out: list[NewsItem] = []
    seen_ids: set[str] = set()
    for m in _ENTRY_RE.finditer(body):
        aid = m.group("id")
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        out.append(NewsItem(id=aid, title=html.unescape(m.group("title")).strip(),
                            url=BASE_URL + m.group("href")))
    return out


def fetch_perex(article_url: str, *, opener=None) -> str:
    """The article's own short description, or ``""`` if it can't be fetched/found."""
    try:
        body = _get(article_url, opener=opener)
    except Exception:                                    # noqa: BLE001
        return ""
    tag = _OG_DESC_TAG_RE.search(body)
    if not tag:
        return ""
    c = _CONTENT_RE.search(tag.group(0))
    return html.unescape(c.group(1)).strip() if c else ""


def translate_to_czech(text: str, *, opener=None) -> str:
    """Best-effort machine translation (MyMemory's free API). Falls back to the original
    text on any failure — a mistranslated message is better than a dropped one, and an
    untranslated one is better still than none."""
    if not text:
        return text
    try:
        q = urllib.parse.quote(text[:490])     # MyMemory's free tier caps request length
        url = f"https://api.mymemory.translated.net/get?q={q}&langpair=en|cs"
        body = _get(url, opener=opener, timeout=15.0)
        translated = json.loads(body)["responseData"]["translatedText"]
        return html.unescape(translated) if translated else text
    except Exception:                                      # noqa: BLE001
        return text


class NewsState:
    """Which article ids have already been posted for each watched page."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._seen: dict[str, list[str]] = {}
        if self._path.is_file():
            try:
                self._seen = json.loads(self._path.read_text(encoding="utf-8")).get("seen", {})
            except (json.JSONDecodeError, OSError):
                self._seen = {}

    def seen_ids(self, page_key: str) -> set[str] | None:
        """``None`` means this page has never been checked before — the caller should seed
        it silently instead of treating every current article as "new"."""
        ids = self._seen.get(page_key)
        return set(ids) if ids is not None else None

    def set_seen(self, page_key: str, ids) -> None:
        self._seen[page_key] = sorted(set(ids))
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps({"seen": self._seen}, indent=1), encoding="utf-8")
        tmp.replace(self._path)


def load_pages(path: str) -> list[dict]:
    """Read ``{"pages": [{"key", "url"}, ...]}`` — a missing file means nothing configured."""
    p = Path(path)
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("pages") or []


def check_page(page_key: str, url: str, state: NewsState, notifier, *,
               opener=None) -> list[NewsItem]:
    """Fetch one page, post anything new, and return what was posted (empty on the very
    first check of a page — that run only seeds the "already seen" set)."""
    items = fetch_list(url, opener=opener)
    if not items:
        return []
    seen = state.seen_ids(page_key)
    if seen is None:
        state.set_seen(page_key, [i.id for i in items])
        return []
    new_items = [i for i in items if i.id not in seen]
    for item in new_items:
        perex = fetch_perex(item.url, opener=opener)
        title_cs = translate_to_czech(item.title, opener=opener)
        text = f"📰 {title_cs}"
        if perex:
            text += f"\n{translate_to_czech(perex, opener=opener)}"
        text += f"\n{item.url}\n{BETA_DISCLAIMER}"
        notifier.send(text)
    state.set_seen(page_key, [i.id for i in items])
    return new_items


__all__ = ["BASE_URL", "BETA_DISCLAIMER", "NewsItem", "NewsState", "fetch_list", "fetch_perex",
           "translate_to_czech", "load_pages", "check_page"]
