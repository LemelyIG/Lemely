"""UD-13 guard (UD13-DV-3): billing rates live in the admin settings, never in code.

The seed module ``lemely/core/billing_defaults.py`` holds the values a fresh database starts
with. Running code reads the admin-edited rows, so only the seeding code may import it, and only
the names it seeds. This test scans every file under ``lemely/`` and fails on:

* an import of ``billing_defaults`` outside the allowlist (``from`` form, ``import`` form,
  ``from lemely.core import billing_defaults``, ``importlib.import_module("...")``, and an
  attribute path such as ``lemely.core.billing_defaults.X``), and an allowlisted file importing
  a name it is not listed for (the allowlist is per name, not per file);
* any module outside the seed module that binds a seed name (``MAX_EXTRA_SEATS = 200``) or the
  name of a rate that moved into settings, whatever the case (``credit_expiry_months``);
* a month count that is not read from settings in ``add_months`` (an int literal, arithmetic on
  literals, a walrus, a module constant, a constant of another module), including an alias of
  ``add_months`` and a helper named like one, anywhere under ``lemely/``;
* ``relativedelta`` with a literal ``months=`` or ``years=``;
* in ``lemely/db/``, an ``expires_at`` keyword or assignment built from ``timedelta`` with a
  literal (``now + timedelta(days=30)``); operational windows stay legal;
* a seat count compared with a literal of 50 or more (``... > 200``), and a seat-count schema
  field whose ``le=`` is a literal other than the 10 000 sanity bound.

``GRACE_PERIOD`` and ``PAYMOB_RETRIAL_DAYS`` joined the forbidden names with T18 (UD13-C): grace
and Paymob's ``retrial_days`` both come from ``billing_settings.grace_days``.

Residual risk, deliberately not chased: a bare price or limit literal that is not a month count,
a seat compare or an expiry (``9_900``, ``return 14``) cannot be told apart from pagination and
other limits without heavy noise. Those readers are covered by their fail-closed tests instead.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from lemely.core import billing_defaults

ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE: Final = ROOT / "lemely"
DEFAULTS_MODULE: Final = "lemely.core.billing_defaults"
DEFAULTS_FILE: Final = "core/billing_defaults.py"

#: Files allowed to import the seed module, mapped to the only names each may import (paths
#: below ``lemely/``). Migrations may import anything.
IMPORT_ALLOWLIST: Final = {
    "db/billing_settings_repo.py": frozenset(  # seeds the ``billing_settings`` row
        {"CREDIT_VALIDITY_MONTHS", "GRACE_DAYS", "MAX_EXTRA_SEATS", "PRICE_CHANGE_NOTICE_DAYS"}
    ),
    "db/usage_catalogue_repo.py": frozenset(  # seeds ``credit_packs.signup_validity_days``
        {"TEACHER_SIGNUP_VALIDITY_DAYS"}
    ),
}
MIGRATIONS_DIR: Final = "db/migrations/"

#: What the seed module seeds: no other module may bind one of these names.
SEED_NAMES: Final = frozenset(billing_defaults.__all__)
#: Names of rates that moved into admin settings. Reintroducing one means a second source of truth.
REMOVED_NAMES: Final = frozenset(
    {
        "CREDIT_EXPIRY_MONTHS",
        "GRACE_PERIOD",
        "MAX_EXTRA_SEATS_AT_CHECKOUT",
        "PAYMOB_RETRIAL_DAYS",
        "TEACHER_SIGNUP_VALIDITY",
    }
)
FORBIDDEN_NAMES: Final = SEED_NAMES | REMOVED_NAMES
#: Removed names also caught in lower case (``credit_expiry_months = 12``). The seed names and
#: ``GRACE_PERIOD`` are not: their lower-case forms are ordinary locals and function names.
LOWER_CASE_TOO: Final = frozenset(
    name.lower()
    for name in ("CREDIT_EXPIRY_MONTHS", "MAX_EXTRA_SEATS_AT_CHECKOUT", "TEACHER_SIGNUP_VALIDITY")
)

#: The ``le=`` bound a seat-count request schema may carry: ``billing_settings.max_extra_seats``
#: tops out here (database CHECK and settings validation), so it is a sanity bound, not a rate.
SEAT_SANITY_BOUND: Final = 10_000
#: A literal at least this large next to a seat count is a hardcoded ceiling, not arithmetic.
SEAT_LITERAL_FLOOR: Final = 50

_MONTH_HELPER: Final = re.compile(r"(add|plus|shift)_?months?", re.IGNORECASE)
_DEFAULTS_PATH: Final = re.compile(r"^[\w.]*billing_defaults$")
_TIMEDELTA_UNITS: Final = frozenset(
    {"weeks", "days", "hours", "minutes", "seconds", "milliseconds", "microseconds"}
)


def _is_int_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _is_literal_expression(node: ast.expr) -> bool:
    """An int literal, or arithmetic made only of int literals (``6 * 2``, ``-12``)."""
    if _is_int_literal(node):
        return True
    if isinstance(node, ast.UnaryOp):
        return _is_literal_expression(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_literal_expression(node.left) and _is_literal_expression(node.right)
    return False


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _docstring_ids(tree: ast.AST) -> set[int]:
    """``id`` of every docstring node, so prose that names the seed module is not flagged."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _bound_names(node: ast.AST) -> list[str]:
    """Names the node binds by assignment or definition (imports are judged separately)."""
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign | ast.AugAssign):
        return [node.target.id] if isinstance(node.target, ast.Name) else []
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    return []


def _literal_constants(tree: ast.AST) -> set[str]:
    """Names assigned an int literal (or arithmetic of literals) anywhere in the file."""
    found: set[str] = set()
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if (
            isinstance(node, ast.Assign | ast.AnnAssign)
            and isinstance(value, ast.expr)
            and _is_literal_expression(value)
        ):
            found.update(_bound_names(node))
    return found


def _add_months_aliases(tree: ast.AST) -> set[str]:
    names = {"add_months"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names if a.name == "add_months")
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name | ast.Attribute)
            and getattr(node.value, "id", getattr(node.value, "attr", "")) == "add_months"
        ):
            names.update(_bound_names(node))
    return names


def _months_argument(call: ast.Call) -> ast.expr | None:
    if len(call.args) >= 2:
        return call.args[1]
    return next((kw.value for kw in call.keywords if kw.arg == "months"), None)


def _fixed_months(arg: ast.expr, constants: set[str]) -> bool:
    """A month count fixed in code: literal arithmetic, a walrus, or a named constant."""
    if _is_literal_expression(arg) or isinstance(arg, ast.NamedExpr):
        return True
    if isinstance(arg, ast.Name):
        return arg.id in constants or arg.id.isupper()
    return isinstance(arg, ast.Attribute) and arg.attr.isupper()


def _has_literal_timedelta(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _callee_name(sub) == "timedelta":
            args = [*sub.args, *(kw.value for kw in sub.keywords if kw.arg in _TIMEDELTA_UNITS)]
            if any(_is_literal_expression(a) for a in args):
                return True
    return False


def _defaults_import_findings(node: ast.AST, allowed: frozenset[str] | None) -> list[str]:
    """What an import of the seed module breaks. ``allowed`` is the importer's name allowlist."""
    names: list[str] | None = None  # names imported from the module; None = the module itself
    hit = False
    if isinstance(node, ast.Import):
        hit = any(alias.name == DEFAULTS_MODULE for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module == DEFAULTS_MODULE or (node.level > 0 and module.endswith("billing_defaults")):
            hit, names = True, [alias.name for alias in node.names]
        elif module == "lemely.core" or (node.level > 0 and not module):
            hit = any(alias.name == "billing_defaults" for alias in node.names)
    if not hit:
        return []
    if allowed is None:
        return ["imports billing_defaults, only seeding code may"]
    if names is None or "*" in names:
        return ["imports the whole of billing_defaults, name the seeds it needs"]
    return [
        f"imports {name} from billing_defaults, not on its allowlist"
        for name in names
        if name not in allowed
    ]


def violations(sources: dict[str, str]) -> list[str]:
    """Findings for ``{path below lemely/: source}``, each ``path:line: what``."""
    found: list[str] = []
    for rel, source in sorted(sources.items()):
        tree = ast.parse(source, filename=rel)
        in_db = rel.startswith("db/")
        is_seed_module = rel == DEFAULTS_FILE
        migration = rel.startswith(MIGRATIONS_DIR)
        allowed = IMPORT_ALLOWLIST.get(rel)
        docstrings = _docstring_ids(tree)
        month_calls = _add_months_aliases(tree)
        constants = _literal_constants(tree)
        for node in ast.walk(tree):
            line = getattr(node, "lineno", 0)
            where = f"{rel}:{line}:"
            if not migration and not is_seed_module:
                found.extend(
                    f"{where} {msg}"
                    for msg in _defaults_import_findings(
                        node, allowed if allowed is not None else None
                    )
                )
                if isinstance(node, ast.Attribute) and node.attr == "billing_defaults":
                    found.append(f"{where} reaches billing_defaults by attribute path")
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and _DEFAULTS_PATH.match(node.value)
                ):
                    found.append(f"{where} names billing_defaults as a string (importlib)")
            if not is_seed_module:
                found.extend(
                    f"{where} binds {name}, a seeded or removed rate name"
                    for name in _bound_names(node)
                    if name in FORBIDDEN_NAMES or name.lower() in LOWER_CASE_TOO
                )
                if isinstance(node, ast.alias | ast.Name | ast.Attribute):
                    used = (
                        node.name.split(".")[-1]
                        if isinstance(node, ast.alias)
                        else getattr(node, "id", getattr(node, "attr", ""))
                    )
                    if used in REMOVED_NAMES:
                        found.append(f"{where} reintroduces {used}")
            found.extend(_calls_findings(node, where, in_db, month_calls, constants))
            found.extend(_seat_findings(node, where, rel.startswith("web/schemas")))
    return found


def _calls_findings(
    node: ast.AST, where: str, in_db: bool, month_calls: set[str], constants: set[str]
) -> list[str]:
    found: list[str] = []
    if isinstance(node, ast.Call):
        name = _callee_name(node)
        if name in month_calls or _MONTH_HELPER.fullmatch(name.strip("_")):
            arg = _months_argument(node)
            if arg is not None and _fixed_months(arg, constants):
                found.append(f"{where} add_months with a month count fixed in code")
        if name == "relativedelta" and any(
            _is_literal_expression(kw.value)
            for kw in node.keywords
            if kw.arg in {"months", "years"}
        ):
            found.append(f"{where} relativedelta with a literal month or year count")
        if in_db and any(
            kw.arg == "expires_at" and _has_literal_timedelta(kw.value) for kw in node.keywords
        ):
            found.append(f"{where} expires_at built from a literal timedelta")
    if in_db and isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
        value = getattr(node, "value", None)
        if (
            isinstance(value, ast.expr)
            and any(
                name == "expires_at" or name.endswith("_expires_at") for name in _target_names(node)
            )
            and _has_literal_timedelta(value)
        ):
            found.append(f"{where} expires_at built from a literal timedelta")
    return found


def _target_names(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [
        t.id if isinstance(t, ast.Name) else t.attr
        for t in targets
        if isinstance(t, ast.Name | ast.Attribute)
    ]


_NOT_A_SEAT_COUNT: Final = re.compile(r"price|minor|amount|unit|allowance|grant", re.IGNORECASE)


def _int_value(node: ast.expr) -> int | None:
    """The value of an int literal, else ``None``."""
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    return None


def _mentions_seats(node: ast.expr) -> bool:
    text = ast.unparse(node)
    return "seat" in text.lower() and _NOT_A_SEAT_COUNT.search(text) is None


def _seat_findings(node: ast.AST, where: str, in_schema: bool) -> list[str]:
    found: list[str] = []
    if isinstance(node, ast.Compare):
        sides = [node.left, *node.comparators]
        has_big_literal = any((_int_value(s) or 0) >= SEAT_LITERAL_FLOOR for s in sides)
        if has_big_literal and any(_int_value(s) is None and _mentions_seats(s) for s in sides):
            found.append(f"{where} a seat count compared with a literal ceiling")
    if in_schema and isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        value = node.value
        if (
            "seat" in node.target.id.lower()
            and isinstance(value, ast.Call)
            and _callee_name(value) == "Field"
        ):
            for kw in value.keywords:
                bound = _int_value(kw.value) if kw.arg == "le" else None
                if bound is not None and bound != SEAT_SANITY_BOUND:
                    found.append(f"{where} a seat field capped by a literal le={bound}")
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


def test_the_allowlisted_names_are_seeds() -> None:
    for rel, names in IMPORT_ALLOWLIST.items():
        assert names <= SEED_NAMES, rel


# -- the scanner itself goes red on each pattern it exists to catch ----------------------------


def _flags(source: str, rel: str = "db/x.py") -> list[str]:
    return violations({rel: source})


def test_a_fixed_month_count_in_add_months_is_flagged() -> None:
    fixed = (
        "def f(now):\n    return add_months(now, 12)\n",
        "def f(now):\n    return billing_repo.add_months(now, months=6)\n",
        "def f(now):\n    return add_months(now, 6 * 2)\n",
        "def f(now):\n    return add_months(now, months := 12)\n",
        "_VALIDITY = 12\n\n\ndef f(now):\n    return add_months(now, _VALIDITY)\n",
        "def f(now):\n    return add_months(now, rules.PERIOD_MONTHS)\n",
        "from x import VALIDITY\n\n\ndef f(now):\n    return add_months(now, VALIDITY)\n",
        "from x import add_months as plus\n\n\ndef f(now):\n    return plus(now, 12)\n",
        "plus = add_months\n\n\ndef f(now):\n    return plus(now, 12)\n",
        "def f(now):\n    return _plus_months(now, 12)\n",
    )
    for source in fixed:
        assert _flags(source), source
    # The same outside lemely/db/: the rule covers the whole package.
    assert _flags(fixed[0], "web/routers/x.py")


def test_a_month_count_read_from_settings_is_not_flagged() -> None:
    ok = (
        "def f(now, months):\n    return add_months(now, months)\n",
        "def f(session, now):\n    return add_months(now, credit_validity_months(session))\n",
        "def f(now, s):\n    return add_months(now, s.credit_validity_months)\n",
    )
    for source in ok:
        assert _flags(source) == [], source


def test_a_literal_relativedelta_is_flagged() -> None:
    assert _flags("x = now + relativedelta(months=12)\n")
    assert _flags("x = now + relativedelta(years=1)\n", "web/x.py")
    assert _flags("x = now + relativedelta(months=n)\n") == []


def test_a_literal_timedelta_on_an_expiry_is_flagged_in_the_db_layer() -> None:
    bad = (
        "def f(now):\n    expires_at = now + timedelta(days=30)\n",
        "def f(now):\n    return issue(expires_at=now + timedelta(days=365))\n",
        "def f(now, g):\n    g.expires_at = now + timedelta(days=30)\n",
        "def f(now):\n    grant_expires_at: object = now + timedelta(weeks=4)\n",
    )
    for source in bad:
        assert _flags(source), source
    ok = (
        "def f(now, pack):\n    return now + timedelta(days=pack.signup_validity_days)\n",
        "def f(now, d):\n    expires_at = now + timedelta(days=d)\n",
        "def f(now):\n    return now - timedelta(hours=2)\n",  # an operational window
    )
    for source in ok:
        assert _flags(source) == [], source


def test_a_hardcoded_seat_ceiling_is_flagged() -> None:
    bad = (
        "def f(sub, seats):\n    return (sub.extra_seats or 0) + seats > 200\n",
        "def f(extra_seats):\n    return 200 < extra_seats\n",
    )
    for source in bad:
        assert _flags(source), source
    capped = "from pydantic import Field\n\nextraSeats: int = Field(default=0, ge=0, le=200)\n"
    assert _flags(capped, "web/schemas_subscriptions.py")
    assert _flags(capped, "io/notify_email.py") == []  # only request schemas carry the ceiling
    ok = (
        "def f(sub, seats, ceiling):\n    return sub.extra_seats + seats > ceiling\n",
        "def f(seats):\n    return seats > 0\n",
        "def f(seats):\n    return 1 <= seats <= MAX_SEATS_PER_PURCHASE\n",
        "def f(rows):\n    return len(rows) > 200\n",
    )
    for source in ok:
        assert _flags(source) == [], source
    sanity = "from pydantic import Field\n\nextraSeats: int = Field(default=0, ge=0, le=10_000)\n"
    assert _flags(sanity, "web/schemas_subscriptions.py") == []
    named = "from pydantic import Field\n\nseats: int = Field(ge=1, le=MAX_SEATS_PER_PURCHASE)\n"
    assert _flags(named, "web/schemas_billing_charges.py") == []


def test_an_import_of_the_seed_module_outside_the_allowlist_is_flagged() -> None:
    forms = (
        "from lemely.core.billing_defaults import GRACE_DAYS\n",
        "from lemely.core import billing_defaults\n",
        "import lemely.core.billing_defaults\n",
        "from .billing_defaults import GRACE_DAYS\n",
        "import importlib\n\nx = importlib.import_module('lemely.core.billing_defaults')\n",
        "import lemely.core\n\nx = lemely.core.billing_defaults.CREDIT_VALIDITY_MONTHS\n",
    )
    for source in forms:
        assert _flags(source, "db/billing_repo.py"), source
        assert _flags(source, "db/migrations/versions/0099_x.py") == [], source
    # Prose that names the module (a docstring) is not an import.
    assert _flags('"""Seeds live in lemely.core.billing_defaults."""\n') == []


def test_the_allowlist_is_per_name_not_per_file() -> None:
    ok = "from lemely.core.billing_defaults import PRICE_CHANGE_NOTICE_DAYS\n"
    assert _flags(ok, "db/billing_settings_repo.py") == []
    assert _flags(ok, "db/usage_catalogue_repo.py")  # not on its list
    other = "from lemely.core.billing_defaults import MAX_EXTRA_SEATS as _SEATS\n"
    assert _flags(other, "db/usage_catalogue_repo.py")
    whole = "from lemely.core import billing_defaults\n"
    assert _flags(whole, "db/billing_settings_repo.py")


def test_a_seed_or_removed_rate_name_is_flagged_however_it_comes_back() -> None:
    forms = (
        "CREDIT_EXPIRY_MONTHS = 12\n",
        "credit_expiry_months = 12\n",
        "MAX_EXTRA_SEATS = 200\n",
        "MAX_EXTRA_SEATS: int = 200\n",
        "GRACE_DAYS = 3\n",
        "def MAX_EXTRA_SEATS():\n    return 200\n",
        "MAX_EXTRA_SEATS_AT_CHECKOUT: int = 200\n",
        "from x import TEACHER_SIGNUP_VALIDITY\n",
        "GRACE_PERIOD: Final = timedelta(days=3)\n",
        "from lemely.core.subscription_rules import GRACE_PERIOD\n",
        "def f(now):\n    return now + rules.GRACE_PERIOD\n",
        "PAYMOB_RETRIAL_DAYS = 3\n",
        "def f():\n    return rules.MAX_EXTRA_SEATS_AT_CHECKOUT\n",
    )
    for source in forms:
        assert _flags(source, "core/x.py"), source
    # The seed module itself is where the seeds are declared.
    assert _flags("MAX_EXTRA_SEATS: int = 200\n", DEFAULTS_FILE) == []
