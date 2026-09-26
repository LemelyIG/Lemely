"""Every call to correct_paper or grade_paper in lemely/ passes options=.

Three of six callers once passed equivalence_gate and none passed
ecf_substitution, and no test noticed, because each caller's own tests
only covered the default. This is a structural check: it covers callers,
such as the Gradio app, that no behavioural test drives. A new call site
that omits options= fails here instead of silently marking with the
defaults.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TARGETS = {"correct_paper", "hybrid_correct_paper", "grade_paper"}
_PACKAGE = Path(__file__).resolve().parent.parent / "lemely"


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_every_marking_call_passes_options() -> None:
    missing: list[str] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node) not in _TARGETS:
                continue
            if not any(kw.arg == "options" for kw in node.keywords):
                rel = path.relative_to(_PACKAGE.parent)
                missing.append(f"{rel}:{node.lineno} {_called_name(node)}(...)")
    assert not missing, "marking call sites without options=:\n" + "\n".join(missing)


def test_the_guard_sees_all_six_callers() -> None:
    """The guard is not vacuous: it finds the six known call sites."""
    found = 0
    for path in _PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _called_name(node) in _TARGETS
        )
    assert found >= 6
