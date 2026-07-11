import json

import pytest

from bap.core.domain.models import BrowserTab
from bap.forge.worlds import (
    BADGE_PCTS,
    World,
    WorldError,
    WorldStore,
    is_forge_hostname,
    normalize_hostname,
)


# --- hostname identity --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://cz8.forgeofempires.com/game/index?ref=x", "cz8.forgeofempires.com"),
        ("cz8.forgeofempires.com", "cz8.forgeofempires.com"),
        ("HTTPS://CZ2.ForgeOfEmpires.com/", "cz2.forgeofempires.com"),
        ("", ""),
        ("not a url", ""),
    ],
)
def test_normalize_hostname(raw, expected):
    assert normalize_hostname(raw) == expected


def test_is_forge_hostname():
    assert is_forge_hostname("https://cz8.forgeofempires.com/game")
    assert is_forge_hostname("en12.forgeofempires.com")
    assert not is_forge_hostname("https://example.com")
    assert not is_forge_hostname("forgeofempires.com.evil.net")


# --- World validation ---------------------------------------------------------


def test_world_defaults():
    w = World(alias="Main", hostname="https://cz8.forgeofempires.com/game/index")
    assert w.alias == "Main"
    assert w.hostname == "cz8.forgeofempires.com"  # normalized from the URL
    assert w.allowed_pcts == BADGE_PCTS
    assert w.max_weakening_pct == 100
    assert w.interval_ms == 1000


def test_world_rejects_blank_alias():
    with pytest.raises(WorldError, match="alias"):
        World(alias="   ", hostname="cz8.forgeofempires.com")


def test_world_rejects_non_forge_host():
    with pytest.raises(WorldError, match="not a Forge server"):
        World(alias="X", hostname="https://example.com/game")


def test_world_rejects_bad_pcts_and_ranges():
    with pytest.raises(WorldError, match="allowed_pcts"):
        World(alias="X", hostname="cz1.forgeofempires.com", allowed_pcts=(20, 33))
    with pytest.raises(WorldError, match="max_weakening_pct"):
        World(alias="X", hostname="cz1.forgeofempires.com", max_weakening_pct=150)
    with pytest.raises(WorldError, match="interval_ms"):
        World(alias="X", hostname="cz1.forgeofempires.com", interval_ms=0)


def test_world_normalizes_pcts_order_and_dedupes():
    w = World(alias="X", hostname="cz1.forgeofempires.com", allowed_pcts=(60, 20, 20, 40))
    assert w.allowed_pcts == (20, 40, 60)


def test_with_changes_revalidates():
    w = World(alias="X", hostname="cz1.forgeofempires.com")
    w2 = w.with_changes(max_weakening_pct=60)
    assert w2.max_weakening_pct == 60
    with pytest.raises(WorldError):
        w.with_changes(hostname="example.com")


# --- store CRUD + auto-save ---------------------------------------------------


def _world(alias, host, **kw):
    return World(alias=alias, hostname=host, **kw)


def test_add_get_list_order():
    store = WorldStore()
    store.add(_world("Main", "cz8.forgeofempires.com"))
    store.add(_world("Farm", "cz1.forgeofempires.com"))
    assert store.aliases() == ["Main", "Farm"]
    assert store.get("Farm").hostname == "cz1.forgeofempires.com"
    assert len(store) == 2


def test_duplicate_alias_rejected():
    store = WorldStore()
    store.add(_world("Main", "cz8.forgeofempires.com"))
    with pytest.raises(WorldError, match="already exists"):
        store.add(_world("Main", "cz1.forgeofempires.com"))


def test_duplicate_hostname_rejected():
    store = WorldStore()
    store.add(_world("Main", "cz8.forgeofempires.com"))
    with pytest.raises(WorldError, match="already used"):
        store.add(_world("Other", "cz8.forgeofempires.com"))


def test_update_allows_rename_and_preserves_order():
    store = WorldStore()
    store.add(_world("A", "cz1.forgeofempires.com"))
    store.add(_world("B", "cz2.forgeofempires.com"))
    store.update("A", _world("Main", "cz1.forgeofempires.com", max_weakening_pct=40))
    assert store.aliases() == ["Main", "B"]  # order kept, alias renamed
    assert store.get("Main").max_weakening_pct == 40


def test_remove():
    store = WorldStore()
    store.add(_world("A", "cz1.forgeofempires.com"))
    store.remove("A")
    assert store.aliases() == []
    with pytest.raises(WorldError, match="No world"):
        store.remove("A")


# --- persistence --------------------------------------------------------------


def test_auto_save_and_reload(tmp_path):
    path = tmp_path / "forge" / "worlds.json"
    store = WorldStore.load(path)  # missing file -> empty, bound to path
    store.add(_world("Main", "cz8.forgeofempires.com", interval_ms=1500, allowed_pcts=(20, 40)))
    assert path.exists()  # add() auto-saved

    reloaded = WorldStore.load(path)
    assert reloaded.aliases() == ["Main"]
    w = reloaded.get("Main")
    assert w.interval_ms == 1500
    assert w.allowed_pcts == (20, 40)


def test_load_skips_corrupt_records(tmp_path):
    path = tmp_path / "worlds.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "worlds": [
                    {"alias": "Good", "hostname": "cz1.forgeofempires.com"},
                    {"alias": "Bad", "hostname": "example.com"},  # not a forge host
                    {"nonsense": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    store = WorldStore.load(path)
    assert store.aliases() == ["Good"]


def test_load_missing_file_is_empty(tmp_path):
    store = WorldStore.load(tmp_path / "nope.json")
    assert store.aliases() == []
    assert store.path is not None  # bound so a later add() creates it


def test_save_is_atomic_and_leaves_no_temp(tmp_path):
    path = tmp_path / "worlds.json"
    store = WorldStore.load(path)
    store.add(_world("A", "cz1.forgeofempires.com"))
    assert not path.with_suffix(".json.tmp").exists()


# --- hostname reattachment ----------------------------------------------------


def test_match_tabs_by_hostname_ignores_tab_ids():
    store = WorldStore()
    store.add(_world("Main", "cz8.forgeofempires.com"))
    store.add(_world("Farm", "cz1.forgeofempires.com"))
    # Tab ids are deliberately unrelated to any previous session's ids.
    tabs = [
        BrowserTab(tab_id="tab-99", title="cz8", url="https://cz8.forgeofempires.com/game/index"),
        BrowserTab(tab_id="tab-3", title="cz1", url="https://cz1.forgeofempires.com/game/index"),
        BrowserTab(tab_id="tab-7", title="mail", url="https://mail.google.com/"),
    ]
    matches = store.match_tabs(tabs)
    assert matches["Main"].tab_id == "tab-99"
    assert matches["Farm"].tab_id == "tab-3"
    assert set(matches) == {"Main", "Farm"}


def test_match_tabs_absent_when_no_tab_open():
    store = WorldStore()
    store.add(_world("Main", "cz8.forgeofempires.com"))
    matches = store.match_tabs([
        BrowserTab(tab_id="t1", title="other", url="https://cz2.forgeofempires.com/"),
    ])
    assert matches == {}  # cz8 not open -> user assigns manually
