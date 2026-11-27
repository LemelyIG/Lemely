"""DV-2 carve-out: only the admin settings router may name the market FX module.

The import-linter contract covers transitive imports from money paths. This scan
covers literal references under ``lemely/``, including dynamic imports, package
attributes, and literal string concatenation. Scripts are outside this scan.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "lemely"
ROUTER = "web/routers/admin_billing_settings.py"
EXEMPT = frozenset({ROUTER, "io/fx_reference.py"})
NAME = re.compile(r"\bfx_reference\b")


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left)
        right = _literal_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _references(source: str) -> list[int]:
    """Return lines that name the FX module in Python code or string literals."""
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            name = node.module or ""
        elif isinstance(node, ast.alias | ast.Name | ast.Attribute):
            if isinstance(node, ast.alias):
                name = node.name
            elif isinstance(node, ast.Name):
                name = node.id
            else:
                name = node.attr
        elif isinstance(node, ast.expr):
            name = _literal_string(node) or ""
        else:
            continue
        if NAME.search(name):
            lines.add(node.lineno)
    return sorted(lines)


def test_no_module_but_the_settings_router_names_the_fx_reference() -> None:
    findings: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel not in EXEMPT:
            lines = _references(path.read_text(encoding="utf-8"))
            findings.extend(f"{rel}:{line}" for line in lines)
    assert findings == []


def test_the_one_allowed_importer_exists_and_names_it() -> None:
    assert _references((PACKAGE / ROUTER).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "source",
    [
        "import lemely.io.fx_reference",
        "from lemely.io.fx_reference import get_usd_egp_reference",
        "from lemely.io import fx_reference",
        "from lemely.io import fx_reference as fx",
        "from . import fx_reference",
        "from .fx_reference import FxReference",
        "__import__('lemely.io.fx_reference')",
        "import lemely.io as io\nio.fx_reference",
        "importlib.import_module('.fx_reference', 'lemely.io')",
        "importlib.import_module(name='lemely.io.fx_reference')",
        "sys.modules['lemely.io.fx_reference']",
        "getattr(lemely.io, 'fx_reference')",
        "importlib.import_module('lemely.io.fx_' + 'reference')",
    ],
)
def test_each_reference_form_is_caught(source: str) -> None:
    assert _references(source)


def test_unrelated_imports_are_not_flagged() -> None:
    assert _references("from lemely.io import gemini\nimport lemely.io.paymob.client") == []
