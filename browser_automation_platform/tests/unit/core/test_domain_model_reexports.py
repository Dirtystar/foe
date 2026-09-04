"""Pin the backward-compatibility contract of bap.core.ports.browser_port.

Shared domain models were relocated to bap.core.domain.models; browser_port
re-exports them so existing consumers keep working. These tests fail if a
future cleanup removes the re-exports or forks the types.
"""

import bap.core.domain.models as domain_models
import bap.core.ports.browser_port as browser_port

RELOCATED_NAMES = ["TabHandle", "TabId", "TabProfile", "ViewportSize"]


def test_relocated_models_are_importable_from_browser_port():
    for name in RELOCATED_NAMES:
        assert hasattr(browser_port, name), f"browser_port no longer exports {name}"


def test_reexports_are_the_same_objects_not_copies():
    for name in RELOCATED_NAMES:
        assert getattr(browser_port, name) is getattr(domain_models, name), (
            f"browser_port.{name} is not the same object as domain_models.{name}; "
            "isinstance checks across the two import paths would break"
        )


def test_relocated_names_are_declared_public_in_browser_port():
    for name in RELOCATED_NAMES:
        assert name in browser_port.__all__


def test_legacy_import_style_still_constructs():
    from bap.core.ports.browser_port import TabHandle, TabProfile, ViewportSize

    profile = TabProfile(id="tab1", viewport=ViewportSize(width=800, height=600))
    handle = TabHandle(tab_id=profile.id, native=None)

    assert isinstance(profile, domain_models.TabProfile)
    assert isinstance(handle, domain_models.TabHandle)
