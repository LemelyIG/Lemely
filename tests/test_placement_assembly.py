"""Placement assembly: the budget, the breadth rule, and the refusals (P4.4, D4.6 §5).

Pure-function tests — no database. The point of each is a rule that D4.6 §5
chose deliberately and that a later "small tidy-up" could silently undo:
duration is derived from transcribed marks, an untopiced question is
ineligible rather than counted, and a set that misses the viability floor is
*refused with a reason* rather than shipped short or padded.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterator

import pytest

from lemely.core.placement import (
    Assembly,
    Candidate,
    PaperTiming,
    Unavailable,
    UnavailableReason,
    assemble,
    estimated_minutes_for,
)
from lemely.io.paper_timing import get_paper_timings, load_paper_timings

# 0625 Paper 4: 75 minutes / 80 marks -> 0.9375 min per mark.
P4 = PaperTiming(
    board="caie",
    subject_code="0625",
    paper_number=4,
    duration_minutes=75,
    total_marks=80,
    practical=False,
    source_document="595430-2023-2025-syllabus.pdf",
    syllabus_version="2023-2025",
)
TIMINGS = {4: P4}


#: Candidate ids are handed out in creation order and reset before every test
#: (see :func:`_reset_candidate_ids`), so a pool is byte-identical from run to
#: run. ``uuid.uuid4()`` here used to make this module genuinely random:
#: :func:`~lemely.core.placement.assemble` breaks a tie on
#: ``str(question_bank_id)``, and in a pool where every candidate carries the
#: same marks the primary key ``abs(estimated_minutes - share)`` ties for
#: *every* option — so the pick was decided by a random UUID string sort and
#: roughly 1 run in 30 selected a different set (measured, not estimated).
_next_id = itertools.count()


@pytest.fixture(autouse=True)
def _reset_candidate_ids() -> Iterator[None]:
    """Restart the id counter per test, so ids never depend on test order."""
    global _next_id
    _next_id = itertools.count()
    yield


def _c(topic: str | None, marks: int, *, paper: int | None = 4, band: str = "medium") -> Candidate:
    return Candidate(
        question_bank_id=uuid.UUID(int=next(_next_id)),
        topic=topic,
        paper_number=paper,
        total_marks=marks,
        difficulty=band,
    )


def _spread(topics: int, per_topic: int, marks: int = 2) -> list[Candidate]:
    """A pool of ``marks``-mark leaves. 2 marks is the shape of a real
    past-paper leaf on 0625 Paper 4 (1.875 min each at the transcribed rate),
    so the default keeps these tests measuring the algorithm rather than an
    unrealistic question size."""
    return [
        _c(f"{i + 1}.1 Topic {i + 1}", marks, band="easy" if n % 2 else "hard")
        for i in range(topics)
        for n in range(per_topic)
    ]


# ── The rate is computed from transcribed facts ──────────────────────────


def test_the_rate_is_derived_from_the_two_transcribed_numbers() -> None:
    """No minutes-per-mark figure is stored anywhere — it is division, on read."""
    assert P4.minutes_per_mark == 75 / 80


def test_the_bundled_data_file_stores_no_derived_rate() -> None:
    """The guard on D4.6 §5's central promise: every number on disk is checkable
    against the syllabus. A ``minutes_per_mark`` key appearing here would be a
    guess acquiring the authority of a fact."""
    import json

    from lemely.data import DATA_DIR

    payload = json.loads((DATA_DIR / "paper_timing.json").read_text(encoding="utf-8"))
    for record in payload["papers"]:
        assert set(record) == {
            "board",
            "subject_code",
            "paper_number",
            "name",
            "duration_minutes",
            "total_marks",
            "practical",
            "source",
        }
        assert record["source"]["document"]
        assert record["source"]["syllabus_version"]


def test_practical_papers_are_excluded_from_placement_by_default() -> None:
    """0625 Paper 5/6 need apparatus; an at-home placement test cannot use them.

    The timings are still transcribed and reachable — this is assembly policy,
    not a claim the data is wrong.
    """
    assert set(get_paper_timings("0625")) == {1, 2, 3, 4}
    assert set(get_paper_timings("0625", include_practical=True)) == {1, 2, 3, 4, 5, 6}
    assert load_paper_timings()[("caie", "0625")][5].practical is True


def test_a_subject_with_no_transcribed_overview_yields_no_timings() -> None:
    assert get_paper_timings("9999") == {}


# ── Assembly: the budget and the breadth rule ────────────────────────────


def test_a_broad_pool_assembles_inside_the_budget() -> None:
    result = assemble(_spread(topics=6, per_topic=3), TIMINGS)

    assert isinstance(result, Assembly)
    assert 12.0 <= result.estimated_minutes <= 18.0
    assert len(result.topics) >= 4
    assert result.question_count >= 6
    # No band assertion here on purpose — see TestBandSpread. This test is about
    # the budget, and `assemble` has no band-spread rule to assert against.


class TestBandSpread:
    """What ``Assembly.spans_multiple_bands`` actually reports (D4.20).

    This class replaces an ``assert result.spans_multiple_bands is True`` that
    sat in :func:`test_a_broad_pool_assembles_inside_the_budget` from
    ``5809814`` until D4.20. That assertion was wrong twice over:

    1. **``assemble`` has no band-spread rule.** It selects breadth-first
       across top-level topics and breaks ties on nearest-to-even-share; it
       never reads ``Candidate.difficulty``. Nothing in it can guarantee two
       bands, so the assertion pinned a behaviour that was never implemented
       and passed on the luck of a random-UUID tie-break.
    2. **``spans_multiple_bands`` is designed to be False sometimes.** It is
       the flag that stops S-05 inventing a working-level estimate from a
       sample drawn from one band (see the property's own docstring). Pinning
       it True on a broad pool asserts against its stated purpose.

    So the honest contract is: it *reports* the bands present in the selected
    set. Both outcomes are legitimate, and S-05 must handle False.

    **Measured on the live 0625 corpus at D4.20** (248 servable rows after the
    P4.8 chunk-0 renderable filter, E2E seed fixtures excluded): placement
    assembles 10 questions / 17.06 min / 6 syllabus topics, of which 6 are
    ``foundation`` and 4 ``standard`` — so ``spans_multiple_bands`` is True
    today and S-05 does show a working level. That is a property of the
    corpus's mark distribution, not a guarantee of the algorithm, which is
    exactly why it is recorded here as a measurement rather than asserted.
    """

    def test_it_is_true_when_the_selected_set_holds_more_than_one_band(self) -> None:
        pool = [
            # 3 marks: six of them is 16.875 min, inside the 12-18 window. At 2
            # marks the pool totals 11.25 and is refused on duration, so the
            # band flag would never be reached.
            _c(f"{i + 1}.1 Topic {i + 1}", 3, band="easy" if i % 2 else "hard")
            for i in range(6)
        ]

        result = assemble(pool, TIMINGS)

        assert isinstance(result, Assembly)
        assert {s.candidate.difficulty for s in result.selected} == {"easy", "hard"}
        assert result.spans_multiple_bands is True

    def test_it_is_false_when_a_viable_set_happens_to_be_single_band(self) -> None:
        """The inverse, and the one the deleted assertion denied could happen.

        A perfectly viable placement test — enough questions, enough topics,
        inside the budget — drawn entirely from one band. ``assemble`` accepts
        it, because breadth across the syllabus is what it is required to
        deliver; the flag is what tells S-05 to keep quiet about a level.
        """
        pool = [_c(f"{i + 1}.1 Topic {i + 1}", 3, band="hard") for i in range(6)]

        result = assemble(pool, TIMINGS)

        assert isinstance(result, Assembly)
        assert result.question_count >= 6
        assert result.syllabus_topic_count == 6
        assert result.spans_multiple_bands is False


def test_breadth_comes_before_depth() -> None:
    """Every topic is visited once before any topic is visited twice.

    Otherwise a placement test can spend its whole budget inside one topic and
    return a "profile" of a single corner of the syllabus.

    Asserted on the *counts*, not on the output sequence: ``selected`` is
    deliberately returned grouped by topic in syllabus order (a sensible order
    to sit the paper in), so selection order is not observable from it. What is
    observable — and what breadth actually means — is that no topic gets a
    second question until every topic has had a first.
    """
    result = assemble(_spread(topics=5, per_topic=4), TIMINGS)

    assert isinstance(result, Assembly)
    counts: dict[str, int] = {}
    for selection in result.selected:
        topic = selection.candidate.topic
        assert topic is not None
        counts[topic] = counts.get(topic, 0) + 1
    assert len(counts) == 5
    assert max(counts.values()) - min(counts.values()) <= 1


def test_topics_are_ordered_by_syllabus_code_not_lexically() -> None:
    """``"10.1"`` must not sort before ``"2.1"``."""
    pool = [_c(f"{code} Topic", 2) for code in ("10.1", "2.1", "1.3", "1.10", "3.2")]
    result = assemble(pool, TIMINGS, min_questions=5, min_minutes=1.0)

    assert isinstance(result, Assembly)
    assert result.topics == ["1.3 Topic", "1.10 Topic", "2.1 Topic", "3.2 Topic", "10.1 Topic"]


def test_a_single_question_that_blows_the_budget_is_never_selected() -> None:
    """A 40-mark question is 37.5 minutes on its own; it cannot be part of a
    ~15-minute test, and leaving it in the pool would stall the greedy fill."""
    pool = [*_spread(topics=4, per_topic=3), _c("9.9 Enormous", 40)]
    result = assemble(pool, TIMINGS)

    assert isinstance(result, Assembly)
    assert all(s.candidate.total_marks != 40 for s in result.selected)


def test_assembly_is_deterministic() -> None:
    pool = _spread(topics=6, per_topic=3)
    first = assemble(pool, TIMINGS)
    second = assemble(pool, TIMINGS)

    assert isinstance(first, Assembly)
    assert isinstance(second, Assembly)
    assert [s.candidate.question_bank_id for s in first.selected] == [
        s.candidate.question_bank_id for s in second.selected
    ]


def test_a_retake_never_reuses_a_question_the_student_has_already_seen() -> None:
    pool = _spread(topics=6, per_topic=3)
    first = assemble(pool, TIMINGS)
    assert isinstance(first, Assembly)
    seen = frozenset(s.candidate.question_bank_id for s in first.selected)

    second = assemble(pool, TIMINGS, exclude_bank_ids=seen)

    assert isinstance(second, Assembly)
    assert not seen & {s.candidate.question_bank_id for s in second.selected}


def test_subtopics_of_one_topic_do_not_count_as_breadth() -> None:
    """Eight subtopics of physics topic 1 are one topic, not eight.

    D4.2's classifier writes whichever level it matched, so the bank holds a
    mix of ``"3 Waves"`` and ``"1.2 Motion"``. Counting those as peers is how a
    measurement against the real 0625 bank reported "13 topics" for a set whose
    nine questions all sat under topic 1 — broad by the counter, narrow in
    fact. Breadth is measured on the top-level code for exactly that reason.
    """
    pool = [_c(f"1.{i} Sub {i}", 2) for i in range(1, 9) for _ in range(3)]
    result = assemble(pool, TIMINGS)

    assert isinstance(result, Unavailable)
    assert result.reason is UnavailableReason.insufficient_topics
    assert result.eligible_topics == 1


def test_breadth_spreads_across_top_level_topics_then_across_subtopics() -> None:
    """Four topics, three subtopics each: every topic represented, and within a
    topic the questions come from different subtopics rather than drilling
    into the first one."""
    pool = [_c(f"{t}.{s} Sub", 2) for t in range(1, 5) for s in range(1, 4) for _ in range(2)]
    result = assemble(pool, TIMINGS)

    assert isinstance(result, Assembly)
    assert result.syllabus_topic_count == 4
    assert len(result.topics) > 4, "a second question in a topic should pick a new subtopic"


# ── The refusals: short is refused, never padded (UI spec §1.4) ──────────


def test_an_empty_pool_is_no_questions() -> None:
    result = assemble([], TIMINGS)
    assert isinstance(result, Unavailable)
    assert result.reason is UnavailableReason.no_questions


@pytest.mark.parametrize(
    ("pool", "why"),
    [
        ([_c(None, 4) for _ in range(20)], "untopiced"),
        ([_c("1.1 T", 4, paper=None) for _ in range(20)], "no paper"),
        ([_c("1.1 T", 4, paper=9) for _ in range(20)], "paper has no transcribed timing"),
    ],
)
def test_a_pool_filtered_to_nothing_is_distinguished_from_an_empty_one(
    pool: list[Candidate], why: str
) -> None:
    """``no_eligible_questions`` vs ``no_questions``: the fix differs — classify
    or transcribe, versus ingest. A single reason would tell S-03 nothing."""
    result = assemble(pool, TIMINGS)
    assert isinstance(result, Unavailable), why
    assert result.reason is UnavailableReason.no_eligible_questions


def test_a_narrow_pool_is_refused_rather_than_shipped() -> None:
    """Three topics is below the floor. The alternative — returning it anyway —
    would produce a weakness profile of three topics presented as a profile of
    the subject."""
    result = assemble(_spread(topics=3, per_topic=6), TIMINGS)

    assert isinstance(result, Unavailable)
    assert result.reason is UnavailableReason.insufficient_topics
    assert result.eligible_topics == 3
    assert result.eligible_questions == 18


def test_a_pool_too_short_to_fill_the_budget_is_refused() -> None:
    """Four topics, one 1-mark question each: 3.75 minutes. Padding it to 15
    would mean repeating questions or inventing them."""
    result = assemble(_spread(topics=4, per_topic=1, marks=1), TIMINGS)

    assert isinstance(result, Unavailable)
    assert result.reason in {
        UnavailableReason.insufficient_questions,
        UnavailableReason.insufficient_duration,
    }
    assert result.estimated_minutes < 12.0


# ── The read-time estimate (D4.6 §5) ─────────────────────────────────────


def test_the_displayed_estimate_is_recomputed_from_frozen_marks() -> None:
    """Stored nowhere, so it stays true if a question is later removed."""
    assert estimated_minutes_for([4, 8], [4, 4], TIMINGS) == pytest.approx(12 * 0.9375)
    assert estimated_minutes_for([4], [4], TIMINGS) == pytest.approx(4 * 0.9375)


def test_a_question_with_no_timing_contributes_zero_not_a_guessed_average() -> None:
    assert estimated_minutes_for([4, 8], [4, None], TIMINGS) == pytest.approx(4 * 0.9375)
    assert estimated_minutes_for([4, 8], [4, 99], TIMINGS) == pytest.approx(4 * 0.9375)
