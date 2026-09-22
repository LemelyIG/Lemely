"""One formulation of "did a marker score this question?" — task #36.

WHAT WENT WRONG, AND WHY A GATE RATHER THAN MORE TESTS
------------------------------------------------------

US-039 made a genuine student blank an UNFLAGGED zero — ``confidence_score =
0.0``, ``confidence = LOW``, ``needs_teacher_review = False`` — without giving
it a ``marker_source`` of its own. It reused ``"missing"``, which already meant
"the AI was not called for this question" for two other reasons, and carried the
distinction in free-text ``review_reason``. So ``0.0`` stopped meaning "the
marker looked and was unsure" and started ALSO meaning "nothing looked", with no
change to its representation.

Every consumer that read it the old way silently changed behaviour on unchanged
input. Nine had to be found by hand, in three waves, none of them appearing in
any of the eleven commits that caused the change:

* the review-queue predicate itself (three attempts to get right)
* a paper card rendering ``Graded · 0.00``
* a pipeline card contradicting ``/grading/queue`` in the same router
* ``markingConfidence.ts`` rendering a blank as "uncertain" on the student's own
  paper
* the accuracy harness depositing every blank as a correct prediction in the
  LOWEST calibration bucket
* ``confidenceBand: "low"`` beside ``needsTeacherReview: false`` on the wire
* the practice screen — the same defect again, found only because someone
  thought to check the confidence BAND rather than the score
* develop's ``is_marking_low_confidence``, a grading-AUTHORITY gate, where the
  same ``0.0`` let a student overturn their own mark on a blank with no evidence
  and no judge

Eight of those sites spelled the question out for themselves. So the fix is not
another eight tests: it is one function
(:func:`lemely.core.schemas.marker_scored`) plus a gate that fails when a ninth
site spells it out again. The truth table below is the function; the gate below
that is the part that has to survive the next story.

The frontend half of the same pair lives in
``tests/test_web_shared_constants.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lemely.core.schemas import (
    UNSCORED_MARKER_SOURCES,
    ConfidenceBand,
    CorrectedQuestion,
    MarkerSourceValue,
    marker_scored,
)
from lemely.db.models.enums import MarkerSource

LEMELY_SRC = Path(__file__).resolve().parents[1] / "lemely"


# ── the function ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("member", list(MarkerSource), ids=lambda m: m.value)
def test_marker_scored_answers_for_every_enum_member(member: MarkerSource) -> None:
    """No member may be un-answered, and the answers are stated here explicitly.

    Enumerating the enum rather than a written-out list is the point: a sixth
    member arrives here with no answer and fails, instead of quietly defaulting
    to "scored" at eight call sites.
    """
    expected = {
        MarkerSource.deterministic: True,
        MarkerSource.ai: True,
        MarkerSource.missing: False,
        MarkerSource.dropped: False,
        MarkerSource.blank: False,
    }
    assert member in expected, f"{member.value} has no stated answer — add one"
    assert marker_scored(member.value) is expected[member]


def test_an_unknown_value_reads_as_scored() -> None:
    """The safe direction for an unrecognised value, and it is a real choice.

    ``False`` would exclude a question from confidence minima, calibration and
    the review-queue count on the strength of a value nobody declared. ``True``
    keeps it in and lets the type-level gates
    (``test_every_layer_declares_the_same_marker_source_values``,
    ``routers/practice._marker_source``) be the things that catch it.
    """
    assert marker_scored("some_future_source") is True


def test_the_real_blank_builder_is_not_scored() -> None:
    """Asked of the producer, not of a literal.

    ``tests/test_self_review_authority_builders.py`` explains why: a test that
    names field values freezes them, and the next story adds a producer the
    test has never heard of.
    """
    from lemely.core.loose_schemas import Question, QuestionType
    from lemely.io.correction_ai import _build_blank_corrected

    question = Question.model_construct(
        id="3b",
        marks=4,
        type=QuestionType.CALCULATION,
        parts=[],
        assessment_objectives=[],
        answer_points=[],
        rejected_answers=[],
        ignored_answers=[],
    )
    blank = _build_blank_corrected(question)

    assert marker_scored(blank.marker_source) is False
    # And the three fields that used to have to carry this are unchanged, so
    # nothing downstream can tell a blank from a doubtful mark by reading them.
    # That is the whole reason `marker_source` had to grow a value.
    assert blank.confidence_score == 0.0
    assert blank.confidence is ConfidenceBand.LOW
    assert blank.needs_teacher_review is False


def test_a_blank_is_the_only_student_blank() -> None:
    """``marker_scored`` and "is this a student blank" are DIFFERENT questions.

    Three values answer ``False`` to the first; exactly one answers ``True`` to
    the second. Collapsing them silences a dropped answer — which the model DID
    respond to — from the review queue and from the authority gate.
    """
    blanks = [m for m in MarkerSource if m.value == "blank"]
    assert len(blanks) == 1
    unscored = {m.value for m in MarkerSource if not marker_scored(m.value)}
    assert unscored == set(UNSCORED_MARKER_SOURCES)
    assert unscored > {"blank"}


# ── the gate ────────────────────────────────────────────────────────────────

#: The spellings this forbids, as they actually shipped:
#:
#:     q.marker_source not in ("missing", "dropped")   (five sites)
#:     q.marker_source != "missing"                    (one site, and it
#:                                                      counted a dropped
#:                                                      answer as marked)
#:
#: Comparisons against ``"blank"`` are NOT forbidden -- that is the other
#: question ("was this a student blank?"), and ``review_queue_rules`` is meant to
#: ask it -- nor against ``"deterministic"``, which ``accuracy/harness.py`` asks
#: to tell an MCQ leaf from a theory one.
_FORBIDDEN_VALUES = frozenset({"missing", "dropped"})

#: Names that hold a marker source. Deliberately short: a wider list
#: (``value``, ``source``) would fire on unrelated string comparisons all over
#: the tree, and a gate with false positives gets deleted rather than obeyed.
#:
#: KNOWN BLIND SPOT, stated rather than papered over:
#: ``web/routers/practice._marker_source`` compares a parameter called ``value``
#: against every literal, so this gate cannot see it. It must name them --- it
#: is the exhaustive ``str``-to-``Literal`` narrowing --- and
#: ``tests/test_web_practice.py`` parametrises it over ``MarkerSource`` itself,
#: which is the check that actually covers that function.
_MARKER_SOURCE_NAMES = frozenset({"marker_source", "markerSource", "msrc"})


def _mentions_marker_source(node: ast.AST) -> bool:
    """True when this expression reads a marker source, by attribute or by name."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in _MARKER_SOURCE_NAMES:
            return True
        if isinstance(child, ast.Name) and child.id in _MARKER_SOURCE_NAMES:
            return True
    return False


def _named_values(node: ast.AST) -> set[str]:
    """The marker-source values this expression names, however it spells them.

    Three spellings, because a gate that sees only one is a gate someone walks
    past without noticing:

    * a string constant --- ``"missing"``, how all eight removed sites spelled it;
    * a literal collection of them --- ``("missing", "dropped")``, how five did;
    * a ``MarkerSource`` member --- ``MarkerSource.missing``, which no production
      site uses today but which ``is``-comparisons on a persisted
      ``QuestionResult`` would naturally reach for, since that column is typed
      as the enum rather than as ``str``.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "MarkerSource":
            return {node.attr}
        return set()
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        values: set[str] = set()
        for element in node.elts:
            values |= _named_values(element)
        return values
    return set()


def _offending_lines(source: str) -> list[tuple[int, str]]:
    """Comparisons of a marker source against an unscored value.

    An AST walk over ``Compare`` nodes, not a text search, and that distinction
    is the whole design of this gate. The first draft matched text with the
    string literals stripped by a tokeniser, so it could never fire — that is
    ``sdd/probes/probe_reach.py``'s failure mode, a check that hardcodes the
    answer it reports, and the inversion tests below are what caught it. The
    second draft kept the literals and fired on the BUILDERS
    (``marker_source="missing"`` in ``_build_missing_corrected``) and on a CLI
    help string, both of which are correct code: a producer must name the value
    it produces.

    Only a comparison is the defect. Constructing a value, declaring it in an
    enum, or writing it in prose is not.
    """
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any(_mentions_marker_source(operand) for operand in operands):
            continue
        named: set[str] = set()
        for operand in operands:
            named |= _named_values(operand)
        hit = named & _FORBIDDEN_VALUES
        if hit:
            offenders.append((node.lineno, ", ".join(sorted(hit))))
    return sorted(offenders)


def test_no_module_compares_a_marker_source_against_an_unscored_value() -> None:
    """One place decides this, because eight places is how nine consumers happened."""
    offenders: list[str] = []
    for path in LEMELY_SRC.rglob("*.py"):
        relative = path.relative_to(LEMELY_SRC.parent).as_posix()
        for number, values in _offending_lines(path.read_text(encoding="utf-8")):
            offenders.append(f"{relative}:{number}: compares against {values}")
    assert not offenders, (
        "a marker source is compared against an unscored value — ask "
        "`lemely.core.schemas.marker_scored` instead:\n" + "\n".join(offenders)
    )


def test_the_gate_fires_on_the_spellings_it_replaced() -> None:
    """Inversion, on the two spellings that actually shipped.

    ``q.marker_source not in ("missing", "dropped")`` stood at five sites and
    ``q.marker_source != "missing"`` at a sixth. Both must be caught. Prose
    quoting either must not be — a gate that fails on its own fix note gets
    deleted rather than obeyed — and neither must the two comparisons that are
    still correct.
    """
    source = (
        "def f(q, questions, cq):\n"
        '    """Docstring naming marker_source == "missing" for the record."""\n'
        '    # comment naming marker_source != "missing" too\n'
        '    a = q.marker_source not in ("missing", "dropped")\n'
        '    b = sum(1 for x in questions if x.marker_source != "missing")\n'
        '    c = q.marker_source == "blank"\n'
        '    d = "mcq" if cq.marker_source == "deterministic" else "theory"\n'
        '    e = CorrectedQuestion(marker_source="missing")\n'
        "    f = qr.marker_source is MarkerSource.dropped\n"
        "    g = qr.marker_source is MarkerSource.blank\n"
        "    return a, b, c, d, e, f, g\n"
    )
    # 4 and 5 are the two removed string spellings; 9 is the enum spelling no
    # production site uses today but which an `is`-comparison on a persisted row
    # would reach for. 6, 7, 8 and 10 are the comparisons and constructions that
    # must stay allowed.
    assert [number for number, _ in _offending_lines(source)] == [4, 5, 9]


def test_the_gate_fires_on_the_real_pre_change_file() -> None:
    """The stronger inversion: on the shipped text, not a hand-written mock-up.

    The first draft of this gate passed a hand-written inversion only because
    its bug also broke the mock-up. Re-deriving the two ``teacher.py`` call
    sites from the current tree and re-introducing the old spelling proves the
    gate sees a real file, and fails loudly if either call site is refactored
    out from under this test.
    """
    current = (LEMELY_SRC / "web" / "routers" / "teacher.py").read_text(encoding="utf-8")
    assert _offending_lines(current) == [], "teacher.py already trips the gate"

    reverted = current.replace(
        "marked = sum(1 for q in questions if marker_scored(q.marker_source))",
        'marked = sum(1 for q in questions if q.marker_source != "missing")',
    ).replace(
        "scored = [q for q in correction.questions if marker_scored(q.marker_source)]",
        "scored = [q for q in correction.questions if q.marker_source "
        'not in ("missing", "dropped")]',
    )
    assert reverted != current, "neither call site was found — this test has drifted"
    assert len(_offending_lines(reverted)) == 2


# ── the consumers, at the two seams where the answer changed ────────────────


def _question(
    marker_source: MarkerSourceValue, *, confidence: float, needs_review: bool
) -> CorrectedQuestion:
    """A question with the given marker source.

    ``MarkerSourceValue``, not ``str``, and not ``str`` plus a
    ``# type: ignore[arg-type]`` -- which is what this was first written as. The
    pydantic mypy plugin does not check a field's declared type against the value
    passed, so only pyright sees ``str`` reaching a ``Literal``; a suppression
    here would hide exactly the class of defect this file exists about.
    """
    return CorrectedQuestion(
        question_id="1",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=confidence,
        needs_teacher_review=needs_review,
        marker_source=marker_source,
    )


def test_the_marked_count_excludes_every_unscored_question() -> None:
    """``_graded_pipeline_steps``'s "Mark scheme aligned" count.

    This was the THIRD genuinely-different formulation — ``!= "missing"`` — and
    the only one that called an unscored question marked. It counted a
    ``"dropped"`` answer (the model replied, extraction discarded it) as
    aligned against the mark scheme, and would have counted a ``"blank"`` one
    too. ``0038_marker_source_dropped``'s own docstring predicted this call site
    would need widening once the enum could express the distinction; task #36 is
    that widening, arrived at by removing the formulation rather than editing it.
    """
    from lemely.web.routers.teacher import _graded_pipeline_steps

    report = _report_of(
        [
            _question("ai", confidence=0.95, needs_review=False),
            _question("missing", confidence=0.0, needs_review=True),
            _question("dropped", confidence=0.0, needs_review=True),
            _question("blank", confidence=0.0, needs_review=False),
        ]
    )

    steps = {step.label: step.count for step in _graded_pipeline_steps(report)}

    assert steps["Mark scheme aligned"] == "1 / 4"
    # Minor F (final-branch-review): the denominator is the marked population
    # (1), not the paper total (4) -- the blank/dropped/missing questions were
    # never checked, so they must not appear to have passed a check. Of the
    # one question a marker actually scored (the "ai" one), it needed no
    # human look, hence 1 / 1.
    assert steps["Confidence check"] == "1 / 1"


def test_confidence_check_reports_the_marked_denominator_not_the_paper_total() -> None:
    """Minor F (final-branch-review): the exact scenario the finding named.

    A 10-question paper with 8 blanks and 2 clean marks used to read
    "Confidence check 10 / 10" -- every blank is exempt from review, which the
    unfiltered count mistook for "passed the check". It should read 2 / 2:
    both of the questions a marker actually scored needed no human look, and
    the 8 that were never scored are no longer counted as if they had been.
    """
    from lemely.web.routers.teacher import _graded_pipeline_steps

    report = _report_of(
        [_question("blank", confidence=0.0, needs_review=False) for _ in range(8)]
        + [
            _question("ai", confidence=0.95, needs_review=False),
            _question("deterministic", confidence=1.0, needs_review=False),
        ]
    )

    steps = {step.label: step.count for step in _graded_pipeline_steps(report)}

    assert steps["Mark scheme aligned"] == "2 / 10"
    assert steps["Confidence check"] == "2 / 2"


def test_the_paper_card_confidence_ignores_every_unscored_question() -> None:
    """Finding E: an unfiltered ``min`` renders a graded paper as ``Graded · 0.00``.

    A blank, a dropped answer and a not-marked question all carry
    ``confidence_score == 0.0`` as a placeholder. One of them on a ten-question
    paper used to set the whole card's confidence.
    """
    from lemely.web.routers.teacher import _paper_summary

    report = _report_of(
        [
            _question("ai", confidence=0.93, needs_review=False),
            _question("blank", confidence=0.0, needs_review=False),
            _question("dropped", confidence=0.0, needs_review=True),
            _question("missing", confidence=0.0, needs_review=True),
        ]
    )

    summary = _paper_summary(_row_of(report))

    assert summary.confidence == 0.93


def _report_of(questions: list[CorrectedQuestion]):
    from lemely.core.schemas import (
        AccuracyReport,
        CorrectionResult,
        ExamMetadata,
        GradePrediction,
        WeaknessReport,
    )

    correction = CorrectionResult(
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        questions=questions,
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=GradePrediction(
            awarded_marks=correction.awarded_marks,
            maximum_marks=correction.maximum_marks,
            percentage=0.0,
            grade="U",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=True,
            boundary_source="subject_default",
        ),
    )


def _row_of(report):
    import uuid
    from datetime import UTC, datetime

    from lemely.db.models.enums import UploadStatus
    from lemely.db.teacher_paper_repo import TeacherPaperRow

    now = datetime.now(UTC)
    return TeacherPaperRow(
        id=uuid.uuid4(),
        uploaded_by=uuid.uuid4(),
        student_id=None,
        storage_path="papers/x.pdf",
        scheme_storage_path=None,
        original_filename="x.pdf",
        content_type="application/pdf",
        status=UploadStatus.complete,
        stage=None,
        progress=None,
        metadata=report.correction.metadata,
        mark_scheme=None,
        report=report,
        error=None,
        run_started_at=None,
        created_at=now,
        updated_at=now,
        stale=False,
    )
