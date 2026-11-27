"""Every caller of the teacher-paper repository's ``finish``/``fail`` passes ``run_token``.

``TeacherPaperRepository.finish`` and ``.fail`` take the claim's ``run_started_at``
token as a required keyword (billing phase 04 Task 10): a superseded run must not
save a report onto, or fail, a paper a newer run owns. A caller that forgets it
raises ``TypeError`` only when that line runs, which for ``scripts/seed_e2e.py`` is
the local Playwright setup that CI never executes. This scan finds every such call
in ``lemely/``, ``scripts/`` and ``tests/`` without running it.

No other ``finish``/``fail`` method is called by attribute in those trees, apart from
``pytest.fail`` and unittest's ``self.fail``, which are excluded by receiver.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TREES = ("lemely", "scripts", "tests")
_METHODS = frozenset({"finish", "fail"})
_NOT_A_PAPER_REPO = frozenset({"pytest", "self"})
_SKIPPED_DIRS = frozenset({"__pycache__", "node_modules", ".venv"})


def _python_files() -> list[Path]:
    return sorted(
        path
        for tree in _TREES
        for path in (_ROOT / tree).rglob("*.py")
        if not _SKIPPED_DIRS.intersection(path.relative_to(_ROOT).parts)
    )


def calls_missing_run_token(source: str, filename: str) -> list[str]:
    """``file:line`` for each ``<receiver>.finish(...)``/``.fail(...)`` without ``run_token=``."""
    missing: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _METHODS
        ):
            continue
        receiver = node.func.value
        if isinstance(receiver, ast.Name) and receiver.id in _NOT_A_PAPER_REPO:
            continue
        if not any(kw.arg == "run_token" for kw in node.keywords):
            missing.append(f"{filename}:{node.lineno}")
    return missing


def test_every_finish_and_fail_call_passes_run_token() -> None:
    files = _python_files()
    assert any(f.as_posix().endswith("scripts/seed_e2e.py") for f in files)
    missing = [
        hit
        for path in files
        for hit in calls_missing_run_token(
            path.read_text(encoding="utf-8"), path.relative_to(_ROOT).as_posix()
        )
    ]
    assert missing == []


def test_the_scan_flags_a_missing_token_and_skips_pytest_and_self() -> None:
    source = (
        "repo.finish(pid, report)\n"
        "TeacherPaperRepository(sm).fail(pid, 'boom')\n"
        "repo.finish(pid, report, run_token=token)\n"
        "pytest.fail('nope')\n"
        "self.fail('nope')\n"
    )
    assert calls_missing_run_token(source, "x.py") == ["x.py:1", "x.py:2"]
