"""Only the allowlisted modules may touch ``tutoring_blocks`` (PLAN §1.4 #9, P13, O11).

The block predicates live once, in ``lemely/db/tutoring_predicates.py``. A
module that writes its own ``tutoring_blocks`` SQL could key a block on
``tutor_profiles.id`` instead of ``users.id``, check one direction only, or
forget ``removed_at``, and its listing would then disagree with every other one.

The detector walks each module's AST rather than grepping (precedent:
``tests/test_include_deleted_scope.py``), so it sees the table name in any
string a module executes (plain, f-string, ``sa.text``) and any use of the
``TutoringBlock`` model, while ignoring the same words in a docstring.
"""

from __future__ import annotations

import ast
from pathlib import Path

LEMELY = Path(__file__).resolve().parent.parent / "lemely"

#: Paths relative to the repository root. The last two do not exist yet: the
#: blocks repository and the sweeps (PLAN §1.4 #2) are their future owners.
ALLOWLIST = frozenset(
    {
        "lemely/db/tutoring_predicates.py",
        "lemely/db/models/tutoring.py",
        "lemely/db/migrations/versions/0050_tutoring_safety.py",
        "lemely/db/tutoring_blocks_repo.py",
        "lemely/db/tutoring_sweeps.py",
    }
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def touches_tutoring_blocks(source: str) -> bool:
    """True if ``source`` names the table in code or uses the ``TutoringBlock`` model."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and "tutoring_blocks" in node.value
        ):
            return True
        if isinstance(node, ast.Name) and node.id == "TutoringBlock":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "TutoringBlock":
            return True
        if isinstance(node, ast.alias) and node.name == "TutoringBlock":
            return True
    return False


def _touching_modules() -> set[str]:
    root = LEMELY.parent
    return {
        path.relative_to(root).as_posix()
        for path in LEMELY.rglob("*.py")
        if touches_tutoring_blocks(path.read_text(encoding="utf-8"))
    }


def test_no_module_outside_allowlist_touches_tutoring_blocks() -> None:
    touching = _touching_modules()
    assert touching - ALLOWLIST == set()
    # Non-vacuity: the walk reaches the allowlisted owners and recognises them.
    assert {
        "lemely/db/tutoring_predicates.py",
        "lemely/db/models/tutoring.py",
        "lemely/db/migrations/versions/0050_tutoring_safety.py",
    } <= touching
    assert len(list(LEMELY.rglob("*.py"))) > 100


def test_detector_recognises_every_spelling() -> None:
    hits = [
        'QUERY = "SELECT 1 FROM tutoring_blocks"',
        'def f(alias):\n    return f"JOIN tutoring_blocks {alias}"',
        'stmt = sa.text("DELETE FROM tutoring_blocks WHERE x")',
        "from lemely.db.models.tutoring import TutoringBlock",
        "import lemely.db.models.tutoring as t\nrow = t.TutoringBlock",
        "def g(session):\n    return session.get(TutoringBlock, 1)",
    ]
    for source in hits:
        assert touches_tutoring_blocks(source), source


def test_detector_ignores_docstrings_and_comments() -> None:
    misses = [
        '"""Blocks live in tutoring_blocks; see the predicates module."""',
        'def f():\n    """Reads tutoring_blocks through the predicates."""\n    return 1',
        "x = 1  # tutoring_blocks is not touched here",
        'NAME = "tutoring_reports"',
    ]
    for source in misses:
        assert not touches_tutoring_blocks(source), source
