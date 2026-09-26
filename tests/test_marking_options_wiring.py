"""Every call to correct_paper, hybrid_correct_paper or grade_paper passes
options=, and that options= is read from settings rather than hard-coded.

Three of six callers once passed equivalence_gate and none passed
ecf_substitution, and no test noticed, because each caller's own tests
only covered the default. This is a structural check: it covers callers,
such as the Gradio app, that no behavioural test drives. A new call site
that omits options= fails here instead of silently marking with the
defaults, and a call site that passes a literal `MarkingOptions(...)` fails
too, because that hard-codes defaults and defeats the point.

The guard matches by the literal identifier used at the call site (the
`Name.id` or `Attribute.attr` on the call's `func`), not by resolving
imports. An import alias -- `from lemely.io.correction_ai import
correct_paper as _cp` -- would call through a different name and escape it
undetected. `hybrid_correct_paper` is matched by name exactly like the
other two targets, so an alias of it would escape the same way. No caller
in this codebase uses such an alias today (`tests/test_marking_options_wiring.py`
scans `lemely/` and `scripts/` for every plain and aliased-free call).
"""

from __future__ import annotations

import ast
from pathlib import Path

_TARGETS = {"correct_paper", "hybrid_correct_paper", "grade_paper"}
_ROOT = Path(__file__).resolve().parent.parent
_SCAN_ROOTS = ("lemely", "scripts")

# The exact known call sites, as "path:function". Listed so that removing one
# (or adding an uncounted one) fails loudly instead of the guard silently
# finding a different count. 7 real callers (CLI, both web grading flows,
# quiz marking, the accuracy harness, Gradio, and this accuracy script) plus
# one internal forward -- `grade_paper` calling `correct_paper` -- makes 8.
_KNOWN_CALL_SITES = (
    "lemely/accuracy/harness.py:measure_accuracy",  # accuracy harness caller
    "lemely/app/cli.py:correct_paper_cmd",  # CLI caller
    "lemely/app/gradio_app.py:_grade",  # Gradio caller
    "lemely/db/quiz_marking_repo.py:mark_submission",  # quiz marking caller
    "lemely/web/routers/student.py:run",  # student paper upload caller
    "lemely/web/routers/teacher.py:_run_grading_job",  # teacher grading job caller
    "lemely/web/services/grading.py:grade_paper",  # internal forward to correct_paper
    "scripts/run_real_paper_accuracy.py:run_or_replay_fixture",  # accuracy script caller
)


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


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
    """The guard is not vacuous: it finds exactly the known call sites."""
    found: list[str] = []
    for root_name in _SCAN_ROOTS:
        for path in sorted((_ROOT / root_name).rglob("*.py")):
            rel = path.relative_to(_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found.extend(
                f"{rel}:{node.lineno} {_called_name(node)}(...)"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and _called_name(node) in _TARGETS
            )
    assert len(found) == len(_KNOWN_CALL_SITES), (
        f"expected exactly {len(_KNOWN_CALL_SITES)} marking call sites "
        f"({', '.join(_KNOWN_CALL_SITES)}), found {len(found)}:\n" + "\n".join(found)
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
