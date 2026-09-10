from bap.forge.config import CANVAS_BINDING, FORGE_RULE_PACK, build_forge_config
from bap.forge.worlds import World


def _w(alias, host, **kw):
    return World(alias=alias, hostname=host, **kw)


def test_builds_one_full_page_session_per_world():
    cfg = build_forge_config([
        _w("Main", "cz8.forgeofempires.com", interval_ms=1500),
        _w("Farm", "cz1.forgeofempires.com", interval_ms=800),
    ])

    assert cfg.settings.attended is True
    assert [p.id for p in cfg.profiles] == ["Main", "Farm"]

    main = cfg.profiles[0]
    assert main.session.interval_ms == 1500
    assert main.viewport.width == 1920 and main.viewport.height == 1080

    binding = main.capture_bindings[0]
    assert binding.name == CANVAS_BINDING
    assert binding.target == "full_page"
    assert binding.selector is None  # never a DOM selector — canvas game
    assert binding.analyzers == []   # no detector wired yet


def test_no_selector_anywhere_in_forge_config():
    cfg = build_forge_config([_w("Main", "cz8.forgeofempires.com")])
    for profile in cfg.profiles:
        for binding in profile.capture_bindings:
            assert binding.target == "full_page"
            assert binding.selector is None


def test_max_sessions_grows_to_fit_worlds():
    worlds = [_w(f"w{i}", f"cz{i}.forgeofempires.com") for i in range(1, 7)]
    cfg = build_forge_config(worlds, max_sessions=4)
    assert cfg.settings.max_sessions >= 6


def test_rule_pack_is_referenced_and_empty():
    cfg = build_forge_config([_w("Main", "cz8.forgeofempires.com")])
    assert FORGE_RULE_PACK in cfg.rule_packs
    assert cfg.rule_packs[FORGE_RULE_PACK] == []
    assert cfg.profiles[0].rule_pack == FORGE_RULE_PACK


def test_empty_worlds_still_valid_config():
    cfg = build_forge_config([])
    assert cfg.profiles == []
    assert cfg.settings.max_sessions >= 1
