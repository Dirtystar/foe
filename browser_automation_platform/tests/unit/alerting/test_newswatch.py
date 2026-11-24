"""InnoGames KB watcher: parsing, new-id detection, translation fallback — no real network."""

from __future__ import annotations

import io
import json

from bap.alerting.newswatch import (
    NewsState,
    check_page,
    fetch_list,
    fetch_perex,
    translate_to_czech,
)

# A trimmed-down but structurally real fragment of the live events listing page.
_LIST_HTML = """
<div class="faq-section"><h2 class="mb-1">BETA Events</h2>
<ul class="list-group list-group-flush">
    <a class="list-group-item ps-0 text-link d-flex"  href="/kb/ForgeOfEmpires/en_DK/6983/Halloween-Event-2026-Mechanics">
        <span>Halloween Event 2026: Mechanics</span>
        <i class="bi bi-chevron-right"></i>
    </a>
    <a class="list-group-item ps-0 text-link d-flex"  href="/kb/ForgeOfEmpires/en_DK/7000/Winter-Event-2026-Mechanics">
        <span>Winter Event 2026: Mechanics</span>
        <i class="bi bi-chevron-right"></i>
    </a>
</ul></div>
"""

# A trimmed article page carrying a real-shaped og:description meta tag.
_ARTICLE_HTML = """
<head>
<meta property="og:title" content="Winter Event 2026: Mechanics" />
<meta property="og:description" content="The Winter Event returns with new mechanics." />
</head>
"""


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeHtmlOpener:
    """Maps URL -> raw text/bytes the "server" answers with."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.urls_requested: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls_requested.append(url)
        if url not in self.pages:
            raise OSError(f"no fake page for {url}")
        return _Response(self.pages[url].encode("utf-8"))


def test_fetch_list_parses_entries_and_dedupes():
    opener = FakeHtmlOpener({"https://x.test/list": _LIST_HTML})
    items = fetch_list("https://x.test/list", opener=opener)
    assert [(i.id, i.title) for i in items] == [
        ("6983", "Halloween Event 2026: Mechanics"),
        ("7000", "Winter Event 2026: Mechanics"),
    ]
    assert items[0].url == ("https://support.innogames.com"
                            "/kb/ForgeOfEmpires/en_DK/6983/Halloween-Event-2026-Mechanics")


def test_fetch_list_on_unreachable_page_returns_empty_not_raises():
    opener = FakeHtmlOpener({})
    assert fetch_list("https://x.test/missing", opener=opener) == []


def test_fetch_perex_reads_og_description():
    opener = FakeHtmlOpener({"https://x.test/a": _ARTICLE_HTML})
    assert fetch_perex("https://x.test/a", opener=opener) == (
        "The Winter Event returns with new mechanics.")


def test_fetch_perex_missing_tag_returns_empty():
    opener = FakeHtmlOpener({"https://x.test/a": "<head></head>"})
    assert fetch_perex("https://x.test/a", opener=opener) == ""


def test_translate_uses_mymemory_and_falls_back_on_failure():
    def good(req, timeout=None):
        return _Response(
            json.dumps({"responseData": {"translatedText": "Zimní událost"}}).encode())
    assert translate_to_czech("Winter Event", opener=good) == "Zimní událost"

    def boom(req, timeout=None):
        raise OSError("no network")
    assert translate_to_czech("Winter Event", opener=boom) == "Winter Event"


def test_translate_empty_text_is_a_noop():
    assert translate_to_czech("", opener=lambda *a, **k: 1 / 0) == ""


def test_check_page_seeds_silently_on_first_run(tmp_path):
    opener = FakeHtmlOpener({"https://x.test/list": _LIST_HTML})
    state = NewsState(str(tmp_path / "state.json"))

    class RecordingNotifier:
        def __init__(self):
            self.sent = []

        def send(self, text):
            self.sent.append(text)
            return True

    notifier = RecordingNotifier()
    new_items = check_page("events", "https://x.test/list", state, notifier, opener=opener)
    assert new_items == []
    assert notifier.sent == []
    assert state.seen_ids("events") == {"6983", "7000"}


def test_check_page_posts_only_genuinely_new_ids(tmp_path, monkeypatch):
    state = NewsState(str(tmp_path / "state.json"))
    state.set_seen("events", ["6983"])          # pretend we'd already seen the Halloween one

    opener = FakeHtmlOpener({
        "https://x.test/list": _LIST_HTML,
        "https://support.innogames.com/kb/ForgeOfEmpires/en_DK/7000/Winter-Event-2026-Mechanics":
            _ARTICLE_HTML,
    })
    # Skip real translation calls — not the point of this test, and no network here.
    monkeypatch.setattr("bap.alerting.newswatch.translate_to_czech", lambda text, **k: text)

    class RecordingNotifier:
        def __init__(self):
            self.sent = []

        def send(self, text):
            self.sent.append(text)
            return True

    notifier = RecordingNotifier()
    new_items = check_page("events", "https://x.test/list", state, notifier, opener=opener)
    assert [i.id for i in new_items] == ["7000"]
    assert len(notifier.sent) == 1
    assert "Winter Event 2026: Mechanics" in notifier.sent[0]
    assert "The Winter Event returns with new mechanics." in notifier.sent[0]
    assert state.seen_ids("events") == {"6983", "7000"}


def test_news_state_survives_a_restart(tmp_path):
    path = str(tmp_path / "state.json")
    NewsState(path).set_seen("news", ["1", "2"])
    assert NewsState(path).seen_ids("news") == {"1", "2"}
    assert NewsState(path).seen_ids("other-page") is None
