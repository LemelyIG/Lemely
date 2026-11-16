"""UD-13 guard (UD13-DV-3): billing rates live in the admin settings, never in code.

The seed module ``lemely/core/billing_defaults.py`` holds the values a fresh database starts
with. Running code reads the admin-edited rows, so only the seeding code may import the module.
This test scans every file under ``lemely/`` and fails on:

* an import of ``billing_defaults`` outside the allowlist;
* a reintroduced name of a removed hardcoded rate (``CREDIT_EXPIRY_MONTHS`` and friends);
* a call ``add_months(..., <int literal>)`` in ``lemely/db/``: a grant's expiry must come from
  ``billing_settings.credit_validity_months``.

``GRACE_PERIOD`` and ``PAYMOB_RETRIAL_DAYS`` join the forbidden names with T18 (UD13-C).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE: Final = ROOT / "lemely"
DEFAULTS_MODULE: Final = "lemely.core.billing_defaults"

#: Files (and one directory) allowed to import the seed module, as paths below ``lemely/``.
IMPORT_ALLOWLIST: Final = frozenset(
    {
        "db/billing_settings_repo.py",  # seeds the ``billing_settings`` row
        "db/usage_catalogue_repo.py",  # seeds ``credit_packs.signup_validity_days``
        # T16's fallback for a missing settings row inside its notice-days read. Drift against
        # DV-3: the follow-up is to fail closed there like ``seat_ceiling`` does, then drop this.
        "db/plan_terms_repo.py",
    }
)
MIGRATIONS_DIR: Final = "db/migrations/"

#: Names of rates that moved into admin settings. Reintroducing one means a second source of truth.
FORBIDDEN_NAMES: Final = frozenset(
    {
        "CREDIT_EXPIRY_MONTHS",
        "MAX_EXTRA_SEATS_AT_CHECKOUT",
        "TEACHER_SIGNUP_VALIDITY",
    }
)


def _is_int_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _imports_defaults(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name == DEFAULTS_MODULE for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        if node.module == DEFAULTS_MODULE:
            return True
        if node.level == 0 and node.module == "lemely.core":
            return any(alias.name == "billing_defaults" for alias in node.names)
        # A relative import never appears in this package, but would dodge the check above.
        return node.level > 0 and (node.module or "").split(".")[-1] == "billing_defaults"
    return False


def _used_names(node: ast.AST) -> list[str]:
    """Every identifier the node binds or reads: names, attributes, imports, definitions."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.alias):
        return [node.name.split(".")[-1], *([node.asname] if node.asname else [])]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    return []


def _is_add_months_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return name == "add_months"


def _literal_months(call: ast.Call) -> bool:
    if len(call.args) >= 2 and _is_int_literal(call.args[1]):
        return True
    return any(kw.arg == "months" and _is_int_literal(kw.value) for kw in call.keywords)


def violations(sources: dict[str, str]) -> list[str]:
    """Findings for ``{path below lemely/: source}``, each ``path:line: what``."""
    found: list[str] = []
    for rel, source in sorted(sources.items()):
        in_db = rel.startswith("db/")
        may_import = rel in IMPORT_ALLOWLIST or rel.startswith(MIGRATIONS_DIR)
        for node in ast.walk(ast.parse(source, filename=rel)):
            line = getattr(node, "lineno", 0)
            if _imports_defaults(node) and not may_import:
                found.append(f"{rel}:{line}: imports billing_defaults, only seeding code may")
            found.extend(
                f"{rel}:{line}: reintroduces {name}"
                for name in _used_names(node)
                if name in FORBIDDEN_NAMES
            )
            if in_db and _is_add_months_call(node):
                assert isinstance(node, ast.Call)
                if _literal_months(node):
                    found.append(f"{rel}:{line}: add_months with a literal month count")
    return found


def _package_sources() -> dict[str, str]:
    return {
        path.relative_to(PACKAGE).as_posix(): path.read_text(encoding="utf-8")
        for path in PACKAGE.rglob("*.py")
    }


def test_no_hardcoded_billing_rates_in_the_package() -> None:
    sources = _package_sources()
    assert len(sources) > 100  # the scan really walked the package
    assert violations(sources) == []


def test_the_allowlisted_importers_really_exist() -> None:
    # A stale allowlist entry would silently permit a future file of the same name.
    for rel in IMPORT_ALLOWLIST:
        assert (PACKAGE / rel).is_file(), rel


# -- the scanner itself goes red on each pattern it exists to catch ----------------------------


def test_a_literal_add_months_in_the_db_layer_is_flagged() -> None:
    bad = {"db/x.py": "def f(now):\n    return add_months(now, 12)\n"}
    assert violations(bad) == ["db/x.py:2: add_months with a literal month count"]
    keyword = {"db/x.py": "def f(now):\n    return billing_repo.add_months(now, months=6)\n"}
    assert len(violations(keyword)) == 1


def test_add_months_with_a_setting_or_outside_the_db_layer_is_not_flagged() -> None:
    ok_db = {"db/x.py": "def f(now, months):\n    return add_months(now, months)\n"}
    assert violations(ok_db) == []
    # The month arithmetic helper itself is tested with literals elsewhere; only db/ is guarded.
    assert violations({"core/x.py": "x = add_months(now, 12)\n"}) == []


def test_an_import_of_the_seed_module_outside_the_allowlist_is_flagged() -> None:
    forms = (
        "from lemely.core.billing_defaults import GRACE_DAYS\n",
        "from lemely.core import billing_defaults\n",
        "import lemely.core.billing_defaults\n",
        "from .billing_defaults import GRACE_DAYS\n",
    )
    for source in forms:
        assert len(violations({"db/billing_repo.py": source})) == 1, source
        assert violations({"db/billing_settings_repo.py": source}) == [], source
        assert violations({"db/migrations/versions/0099_x.py": source}) == [], source


def test_a_removed_rate_name_is_flagged_however_it_comes_back() -> None:
    forms = (
        "CREDIT_EXPIRY_MONTHS = 12\n",
        "MAX_EXTRA_SEATS_AT_CHECKOUT: int = 200\n",
        "from x import TEACHER_SIGNUP_VALIDITY\n",
        "def f():\n    return rules.MAX_EXTRA_SEATS_AT_CHECKOUT\n",
    )
    for source in forms:
        assert violations({"core/x.py": source}), source
