"""DV-2 carve-out guard (P08-T21): the market FX hint never reaches a money calculation.

``lemely.io.fx_reference`` is display only (UD-13: admins set every rate). Only the admin settings
router may import it. Every other module under ``lemely/``, billing calculation paths included
(``core/usage_pricing``, the db repos, the subscription and refund code), fails this test if it
imports the module in any form: ``import``, ``from``, ``from lemely.io import fx_reference``,
``importlib.import_module("...")``, ``__import__("...")`` or an attribute path.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE: Final = ROOT / "lemely"
MODULE: Final = "lemely.io.fx_reference"
#: Paths below ``lemely/`` allowed to import it: the read-only hint on the settings GET.
ALLOWED: Final = frozenset({"web/routers/admin_billing_settings.py"})
OWN_FILE: Final = "io/fx_reference.py"


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _string_arg(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def importers(source: str) -> list[str]:
    """What in ``source`` pulls in ``lemely.io.fx_reference``, one line each."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if a.name == MODULE]
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            if node.module == MODULE:
                found.append(f"from {base} import ...")
            elif node.module == "lemely.io" and any(a.name == "fx_reference" for a in node.names):
                found.append("from lemely.io import fx_reference")
            elif node.level and (node.module or "").endswith("fx_reference"):
                found.append(f"from {base} import ...")
            elif node.level and any(a.name == "fx_reference" for a in node.names):
                found.append(f"from {base} import fx_reference")
        elif isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee.endswith(("import_module", "__import__")) and _string_arg(node) == MODULE:
                found.append(f"{callee}({MODULE!r})")
        elif isinstance(node, ast.Attribute) and _dotted(node) == MODULE:
            found.append(f"attribute path {MODULE}")
    return found


def _package_findings() -> list[str]:
    out: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel in ALLOWED or rel == OWN_FILE:
            continue
        out += [f"{rel}: {hit}" for hit in importers(path.read_text(encoding="utf-8"))]
    return out


def test_no_module_but_the_settings_router_imports_the_fx_reference() -> None:
    assert _package_findings() == []


def test_the_one_allowed_importer_exists_and_imports_it() -> None:
    (rel,) = ALLOWED
    assert importers((PACKAGE / rel).read_text(encoding="utf-8"))


def test_every_import_form_is_caught() -> None:
    forms = [
        "import lemely.io.fx_reference",
        "from lemely.io.fx_reference import get_usd_egp_reference",
        "from lemely.io import fx_reference",
        "from lemely.io import fx_reference as fx",
        "from . import fx_reference",
        "from .fx_reference import FxReference",
        "import importlib\nimportlib.import_module('lemely.io.fx_reference')",
        "__import__('lemely.io.fx_reference')",
        "import lemely\nx = lemely.io.fx_reference.get_usd_egp_reference()",
    ]
    for source in forms:
        assert importers(source), source


def test_unrelated_imports_are_not_flagged() -> None:
    assert importers("from lemely.io import gemini\nimport lemely.io.paymob.client") == []
