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


def test_core_never_imports_gui_or_ops():
    # core is the innermost layer: it must not reach into the operational
    # (ops) or presentation (gui) layers either.
    offenders = []
    for path in _py_files("core"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("bap.gui", "bap.ops"):
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append((path.name, forbidden))
    assert offenders == [], f"core reached into gui/ops: {offenders}"


def test_ops_only_depends_on_core():
    # ops is thin operational infrastructure over core; it must not depend on
    # app/adapters/gui (which would invert the composition direction).
    offenders = []
    for path in _py_files("ops"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("bap.app", "bap.adapters", "bap.gui"):
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append((path.name, forbidden))
    assert offenders == [], f"ops reached outward: {offenders}"


def test_adapters_never_import_gui():
    offenders = []
    for path in _py_files("adapters"):
        text = path.read_text(encoding="utf-8")
        if "import bap.gui" in text or "from bap.gui" in text:
            offenders.append(path.name)
    assert offenders == [], f"adapters must not import gui: {offenders}"


def test_adapters_app_dependency_is_limited_to_the_registry_seam():
    # Adapters are allowed exactly one inward-to-app dependency: the registry
    # assembly seam (bap.app.registries / bap.app.plugins), used by the
    # production registry factories that live beside the adapters. Any *other*
    # adapters -> app import is a layering violation and must fail here.
    allowed = {"bap.app.registries", "bap.app.plugins"}
    offenders = []
    for path in _py_files("adapters"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import bap.app") or stripped.startswith("from bap.app")):
                continue
            module = stripped.split()[1]  # `from <module> import ...` / `import <module>`
            if module not in allowed:
                offenders.append((path.name, module))
    assert offenders == [], f"adapters reached into app beyond the registry seam: {offenders}"


def test_app_never_imports_gui():
    # The GUI depends on app (composition); the reverse would couple the
    # headless runtime to PySide6.
    offenders = []
    for path in _py_files("app"):
        text = path.read_text(encoding="utf-8")
        if "import bap.gui" in text or "from bap.gui" in text:
            offenders.append(path.name)
    assert offenders == [], f"app must not import gui: {offenders}"


def test_gui_is_only_imported_lazily_outside_the_gui_package():
    # PySide6 is optional. Any non-gui module that imports gui must do so lazily
    # (inside a function), so importing the headless runtime never requires Qt.
    # cli.py is the only such module today; assert its gui import is indented.
    offenders = []
    for path in SRC.rglob("*.py"):
        if "gui" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ("import bap.gui" in line or "from bap.gui" in line) and not line.startswith((" ", "\t")):
                offenders.append((path.name, lineno))
    assert offenders == [], f"gui must be imported lazily outside gui/: {offenders}"
