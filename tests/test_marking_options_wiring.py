"""Every call to correct_paper, hybrid_correct_paper or grade_paper passes
options=, and that options= is read from settings rather than hard-coded.

Three of six callers once passed equivalence_gate and none passed
ecf_substitution, and no test noticed, because each caller's own tests
only covered the default. This is a structural check: it covers callers,
such as the Gradio app, that no behavioural test drives. A new call site
that omits options= fails here instead of silently marking with the
defaults, and a call site that passes a literal `MarkingOptions(...)` fails
too, because that hard-codes defaults and defeats the point.

The guard matches by name: the `Name.id` or `Attribute.attr` on the call's
`func`, not by resolving imports. A call through an import alias, such as
`from lemely.io.correction_ai import correct_paper as _cp` followed by
`_cp(...)`, would escape the guard undetected, because the name at the
call site is `_cp`, not `correct_paper`. `hybrid_correct_paper` is matched
by name exactly like the other two targets, so an alias of it would escape
the same way too. The Gradio app happens to import `correct_paper` under
the alias `hybrid_correct_paper` (`lemely/app/gradio_app.py`); since that
alias collides with one of the three target names, the call it makes is
still caught -- but the guard would not catch an alias to any other name.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TARGETS = {"correct_paper", "hybrid_correct_paper", "grade_paper"}
_ROOT = Path(__file__).resolve().parent.parent
_SCAN_ROOTS = ("lemely", "scripts")

# The exact known call sites, as "<path relative to repo root>:<enclosing
# function>". Listed explicitly, and compared below as a set rather than a
# count, so that swapping one site for another, or mislabelling one (the
# Gradio call site once read "_grade" here, but the call is inside the
# nested `_run` closure defined within `_grade`), fails loudly instead of
# the guard silently agreeing as long as the number of sites is unchanged.
# 7 real callers (CLI, both web grading flows, quiz marking, the accuracy
# harness, Gradio, and this accuracy script) plus one internal forward --
# `grade_paper` calling `correct_paper` -- makes 8.
_KNOWN_CALL_SITES = frozenset(
    {
        "lemely/accuracy/harness.py:measure_accuracy",  # accuracy harness caller
        "lemely/app/cli.py:correct_paper_cmd",  # CLI caller
        "lemely/app/gradio_app.py:_run",  # Gradio caller (nested inside _grade)
        "lemely/db/quiz_marking_repo.py:mark_submission",  # quiz marking caller
        "lemely/web/routers/student.py:run",  # student paper upload caller
        "lemely/web/routers/teacher.py:_run_grading_job",  # teacher grading job caller
        "lemely/web/services/grading.py:grade_paper",  # internal forward to correct_paper
        "scripts/run_real_paper_accuracy.py:run_or_replay_fixture",  # accuracy script caller
    }
)


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _collect_call_sites(source: str, filename: str) -> set[str]:
    """Collect every marking-target call site in *source*.

    Each site is labelled ``"<filename>:<enclosing function>"``. Walks the
    tree keeping a stack of enclosing ``FunctionDef``/``AsyncFunctionDef``
    names and labels a call with the innermost one, or ``"<module>"`` when
    the call sits at module level (matching by call-site name only, per the
    module docstring, so an aliased import can still slip past unlabelled).
    """
    sites: set[str] = set()
    stack: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if _called_name(node) in _TARGETS:
                enclosing = stack[-1] if stack else "<module>"
                sites.add(f"{filename}:{enclosing}")
            self.generic_visit(node)

    _Visitor().visit(ast.parse(source, filename=filename))
    return sites


def _is_hardcoded_marking_options(value: ast.expr) -> bool:
    """True if *value* is a bare ``MarkingOptions(...)`` constructor call.

    ``options=options`` (the forwarding in ``grading.py``) and
    ``options=settings.grading.marking_options()`` both read the flags from
    settings and stay allowed; a literal ``MarkingOptions(...)`` hard-codes
    defaults regardless of settings.
    """
    return isinstance(value, ast.Call) and _called_name(value) == "MarkingOptions"


def find_marking_call_issues(
    source: str, filename: str = "<string>"
) -> tuple[list[str], list[str]]:
    """Scan *source* for calls to the marking targets.

    Returns ``(missing, hardcoded)``: call sites with no ``options=``
    keyword, and call sites whose ``options=`` value is a bare
    ``MarkingOptions(...)`` constructor call. Factored out of the tests below
    so a test can feed it a source string directly, without editing a
    production file to prove a rejection works.
    """
    missing: list[str] = []
    hardcoded: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called_name(node) not in _TARGETS:
            continue
        label = f"{filename}:{node.lineno} {_called_name(node)}(...)"
        options_kw = next((kw for kw in node.keywords if kw.arg == "options"), None)
        if options_kw is None:
            missing.append(label)
        elif _is_hardcoded_marking_options(options_kw.value):
            hardcoded.append(label)
    return missing, hardcoded


def test_every_marking_call_passes_options() -> None:
    missing: list[str] = []
    hardcoded: list[str] = []
    for root_name in _SCAN_ROOTS:
        for path in sorted((_ROOT / root_name).rglob("*.py")):
            rel = path.relative_to(_ROOT)
            file_missing, file_hardcoded = find_marking_call_issues(
                path.read_text(encoding="utf-8"), filename=str(rel)
            )
            missing.extend(file_missing)
            hardcoded.extend(file_hardcoded)
    assert not missing, "marking call sites without options=:\n" + "\n".join(missing)
    assert not hardcoded, (
        "marking call sites with a hard-coded MarkingOptions() instead of settings:\n"
        + "\n".join(hardcoded)
    )


def test_the_guard_sees_every_known_call_site() -> None:
    """The guard is not vacuous: it finds exactly the known call sites.

    Compares the *set* of sites, not just its size, so swapping one site
    for another -- or mislabelling one, as the old comment did by naming
    ``_grade`` instead of the ``_run`` closure nested inside it -- fails
    loudly instead of staying green as long as the count matches.
    """
    found: set[str] = set()
    for root_name in _SCAN_ROOTS:
        for path in sorted((_ROOT / root_name).rglob("*.py")):
            rel = path.relative_to(_ROOT)
            found |= _collect_call_sites(path.read_text(encoding="utf-8"), str(rel))
    missing = _KNOWN_CALL_SITES - found
    unexpected = found - _KNOWN_CALL_SITES
    assert not missing and not unexpected, (
        "marking call sites drifted from the expected set:\n"
        f"missing (expected, not found): {sorted(missing)}\n"
        f"unexpected (found, not expected): {sorted(unexpected)}"
    )


def test_matcher_flags_a_hardcoded_marking_options() -> None:
    missing, hardcoded = find_marking_call_issues(
        "correct_paper(ms, ans, options=MarkingOptions())\n", filename="probe.py"
    )
    assert not missing
    assert hardcoded == ["probe.py:1 correct_paper(...)"]


def test_matcher_flags_a_missing_options_kwarg() -> None:
    missing, hardcoded = find_marking_call_issues("correct_paper(ms, ans)\n", filename="probe.py")
    assert missing == ["probe.py:1 correct_paper(...)"]
    assert not hardcoded


def test_matcher_allows_forwarded_and_settings_derived_options() -> None:
    missing, hardcoded = find_marking_call_issues(
        "correct_paper(ms, ans, options=options)\n"
        "grade_paper(ms, ans, options=settings.grading.marking_options())\n",
        filename="probe.py",
    )
    assert not missing
    assert not hardcoded
