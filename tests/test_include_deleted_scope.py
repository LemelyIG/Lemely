"""Containment of the soft-delete escape hatch (Task 11, review amendment I7).

``INCLUDE_DELETED``/``include_deleted`` is the one way to see a soft-deleted
``Attempt``, ``Upload``, or ``TeacherPaper`` row, and it must not spread beyond
its five permitted callers (``lemely/db/session.py``, the definition;
``lemely/db/deletion_repo.py``; ``lemely/web/purge.py``;
``lemely/db/attempt_repo.py``'s ``_lock_live_upload``, which must see a deleted
upload to refuse persisting an attempt onto it — Task 5a; and, as of this task,
``lemely/db/admin_repo.py``'s purge-backlog metric).

The detector walks each file's AST rather than grepping for text, so it
recognises the three real spellings a caller can use --- the ``INCLUDE_DELETED``
constant as a bare name or an attribute access, the keyword
``include_deleted=`` on a call, and the raw string ``"include_deleted"`` used
inside a call (e.g. ``execution_options(**{"include_deleted": True})``) --- while
ignoring the same text sitting in a docstring or a comment, which carries no
runtime meaning. ``lemely/db/models/attempts.py`` mentions
``include_deleted`` only in a docstring and must NOT appear in the found set.

Task 16 will add teacher-paper deletion inside ``deletion_repo.py`` and purge
inside ``purge.py`` — both already-allowed files — so this allowlist should not
need to grow when that lands.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _uses_include_deleted(tree: ast.AST) -> bool:
    """True if ``tree`` contains any of the three real spellings of the hatch."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "INCLUDE_DELETED":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "INCLUDE_DELETED":
            return True
        if isinstance(node, ast.keyword) and node.arg == "include_deleted":
            return True
        if isinstance(node, ast.Call):
            # The string form only counts inside a call (e.g. a dict literal
            # passed as `**{"include_deleted": True}`) -- a bare module-level
            # or docstring string is not a use of the hatch, just text.
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value == "include_deleted":
                    return True
    return False


def _find_include_deleted_files(root: Path) -> set[Path]:
    """Every ``*.py`` file under ``root`` whose AST uses the escape hatch."""
    found: set[Path] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _uses_include_deleted(tree):
            found.add(path)
    return found


def test_include_deleted_appears_only_where_it_is_allowed() -> None:
    """The escape hatch must not spread beyond its five permitted callers."""
    allowed = {
        Path("lemely/db/session.py"),
        Path("lemely/db/deletion_repo.py"),
        Path("lemely/web/purge.py"),
        Path("lemely/db/attempt_repo.py"),
        Path("lemely/db/admin_repo.py"),
    }
    found = _find_include_deleted_files(Path("lemely"))
    assert found == allowed


def test_the_scope_test_would_notice_a_new_user(tmp_path: Path) -> None:
    """The detector is shown to detect, so this test cannot pass vacuously.

    Each of the three spellings the detector recognises is proven separately,
    running **the same function** the real scan uses, against an intruder file
    that is otherwise unrelated to the allowlist above.
    """
    name_form = tmp_path / "rogue_name.py"
    name_form.write_text(
        "from lemely.db.session import INCLUDE_DELETED\n"
        "stmt.execution_options(**{INCLUDE_DELETED: True})\n",
        encoding="utf-8",
    )

    keyword_form = tmp_path / "rogue_keyword.py"
    keyword_form.write_text("stmt.execution_options(include_deleted=True)\n", encoding="utf-8")

    string_form = tmp_path / "rogue_string.py"
    string_form.write_text(
        'stmt.execution_options(**{"include_deleted": True})\n', encoding="utf-8"
    )

    # A docstring mentioning the word must NOT be reported -- it is prose, not
    # a use of the hatch.
    docstring_only = tmp_path / "innocent.py"
    docstring_only.write_text(
        '"""Mentions include_deleted in prose, never as code."""\n', encoding="utf-8"
    )

    found = _find_include_deleted_files(tmp_path)

    assert name_form in found
    assert keyword_form in found
    assert string_form in found
    assert docstring_only not in found
