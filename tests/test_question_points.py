"""Per-mark-point derivation (spec 2026-09-17, "Write path").

Pure-function tests: no database, no session. The behaviour that matters most
is the inversion — a row is written per point in the MARK SCHEME, not per id in
``matched_point_ids`` — because missed points are exactly what a breakdown is
for.
"""

from __future__ import annotations

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MathMarkType,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.schemas import AIMarkResponse, ConfidenceBand, CorrectedQuestion, PointVerdict
from lemely.db.question_points import derive_point_rows
from lemely.io.correction_ai import _build_ai_corrected
from tests.conftest import _scheme


def _corrected(**overrides: object) -> CorrectedQuestion:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "matched_point_ids": ["p1"],
    }
    base.update(overrides)
    return CorrectedQuestion(**base)  # type: ignore[arg-type]


def test_writes_a_row_per_scheme_point_not_per_matched_id() -> None:
    """The inversion. Two missed points must still become rows."""
    rows = derive_point_rows(_corrected(), _scheme())

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["awarded"] for row in rows] == [True, False, False]


def test_carries_tariff_mark_type_and_text_from_the_scheme() -> None:
    rows = derive_point_rows(_corrected(), _scheme())

    assert rows[1] == {
        "mark_point_id": "p2",
        "ordinal": 1,
        "mark_type": "A",
        "tariff": 1,
        "tariff_defaulted": False,
        "point_text": "Answer to 3sf",
        "awarded": False,
        "is_alternative": False,
        "is_optional": False,
        "rationale": None,
        "group_key": None,
        "group_max_marks": None,
        "verdict": None,
        "evidence_span": "",
        "ecf_applied": False,
    }


def test_rationale_comes_from_point_notes_when_the_marker_supplied_it() -> None:
    rows = derive_point_rows(
        _corrected(point_notes={"p2": "wrote 12.47, needed 12.5"}),
        _scheme(),
    )

    assert rows[1]["rationale"] == "wrote 12.47, needed 12.5"
    assert rows[0]["rationale"] is None


def test_point_notes_for_unknown_points_are_ignored() -> None:
    """A note keyed to a point the scheme lacks must not mint a row."""
    rows = derive_point_rows(
        _corrected(point_notes={"p99": "note for a point that does not exist"}),
        _scheme(),
    )

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]


def test_dangling_matched_ids_do_not_become_rows() -> None:
    """An id the marker claimed but the scheme lacks is dropped, not invented."""
    rows = derive_point_rows(_corrected(matched_point_ids=["p1", "p_ghost"]), _scheme())

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["awarded"] for row in rows] == [True, False, False]


def test_no_scheme_yields_no_rows() -> None:
    """The quiz case: persist_quiz_correction has no scheme to pass."""
    assert derive_point_rows(_corrected(), None) == []


def test_question_absent_from_the_scheme_yields_no_rows() -> None:
    assert derive_point_rows(_corrected(question_id="99z"), _scheme()) == []


def test_question_with_no_answer_points_yields_no_rows() -> None:
    """Levels-based questions carry descriptors, not points."""
    scheme = _scheme()
    scheme.questions[0].answer_points = []

    assert derive_point_rows(_corrected(), scheme) == []


def test_duplicate_point_ids_collapse_to_one_row_first_occurrence_wins() -> None:
    """A malformed scheme with two points sharing an id must not emit two rows:
    that would violate the DB's uniqueness constraint on
    ``(question_result_id, mark_point_id)`` and lose the whole attempt at
    commit (spec 2026-09-17, "Error handling"). The first occurrence wins and
    ``ordinal`` stays contiguous over the emitted rows, not the raw index.
    """
    scheme = _scheme()
    scheme.questions[0].answer_points = [
        AnswerPoint(id="p1", point="Correct method", marks=1, math_mark_type=MathMarkType.M),
        AnswerPoint(
            id="p1", point="Duplicate, should be dropped", marks=5, math_mark_type=MathMarkType.B
        ),
        AnswerPoint(id="p2", point="Answer to 3sf", marks=1, math_mark_type=MathMarkType.A),
    ]

    rows = derive_point_rows(_corrected(matched_point_ids=["p1"]), scheme)

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2"]
    assert [row["ordinal"] for row in rows] == [0, 1]
    assert rows[0]["point_text"] == "Correct method"
    assert rows[0]["tariff"] == 1


def test_mark_type_is_none_for_a_non_maths_point() -> None:
    scheme = _scheme()
    scheme.questions[0].answer_points[0].math_mark_type = None

    rows = derive_point_rows(_corrected(), scheme)

    assert rows[0]["mark_type"] is None


def test_defaulted_marks_are_flagged_as_tariff_defaulted() -> None:
    """A point whose marks were minted (not read from the source) must carry

    that provenance onto the ledger row, so a reader never mistakes a guessed
    tariff for one CAIE actually printed (spec 2026-09-17 fix 2).
    """
    scheme = _scheme()
    scheme.questions[0].answer_points[0].marks_defaulted = True

    rows = derive_point_rows(_corrected(), scheme)

    assert rows[0]["tariff_defaulted"] is True
    assert rows[1]["tariff_defaulted"] is False


def test_alternative_and_optional_flags_are_carried_from_the_scheme() -> None:
    """OR-group / pool membership must survive onto the ledger row, since the

    ledger's ``tariff``/``awarded`` alone cannot say whether summing them
    should match ``awarded_marks`` (spec 2026-09-17 fix 3).
    """
    scheme = _scheme()
    scheme.questions[0].answer_points[1].is_alternative = True
    scheme.questions[0].answer_points[2].is_optional = True

    rows = derive_point_rows(_corrected(), scheme)

    assert rows[0]["is_alternative"] is False
    assert rows[0]["is_optional"] is False
    assert rows[1]["is_alternative"] is True
    assert rows[1]["is_optional"] is False
    assert rows[2]["is_alternative"] is False
    assert rows[2]["is_optional"] is True


# ── group_key / group_max_marks: the scheme's either/or and any-N structure ──
#
# Recorded at derivation time because `is_alternative` only means "an
# alternative to the previous point": the group exists in scheme order and
# nowhere else. `_check_coherence` (lemely/io/correction_ai.py) refuses to
# rebuild it at read time; this is the one place the Question is in hand.


def _points(*specs: tuple[str, int, str]) -> list[AnswerPoint]:
    """``(id, marks, flags)`` where flags is "" / "alt" / "opt"."""
    return [
        AnswerPoint(
            id=pid,
            point=f"Point {pid}",
            marks=marks,
            is_alternative=flags == "alt",
            is_optional=flags == "opt",
        )
        for pid, marks, flags in specs
    ]


def _scheme_with(
    points: list[AnswerPoint], *, marks: int, select_count: int | None = None
) -> MarkScheme:
    """``_scheme()`` with question "1a"'s points, total and select_count replaced."""
    scheme = _scheme()
    question = scheme.questions[0]
    question.answer_points = points
    question.marks = marks
    question.select_count = select_count
    return scheme


def _groups(rows: list[dict[str, object]]) -> list[tuple[object, object]]:
    return [(row["group_key"], row["group_max_marks"]) for row in rows]


def test_independent_points_have_no_group() -> None:
    rows = derive_point_rows(_corrected(), _scheme())
    assert _groups(rows) == [(None, None), (None, None), (None, None)]


def test_an_alternative_joins_the_point_before_it_into_an_either_or_group() -> None:
    """p1 (M) / p2 (A, alternative) is one group worth 1; p3 stays independent."""
    scheme = _scheme()
    scheme.questions[0].answer_points[1].is_alternative = True

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("alt:1", 1), ("alt:1", 1), (None, None)]


def test_both_members_flagged_alternative_is_the_same_group() -> None:
    """Parsers flag either/or pairs both ways round; both encodings must group
    identically (this is the encoding tests/test_self_review_repo.py's
    `_alt_group_scheme` uses)."""
    scheme = _scheme_with(_points(("p1", 1, "alt"), ("p2", 1, "alt"), ("p3", 1, "")), marks=2)

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("alt:1", 1), ("alt:1", 1), (None, None)]


def test_either_or_cap_is_the_best_member_not_the_sum() -> None:
    """Full method (2) OR partial (1): the group is worth 2, not 3."""
    scheme = _scheme_with(_points(("p1", 2, ""), ("p2", 1, "alt"), ("p3", 1, "")), marks=3)

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("alt:1", 2), ("alt:1", 2), (None, None)]


def test_a_lone_flag_is_not_a_group() -> None:
    """A first point flagged alternative with nothing to attach to, and a pool
    of one, are independent points: NULL/NULL, not a one-member group."""
    scheme = _scheme_with(_points(("p1", 1, "alt"), ("p2", 1, ""), ("p3", 1, "opt")), marks=3)

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [(None, None), (None, None), (None, None)]


def test_pool_with_select_count_is_capped_at_the_n_largest_tariffs() -> None:
    """'Any 2 from' four one-mark points on a 4-mark question: the pool is

    worth 2 (the two largest tariffs), not 4 (every tariff) and not
    coincidentally equal to the question's own total — ``marks=4`` keeps
    sum-of-N (2), ``total`` (4) and ``leftover`` (4, no independents here)
    from agreeing by accident, unlike the old ``marks=2`` fixture where all
    three collapsed to the same number (Finding 3)."""
    scheme = _scheme_with(
        _points(("p1", 1, "opt"), ("p2", 1, "opt"), ("p3", 1, "opt"), ("p4", 1, "opt")),
        marks=4,
        select_count=2,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 2)] * 4


def test_pool_select_count_takes_the_largest_tariffs_not_the_first_or_smallest() -> None:
    """Every existing pool test used uniform 1-mark tariffs, so
    ``sorted(..., reverse=True)`` was never exercised (Finding 2): deleting
    the sort, or sorting ascending, passed all of them. A mixed pool where
    the three plausible implementations diverge — largest-two (5), first-two
    in scheme order (1 + 3 = 4), smallest-two (1 + 2 = 3) — catches that. No
    independent point here: mixing one in would let Finding 1's subtraction
    confound what this test measures, so ``total`` (10) is chosen well clear
    of every candidate to isolate the sort."""
    scheme = _scheme_with(
        _points(("p1", 1, "opt"), ("p2", 3, "opt"), ("p3", 2, "opt")),
        marks=10,
        select_count=2,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 5)] * 3


def test_pool_cap_never_exceeds_the_question_total() -> None:
    """select_count=3 on a 2-mark question: the question total wins."""
    scheme = _scheme_with(
        _points(("p1", 1, "opt"), ("p2", 1, "opt"), ("p3", 1, "opt"), ("p4", 1, "opt")),
        marks=2,
        select_count=3,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 2)] * 4


def test_pool_without_select_count_gets_the_marks_the_question_has_left() -> None:
    """One independent point (1) plus a pool of three on a 3-mark question:
    the pool can be worth at most 3 - 1 = 2. Distinguishes the leftover rule
    from 'sum of members' (3) and from 'best member' (1)."""
    scheme = _scheme_with(
        _points(("p1", 1, ""), ("p2", 1, "opt"), ("p3", 1, "opt"), ("p4", 1, "opt")), marks=3
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [(None, None), ("pool:1", 2), ("pool:1", 2), ("pool:1", 2)]


def test_pool_select_count_cap_still_subtracts_independent_and_alt_marks() -> None:
    """Finding 1: the ``select_count`` branch used to cap the pool at
    ``min(total, sum of the N largest tariffs)``, ignoring what independent
    points had already spent — so a low-confidence question could be granted
    every pool point even though the question had no room left for them.
    p1 is independent worth 2; p2/p3/p4 are a 'any 3 from' pool worth 1 each
    on a 3-mark question. The unsubtracted formula gives 3 (sum of all three
    tariffs, which is also ``total``); the question actually has only
    3 - 2 == 1 mark of room left once p1's independent 2 is spent."""
    scheme = _scheme_with(
        _points(("p1", 2, ""), ("p2", 1, "opt"), ("p3", 1, "opt"), ("p4", 1, "opt")),
        marks=3,
        select_count=3,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [(None, None), ("pool:1", 1), ("pool:1", 1), ("pool:1", 1)]


def test_two_pools_without_a_select_count_do_not_share_the_leftover() -> None:
    """Triage F5 (user decision, 2026-09-29). A pool whose N is unstated used
    to take the whole leftover and leave a later pool capped at 0, so a
    student earning two marks in each of two pools got 4/6 with no review
    flag (``probe_marking.py``, case F5). Each such pool is now worth
    min(leftover, its own tariffs) = min(4 - 1, 2) = 2, the leftover NOT
    consumed by the earlier pool; the question-level clamp in the consumers
    bounds the total.
    """
    scheme = _scheme_with(
        _points(
            ("p1", 1, "opt"),
            ("p2", 1, "opt"),
            ("p3", 1, ""),
            ("p4", 1, "opt"),
            ("p5", 1, "opt"),
        ),
        marks=4,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [
        ("pool:1", 2),
        ("pool:1", 2),
        (None, None),
        ("pool:2", 2),
        ("pool:2", 2),
    ]


def test_a_pool_without_a_select_count_never_exceeds_the_question() -> None:
    scheme = _scheme_with(_points(("p1", 2, "opt"), ("p2", 2, "opt"), ("p3", 2, "opt")), marks=4)

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 4)] * 3


def test_a_pool_with_a_select_count_still_shares_the_leftover() -> None:
    """The stated-N rule is unchanged: ``min(pool_room, N largest tariffs)``,
    consumed in scheme order, so a later stated-N pool can still end at 0."""
    scheme = _scheme_with(
        _points(
            ("p1", 1, "opt"), ("p2", 1, "opt"), ("p3", 1, ""), ("p4", 1, "opt"), ("p5", 1, "opt")
        ),
        marks=2,
        select_count=2,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [
        ("pool:1", 1),
        ("pool:1", 1),
        (None, None),
        ("pool:2", 0),
        ("pool:2", 0),
    ]


def test_an_alternative_after_a_pool_member_joins_the_pool() -> None:
    scheme = _scheme_with(
        _points(("p1", 1, "opt"), ("p2", 1, "opt"), ("p3", 1, "alt")), marks=3, select_count=2
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("pool:1", 2)] * 3


def test_two_groups_get_distinct_keys_and_the_leftover_subtracts_the_either_or_cap() -> None:
    """p1|p2 (either/or, worth 1) then a pool p3,p4 with no select_count on a
    3-mark question: the pool's leftover is 3 - 0 (no independents) - 1 (the
    either/or cap) = 2."""
    scheme = _scheme_with(
        _points(("p1", 1, ""), ("p2", 1, "alt"), ("p3", 1, "opt"), ("p4", 1, "opt")), marks=3
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("alt:1", 1), ("alt:1", 1), ("pool:1", 2), ("pool:1", 2)]


def test_two_alt_groups_in_one_question_are_numbered_alt_1_and_alt_2() -> None:
    """Finding 5: every prior either/or test used exactly one group.
    p1|p2 and p3|p4 are two separate either/or runs in the same question;
    they must get distinct, gapless keys (``alt:1``, ``alt:2``), not share
    one key or collide with a later pool's ``pool:1`` numbering."""
    scheme = _scheme_with(
        _points(("p1", 1, ""), ("p2", 1, "alt"), ("p3", 2, ""), ("p4", 1, "alt")), marks=3
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("alt:1", 1), ("alt:1", 1), ("alt:2", 2), ("alt:2", 2)]


def test_stated_n_pool_leftover_is_zero_when_independents_consume_the_whole_total() -> None:
    """Finding 5 (review round): when independent points already claim every
    mark, a pool WITH a ``select_count`` is worth 0 -- it draws on the
    leftover, and the question has nothing left to give."""
    scheme = _scheme_with(
        _points(("p1", 2, ""), ("p2", 1, "opt"), ("p3", 1, "opt")), marks=2, select_count=1
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [(None, None), ("pool:1", 0), ("pool:1", 0)]


def test_pool_leftover_is_zero_when_independents_consume_the_whole_total() -> None:
    """Finding 5: when independent points already claim every mark, a pool
    without a ``select_count`` is worth 0 — no grant in it can ever be
    correct, since the question has nothing left to give. Conservative and
    correct, not previously asserted. Still true under the non-shared
    leftover cap (triage F5, 2026-09-29): min(leftover 0, tariffs 2) = 0."""
    scheme = _scheme_with(_points(("p1", 2, ""), ("p2", 1, "opt"), ("p3", 1, "opt")), marks=2)

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [(None, None), ("pool:1", 0), ("pool:1", 0)]


def test_two_unstated_pools_are_each_bounded_by_the_leftover_independently() -> None:
    """Triage F5 (user decision, 2026-09-29): 6 marks, two independent 1-mark
    points, two unstated pools of five 1-mark points. Leftover 6 - 2 = 4.
    Each pool is worth min(4, 5) = 4 on its own: not 4 then 0 (the old
    shared leftover) and not 5 and 5 (own tariffs capped only at the
    question). The pools together may promise 8 > 4; the consumers'
    question-level clamp bounds the grant at 6."""
    scheme = _scheme_with(
        _points(
            ("i1", 1, ""),
            *((f"a{n}", 1, "opt") for n in range(5)),
            ("i2", 1, ""),
            *((f"b{n}", 1, "opt") for n in range(5)),
        ),
        marks=6,
    )

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [
        (None, None),
        *[("pool:1", 4)] * 5,
        (None, None),
        *[("pool:2", 4)] * 5,
    ]


def test_a_container_question_total_falls_back_to_the_marked_maximum() -> None:
    """`Question.marks == 0` is the scheme's "container" convention; the cap
    then bounds against the marker's `maximum_marks` (3 here) instead of 0."""
    scheme = _scheme_with(_points(("p1", 2, ""), ("p2", 1, "alt")), marks=0)

    rows = derive_point_rows(_corrected(), scheme)

    assert _groups(rows) == [("alt:1", 2), ("alt:1", 2)]


# ── US-045: `verdict` / `evidence_span` / `ecf_applied` ──────────────────────
#
# `PointVerdict` is I6's per-point record. `verdict` distinguishes `withheld`
# from `unverifiable` where `awarded` alone collapses both to `False`; `note`
# is deliberately NOT a second column and instead reuses `rationale` (see
# `derive_point_rows`'s docstring and `QuestionResultPoint.rationale`).


def _verdict_scheme() -> MarkScheme:
    """A scheme whose one question mirrors
    ``tests.test_correction_ai.PointVerdictBuildTests._question`` exactly
    (same id, same two points), so a real ``_build_ai_corrected`` output can
    be looked up against it by ``derive_point_rows``.
    """
    scheme = _scheme()
    scheme.questions[0] = SchemeQuestion(
        id="2",
        marks=2,
        type=SchemeQuestionType.EXPLANATION,
        answer_points=[
            AnswerPoint(id="p1", point="method step", marks=1, math_mark_type=MathMarkType.M),
            AnswerPoint(id="p2", point="final value", marks=1, math_mark_type=MathMarkType.A),
        ],
    )
    return scheme


def test_awarded_matches_the_verdict_over_real_verdict_path_output() -> None:
    """The consistency invariant, proven over ``_build_ai_corrected_from_verdicts``'s
    real output -- not hand-built rows (``probes/README.md``'s rule): wherever
    a point carries a verdict, ``awarded`` must agree with it.
    """
    scheme = _verdict_scheme()
    question = scheme.get_question_by_id("2")
    assert question is not None
    mark = AIMarkResponse(
        awarded_marks=0,  # stale/ignored under the verdict path, as elsewhere
        confidence=0.95,
        matched_point_ids=[],
        feedback="fb",
        point_verdicts=[
            PointVerdict(point_id="p1", verdict="awarded", evidence_span="did the method"),
            PointVerdict(point_id="p2", verdict="withheld", evidence_span=""),
        ],
    )
    cq = _build_ai_corrected(
        question,
        "did the method, answer is 42",
        mark,
        student_working="did the method",
        equivalence_gate=True,
    )
    assert cq.point_verdicts, "the verdict path must actually have run"

    rows = derive_point_rows(cq, scheme)

    by_id = {row["mark_point_id"]: row for row in rows}
    assert by_id["p1"]["verdict"] == "awarded"
    assert by_id["p1"]["awarded"] is True
    assert by_id["p2"]["verdict"] == "withheld"
    assert by_id["p2"]["awarded"] is False
    for row in rows:
        if row["verdict"] is not None:
            assert row["awarded"] == (row["verdict"] == "awarded")


def test_unverifiable_and_withheld_both_read_as_not_awarded_but_verdict_tells_them_apart() -> None:
    """The distinction I6 exists to carry: both collapse to ``awarded=False``,
    but ``verdict`` still tells them apart."""
    scheme = _verdict_scheme()
    question = scheme.get_question_by_id("2")
    assert question is not None
    mark = AIMarkResponse(
        awarded_marks=0,
        confidence=0.95,
        matched_point_ids=[],
        feedback="fb",
        point_verdicts=[
            PointVerdict(point_id="p1", verdict="withheld", evidence_span=""),
            PointVerdict(point_id="p2", verdict="unverifiable", evidence_span=""),
        ],
    )
    cq = _build_ai_corrected(
        question, "attempted", mark, student_working="attempted", equivalence_gate=True
    )

    rows = derive_point_rows(cq, scheme)
    by_id = {row["mark_point_id"]: row for row in rows}
    assert by_id["p1"]["awarded"] is False
    assert by_id["p2"]["awarded"] is False
    assert by_id["p1"]["verdict"] == "withheld"
    assert by_id["p2"]["verdict"] == "unverifiable"


def test_verdict_note_wins_over_point_notes_when_a_verdict_exists_for_the_point() -> None:
    rows = derive_point_rows(
        _corrected(
            point_verdicts=[
                PointVerdict(point_id="p1", verdict="awarded", note="from the verdict")
            ],
            point_notes={"p1": "from point_notes, must lose"},
        ),
        _scheme(),
    )

    assert rows[0]["rationale"] == "from the verdict"


def test_point_notes_is_the_only_source_when_the_point_has_no_verdict() -> None:
    rows = derive_point_rows(
        _corrected(point_notes={"p1": "from point_notes"}),
        _scheme(),
    )

    assert rows[0]["rationale"] == "from point_notes"


def test_both_note_sources_empty_yields_null_rationale() -> None:
    rows = derive_point_rows(
        _corrected(point_verdicts=[PointVerdict(point_id="p1", verdict="awarded")]),
        _scheme(),
    )

    assert rows[0]["rationale"] is None


def test_a_point_with_no_verdict_gets_the_column_defaults() -> None:
    """No ``point_verdicts`` at all (the legacy path): every point gets
    ``verdict=None``, matching ``QuestionResultPoint``'s nullable column, and
    ``evidence_span``/``ecf_applied`` at the same defaults their columns
    carry (``''``/``False``), not ``None``."""
    rows = derive_point_rows(_corrected(), _scheme())

    for row in rows:
        assert row["verdict"] is None
        assert row["evidence_span"] == ""
        assert row["ecf_applied"] is False


def test_evidence_span_and_ecf_applied_are_carried_from_the_verdict() -> None:
    rows = derive_point_rows(
        _corrected(
            point_verdicts=[
                PointVerdict(
                    point_id="p1",
                    verdict="awarded",
                    evidence_span="12.5 m/s",
                    ecf_applied=True,
                )
            ]
        ),
        _scheme(),
    )

    assert rows[0]["evidence_span"] == "12.5 m/s"
    assert rows[0]["ecf_applied"] is True
    # p2/p3 carry no verdict: defaults, not the first point's values.
    assert rows[1]["evidence_span"] == ""
    assert rows[1]["ecf_applied"] is False


def test_group_capped_points_total_caps_each_group_then_clamps_only_when_asked() -> None:
    """``lemely.core.point_groups.group_capped_points_total`` directly: an
    independent point adds its tariff, a group adds ``min(cap, its tariffs)``
    (either/or cap 1 holding two awarded 1-mark members to 1, a pool cap 2
    holding three to 2), and ``total`` clamps the sum -- or, as ``None``,
    leaves the raw per-group figure the self-review upward step needs."""
    from lemely.core.point_groups import group_capped_points_total

    awarded = [
        (2, None, None),
        (1, "alt:1", 1),
        (1, "alt:1", 1),
        (1, "pool:1", 2),
        (1, "pool:1", 2),
        (1, "pool:1", 2),
    ]
    assert group_capped_points_total(awarded, total=None) == 2 + 1 + 2
    assert group_capped_points_total(awarded, total=4) == 4
    assert group_capped_points_total(awarded, total=10) == 5
    assert group_capped_points_total([], total=None) == 0
    # No producer writes a named group without a cap; it counts 0.
    assert group_capped_points_total([(3, "alt:9", None)], total=None) == 0
