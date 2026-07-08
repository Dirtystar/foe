"""Static guards for the dependency rules the composition root relies on.

These scan source text rather than runtime imports, so they catch a
violation the moment it is written, regardless of import order.
"""

from pathlib import Path

import bap

SRC = Path(bap.__file__).parent


def _py_files(package: str):
    return (SRC / package).rglob("*.py")


def test_core_never_imports_config():
    offenders = []
    for path in _py_files("core"):
        text = path.read_text(encoding="utf-8")
        if "import bap.config" in text or "from bap.config" in text:
            offenders.append(path.name)
    assert offenders == [], f"core must not import config, but these do: {offenders}"


def test_core_never_imports_app_or_config_or_adapters():
    offenders = []
    for path in _py_files("core"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("bap.app", "bap.config", "bap.adapters"):
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append((path.name, forbidden))
    assert offenders == [], f"core reached outward: {offenders}"


def test_config_never_imports_core_or_runtime():
    offenders = []
    for path in _py_files("config"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("bap.core", "bap.app", "bap.adapters"):
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append((path.name, forbidden))
    assert offenders == [], f"config must create no runtime objects: {offenders}"
