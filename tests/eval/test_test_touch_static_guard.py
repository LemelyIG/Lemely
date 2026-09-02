"""CI assertion: no evaluation/analysis code path may compare a label's
``split`` to ``"test"`` outside the sanctioned gate module (spec §7 M0.7a).

This is a static AST scan, not a runtime check — there is no live
pipeline-result/label join yet (M0.1/#25, M2.3 have not landed), so the scan
is the only enforceable mechanism until then. It is modelled on
``tests/architecture/test_no_print_in_core.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = [_REPO_ROOT / "lemely", _REPO_ROOT / "scripts"]

# The one module allowed to compare split to "test": the gate itself.
_SANCTIONED_MODULE = _REPO_ROOT / "lemely" / "eval" / "test_touch.py"

# Directories under the scan roots that are not evaluation/analysis code and
# would otherwise produce false positives (e.g. this test suite's own
# fixtures, generated migrations).
_EXCLUDED_DIR_NAMES = {"__pycache__", "migrations"}


def _is_split_test_comparison(node: ast.AST) -> bool:
    """True if ``node`` branches on a split field being (or not being) ``"test"``.

    Matches ``==``, ``!=``, ``in`` and ``not in``, where one operand textually
    mentions "split" (attribute, subscript key, or bare name) and the other is
    the literal ``"test"`` or a container holding it.

    ``!=`` matters as much as ``==``, and the omission was not hypothetical:
    the sanctioned gate itself early-returns on ``if split != "test"``, so an
    Eq-only guard could not see the very idiom an unsanctioned module would
    copy from it. With Eq alone this guard matched nothing anywhere in the
    repo — it would have passed against an empty checkout, and the
    ``_SANCTIONED_MODULE`` exemption below was dead code. See
    ``test_guard_flags_the_sanctioned_module``, which fails if that recurs.
    """
    if not isinstance(node, ast.Compare):
        return False
    if len(node.ops) != 1:
        return False
    op = node.ops[0]
    if not isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
        return False
    operands = [node.left, node.comparators[0]]

    def _names_test(n: ast.AST) -> bool:
        if isinstance(n, ast.Constant) and n.value == "test":
            return True
        if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            return any(isinstance(e, ast.Constant) and e.value == "test" for e in n.elts)
        return False

    # Membership tests need set logic, not a literal scan: the guarded branch
    # is reachable by a test-split record when the container HOLDS "test"
    # (`in`) or when it does NOT (`not in` — the complement admits test). So
    # `split not in ("train",)` is a test-split branch that never says "test",
    # and an implementation that only looked for the literal missed it.
    # `not in` is always flagged: with "test" absent the complement admits it,
    # and with "test" present it is just a spelling of `!= "test"`.
    if isinstance(op, ast.NotIn):
        literal_present = True
    elif isinstance(op, ast.In):
        literal_present = any(_names_test(o) for o in operands)
    else:
        literal_present = any(_names_test(o) for o in operands)

    def _mentions_split(n: ast.AST) -> bool:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and "split" in sub.id:
                return True
            if isinstance(sub, ast.Attribute) and "split" in sub.attr:
                return True
            if isinstance(sub, ast.Constant) and sub.value == "split":
                return True
        return False

    split_present = any(_mentions_split(o) for o in operands)
    return literal_present and split_present


def _is_split_test_match_case(node: ast.AST) -> bool:
    """True if ``node`` is a ``case "test":`` arm of a ``match`` statement.

    ``match split: case "test": ...`` is a branch on the split value that no
    comparison-node walk would ever see.
    """
    if not isinstance(node, ast.match_case):
        return False
    pattern = node.pattern
    if isinstance(pattern, ast.MatchValue):
        return isinstance(pattern.value, ast.Constant) and pattern.value.value == "test"
    if isinstance(pattern, ast.MatchOr):
        return any(
            isinstance(p, ast.MatchValue)
            and isinstance(p.value, ast.Constant)
            and p.value.value == "test"
            for p in pattern.patterns
        )
    return False


def _offending_sites(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and _is_split_test_comparison(node):
            offenders.append(f"{path}:{node.lineno}")
        elif _is_split_test_match_case(node):
            offenders.append(f"{path}:{node.pattern.lineno}")
    return offenders


def test_guard_flags_the_sanctioned_module() -> None:
    """Positive control: the guard must fire on the one module that legitimately
    compares split to "test".

    Without this, the guard can silently go vacuous — matching nothing anywhere
    — and still pass, because a scan that finds no offenders is exactly what
    success looks like. That is not hypothetical: the first version matched
    only ``ast.Eq``, the gate uses ``!=``, and so it flagged nothing in the
    entire repo while reporting green, leaving the ``_SANCTIONED_MODULE``
    exemption below as dead code.

    If this assertion ever fails, the guard has stopped detecting the idiom it
    exists to detect — fix the matcher, do not delete this test.
    """
    sites = _offending_sites(_SANCTIONED_MODULE)
    assert sites, (
        f"the guard found no split-vs-'test' branch in {_SANCTIONED_MODULE}, "
        "which certainly contains one — the matcher has gone vacuous and the "
        "exemption in test_no_untokened_test_split_join_in_source is dead code."
    )


def test_guard_catches_each_branching_idiom(tmp_path: Path) -> None:
    """The guard must catch every way a module can branch on split == test.

    Each idiom is planted in a throwaway file and must be flagged; the
    negative control must not be.
    """
    idioms = {
        "eq": 'if record.split == "test":\n    join()\n',
        "not_eq": 'if record.split != "test":\n    return\njoin()\n',
        "in_tuple": 'if record.split in ("test", "dev"):\n    join()\n',
        "not_in": 'if record.split not in ("train",):\n    join()\n',
        "match_case": 'match record.split:\n    case "test":\n        join()\n',
        "reversed": 'if "test" == record.split:\n    join()\n',
    }
    for name, src in idioms.items():
        path = tmp_path / f"{name}.py"
        path.write_text(src, encoding="utf-8")
        assert _offending_sites(path), f"guard missed the {name!r} idiom:\n{src}"

    clean = tmp_path / "clean.py"
    clean.write_text('if record.split == "train":\n    join()\n', encoding="utf-8")
    assert _offending_sites(clean) == [], "guard false-positives on a train-split branch"


def test_no_untokened_test_split_join_in_source() -> None:
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.resolve() == _SANCTIONED_MODULE.resolve():
                continue
            if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            offenders.extend(_offending_sites(path))

    assert offenders == [], (
        "split == 'test' comparison found outside the sanctioned gate module "
        f"({_SANCTIONED_MODULE}): {offenders}. Evaluation joins against the "
        "test split must go through lemely.eval.test_touch.authorize_test_split_join."
    )
