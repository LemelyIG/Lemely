"""Unit tests for the pure/derivable parts of ``scripts/seed_e2e.py`` (P3.10 chunks a/e1).

Everything here is hermetic — no DB, no GoTrue, no wall clock (every scenario
supplies its own fixed ``now``), mirroring ``tests/test_at_risk.py``'s style.
The impure ``seed()`` orchestration (real GoTrue/Postgres I/O) is deliberately
NOT exercised here: verifying it needs the live migrated stack, and running a
full multi-role signup + OTP + attempt-persist flow on every ``pytest``
invocation would seed real demo rows every time a developer runs the suite
with the stack up — the opposite of what a seed script is for. That flow was
verified manually against the live stack (see the P3.10a / P3.10e1 chunk
reports).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
import sqlalchemy as sa

from lemely.core.at_risk import (
    AtRiskReason,
    BelowTargetEvidence,
    TargetRuleStatus,
    assess_at_risk,
)
from lemely.core.booking import EffectiveState, effective_state, is_late_cancel
from lemely.core.difficulty import allocate_difficulty
from lemely.core.history import GRADE_ORDER, StudentHistory, is_grade_bearing
from lemely.core.placement import MIN_QUESTIONS, MIN_TOPICS
from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD, ConfidenceBand
from lemely.core.tutor_outcomes import (
    DURING_WINDOW,
    OUTCOME_K_MIN,
    close_instant,
    outcome_for_subject,
)
from lemely.db.models.enums import QuestionSource, Role
from lemely.db.models.tutoring import (
    TutorAccessAudit,
    TutorBooking,
    TutorBookingNote,
    TutorDataGrant,
    TutoringReport,
    TutorProfile,
)
from lemely.db.models.users import ParentChildLink, User
from lemely.db.tutor_outcomes_repo import TutorOutcomesRepository
from lemely.db.tutoring_predicates import EFFECTIVE_STATE_SQL
from scripts.seed_e2e import (
    BELOW_TARGET_GRADE,
    BELOW_TARGET_POSITIONS_BELOW,
    BELOW_TARGET_SCORE,
    CONTROL_SCORES,
    CORRECTED_SCORE,
    DECLINING_DAYS_AGO,
    DECLINING_SCORES,
    INACTIVE_SCORE,
    LEGACY_REVIEW_CONFIDENCE_SCORE,
    LEGACY_REVIEW_DAYS_AGO,
    LEGACY_REVIEW_SCORE,
    PLACEMENT_MATHS_SAMPLE,
    PLACEMENT_MCQ_ANSWER,
    PLACEMENT_PAPER_NUMBER,
    PLACEMENT_QUESTION_MARKS,
    PLACEMENT_QUESTIONS_PER_TOPIC,
    PLACEMENT_SUBJECT_CODE,
    PLACEMENT_TOPICS,
    PRACTICE_SET_COUNT,
    QUIZ_BANK_ANSWERS,
    QUIZ_BANK_BANDS,
    QUIZ_REQUESTED_COUNT,
    RATIONALE_ONLY_REVIEW_CONFIDENCE_SCORE,
    RATIONALE_ONLY_REVIEW_SCORE,
    REVIEW_ITEM_CONFIDENCE_SCORE,
    SUBJECT_CODE,
    TUTORING_BOOKING_PLAN,
    TUTORING_INSUFFICIENT_COHORT,
    TUTORING_SUBJECT_CODE,
    TUTORING_SUFFICIENT_COHORT,
    TutoringSeedAccounts,
    accuracy_report_for_score,
    below_target_recorded_at,
    build_email,
    build_password,
    build_placement_bank_questions,
    build_placement_paper_stem,
    build_quiz_bank_questions,
    build_result_payload,
    control_recorded_ats,
    corrected_recorded_at,
    declining_recorded_ats,
    default_run_tag,
    inactive_recorded_at,
    is_placement_seed_prompt,
    legacy_review_recorded_at,
    legacy_review_scheme,
    paper_record_for_scenario,
    seed_tutoring_fixture,
    tutoring_booking_times,
    tutoring_cohort_inputs,
    tutoring_expected_outcome,
    tutoring_session_start,
    wrong_mcq_answer,
)

_NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
_TEACHER_ID = uuid.UUID("6f6d8b0e-8c7b-4a0b-9d0a-000000000001")


# ---------------------------------------------------------------------------
# Identity/credential builders.
# ---------------------------------------------------------------------------


class TestCredentialBuilders:
    def test_build_email_is_namespaced_by_role_and_tag(self) -> None:
        assert build_email("teacher", "abc123") == "teacher-abc123@e2e.lemely.local"

    def test_build_email_differs_across_roles_for_the_same_tag(self) -> None:
        assert build_email("teacher", "abc123") != build_email("admin", "abc123")

    def test_build_password_differs_across_tags(self) -> None:
        assert build_password("tag1") != build_password("tag2")

    def test_build_password_is_deterministic(self) -> None:
        assert build_password("tag1") == build_password("tag1")

    def test_default_run_tag_is_unique_per_call(self) -> None:
        tags = {default_run_tag() for _ in range(20)}
        assert len(tags) == 20

    def test_default_run_tag_is_lowercase_hex(self) -> None:
        tag = default_run_tag()
        assert len(tag) == 12
        int(tag, 16)  # raises ValueError if not valid hex


# ---------------------------------------------------------------------------
# Date arithmetic.
# ---------------------------------------------------------------------------


class TestDateArithmetic:
    def test_declining_recorded_ats_are_oldest_first(self) -> None:
        ats = declining_recorded_ats(_NOW)
        assert ats == sorted(ats)
        assert len(ats) == len(DECLINING_DAYS_AGO) == 3

    def test_declining_recorded_ats_match_days_ago(self) -> None:
        ats = declining_recorded_ats(_NOW)
        for at, days_ago in zip(ats, DECLINING_DAYS_AGO, strict=True):
            assert (_NOW - at).days == days_ago

    def test_control_recorded_ats_are_oldest_first_and_recent(self) -> None:
        ats = control_recorded_ats(_NOW)
        assert ats == sorted(ats)
        assert all((_NOW - at).days < 14 for at in ats)

    def test_inactive_recorded_at_is_at_least_14_days_ago(self) -> None:
        at = inactive_recorded_at(_NOW)
        assert (_NOW - at).days >= 14

    def test_corrected_recorded_at_is_recent(self) -> None:
        at = corrected_recorded_at(_NOW)
        assert (_NOW - at).days < 14

    def test_below_target_recorded_at_is_recent(self) -> None:
        """Recent is what keeps rule 3 out of this account's flag list."""
        at = below_target_recorded_at(_NOW)
        assert (_NOW - at).days < 14

    def test_legacy_review_recorded_at_is_recent(self) -> None:
        """Recent, and the account's only attempt -- neither the inactive nor
        the declining-trend rule can ever fire on this student (task #67)."""
        at = legacy_review_recorded_at(_NOW)
        assert (_NOW - at).days < 14
        assert (_NOW - at).days == LEGACY_REVIEW_DAYS_AGO


# ---------------------------------------------------------------------------
# Scenario proof — feed the exact scores/dates the real seed persists into
# ``assess_at_risk`` directly, with no DB in the loop, and prove each fires
# (or doesn't) exactly as the seed's docstring claims.
# ---------------------------------------------------------------------------


class TestScenariosFireCorrectly:
    def test_declining_scenario_fires_declining_trend_only(self) -> None:
        records = [
            paper_record_for_scenario("declining", score, at, paper_number=i + 1)
            for i, (score, at) in enumerate(
                zip(DECLINING_SCORES, declining_recorded_ats(_NOW), strict=True)
            )
        ]
        history = StudentHistory(student_id="declining", records=records)
        assessment = assess_at_risk(history, now=_NOW)
        reasons = {flag.reason for flag in assessment.flags}
        assert reasons == {AtRiskReason.DECLINING_TREND}

    def test_declining_run_is_a_single_subject(self) -> None:
        """Rule 1 reads the last 3 grade-bearing records across ALL subjects —
        a second subject interleaved into this run would stop it firing."""
        records = [
            paper_record_for_scenario("declining", score, at, paper_number=i + 1)
            for i, (score, at) in enumerate(
                zip(DECLINING_SCORES, declining_recorded_ats(_NOW), strict=True)
            )
        ]
        assert {r.metadata.subject_code for r in records} == {SUBJECT_CODE}

    def test_inactive_scenario_fires_inactive_only(self) -> None:
        record = paper_record_for_scenario(
            "inactive", INACTIVE_SCORE, inactive_recorded_at(_NOW), paper_number=1
        )
        history = StudentHistory(student_id="inactive", records=[record])
        assessment = assess_at_risk(history, now=_NOW)
        reasons = {flag.reason for flag in assessment.flags}
        assert reasons == {AtRiskReason.INACTIVE}

    def test_control_scenario_is_never_flagged(self) -> None:
        records = [
            paper_record_for_scenario("control", score, at, paper_number=i + 1)
            for i, (score, at) in enumerate(
                zip(CONTROL_SCORES, control_recorded_ats(_NOW), strict=True)
            )
        ]
        history = StudentHistory(student_id="control", records=records)
        assessment = assess_at_risk(history, now=_NOW)
        assert assessment.flags == []
        assert not assessment.is_at_risk

    def test_corrected_paper_record_is_grade_bearing(self) -> None:
        record = paper_record_for_scenario(
            "corrected", CORRECTED_SCORE, corrected_recorded_at(_NOW), paper_number=1
        )
        assert is_grade_bearing(record)

    def _below_target_history(self) -> StudentHistory:
        record = paper_record_for_scenario(
            "below-target", BELOW_TARGET_SCORE, below_target_recorded_at(_NOW), paper_number=1
        )
        return StudentHistory(student_id="below-target", records=[record])

    def test_below_target_scenario_fires_below_target_only(self) -> None:
        assessment = assess_at_risk(
            self._below_target_history(),
            now=_NOW,
            targets={SUBJECT_CODE: BELOW_TARGET_GRADE},
        )
        reasons = {flag.reason for flag in assessment.flags}
        assert reasons == {AtRiskReason.BELOW_TARGET}
        assert assessment.target_rule_status is TargetRuleStatus.FIRED

    def test_below_target_gap_is_the_published_number(self) -> None:
        """`BELOW_TARGET_POSITIONS_BELOW` is asserted by the E2E spec against the
        rendered sentence, so it must be what the engine actually computes —
        not a hand-maintained comment that can drift off the ladder."""
        assessment = assess_at_risk(
            self._below_target_history(),
            now=_NOW,
            targets={SUBJECT_CODE: BELOW_TARGET_GRADE},
        )
        (flag,) = assessment.flags
        evidence = flag.evidence
        assert isinstance(evidence, BelowTargetEvidence)
        assert evidence.positions_below == BELOW_TARGET_POSITIONS_BELOW
        assert evidence.target_grade == BELOW_TARGET_GRADE
        assert evidence.predicted_grade == BELOW_TARGET_SCORE[1]

    def test_below_target_scenario_needs_its_target_to_fire(self) -> None:
        """The inverse. Without a target for THIS subject the rule is not
        evaluable — never a silent 'checked and clean' — so a seed that keyed
        the target on the wrong subject would fail as an unflagged student
        rather than loudly. This is what pins the seed's subject choice."""
        history = self._below_target_history()

        no_targets = assess_at_risk(history, now=_NOW)
        assert no_targets.flags == []
        assert no_targets.target_rule_status is TargetRuleStatus.NOT_EVALUABLE

        wrong_subject = assess_at_risk(history, now=_NOW, targets={"0580": BELOW_TARGET_GRADE})
        assert wrong_subject.flags == []
        assert wrong_subject.target_rule_status is TargetRuleStatus.NOT_EVALUABLE

    def test_below_target_gap_clears_the_threshold_with_room(self) -> None:
        """A target one position closer must still fire; the fixture is not
        sitting exactly on `_TARGET_GAP_POSITIONS`."""
        closer_target = GRADE_ORDER[GRADE_ORDER.index(BELOW_TARGET_GRADE) + 1]
        assessment = assess_at_risk(
            self._below_target_history(), now=_NOW, targets={SUBJECT_CODE: closer_target}
        )
        assert {flag.reason for flag in assessment.flags} == {AtRiskReason.BELOW_TARGET}


# ---------------------------------------------------------------------------
# accuracy_report_for_score — what actually gets persisted.
# ---------------------------------------------------------------------------


class TestAccuracyReportForScore:
    def test_carries_the_exact_percentage_and_grade(self) -> None:
        report = accuracy_report_for_score((66.5, "C"), paper_number=2)
        assert report.grade_prediction.percentage == 66.5
        assert report.grade_prediction.grade == "C"

    def test_uses_the_single_shared_subject_code(self) -> None:
        report = accuracy_report_for_score((66.5, "C"), paper_number=2)
        assert report.correction.metadata.subject_code == SUBJECT_CODE

    def test_paper_number_is_threaded_through(self) -> None:
        report = accuracy_report_for_score((50.0, "D"), paper_number=3)
        assert report.correction.metadata.paper_number == 3

    def test_never_needs_teacher_review(self) -> None:
        """A seed attempt must never land in the review queue — it isn't
        exercising that surface and would just be noise there."""
        report = accuracy_report_for_score((10.0, "U"), paper_number=1)
        assert report.correction.needs_teacher_review is False

    def test_default_confidence_is_the_review_suppressing_shape(self) -> None:
        """Every scenario call relies on these defaults — pinned explicitly so
        a future signature change can't silently flip them."""
        report = accuracy_report_for_score((66.5, "C"), paper_number=2)
        question = report.correction.questions[0]
        assert question.confidence == ConfidenceBand.HIGH
        assert question.confidence_score == 0.95
        assert question.needs_teacher_review is False
        assert question.review_reason is None

    def test_low_confidence_override_carries_the_score_and_needs_review(self) -> None:
        """The exact override P3.10 chunk e1 uses for the ``inactive`` student —
        the score/grade must be untouched even though confidence is not."""
        report = accuracy_report_for_score(
            INACTIVE_SCORE,
            paper_number=1,
            confidence=ConfidenceBand.LOW,
            confidence_score=REVIEW_ITEM_CONFIDENCE_SCORE,
            needs_teacher_review=True,
        )
        question = report.correction.questions[0]
        assert question.confidence == ConfidenceBand.LOW
        assert question.confidence_score == REVIEW_ITEM_CONFIDENCE_SCORE
        assert question.needs_teacher_review is True
        assert question.review_reason is not None
        assert report.correction.needs_teacher_review is True
        # Score/grade untouched — same pair INACTIVE_SCORE always carries.
        assert report.grade_prediction.percentage == INACTIVE_SCORE[0]
        assert report.grade_prediction.grade == INACTIVE_SCORE[1]

    def test_review_item_confidence_is_genuinely_below_the_review_threshold(self) -> None:
        """Verified by construction, not asserted: if this constant ever drifts
        to/above the threshold, the seed's low-confidence attempt would stop
        landing in the review queue and T-08 would silently lose its only
        seeded item."""
        assert REVIEW_ITEM_CONFIDENCE_SCORE < REVIEW_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# The quiz's question-bank supply (P3.10 chunk e1).
# ---------------------------------------------------------------------------


class TestQuizBankSupply:
    def test_bank_bands_supply_exactly_what_the_allocator_needs(self) -> None:
        """QUIZ_BANK_BANDS must supply >= what allocate_difficulty(None,
        QUIZ_REQUESTED_COUNT) asks for in every band, or generate_questions
        reports a real shortfall — proven against the actual allocator, not a
        hand-copied expectation that could drift from it."""
        from collections import Counter

        needed = allocate_difficulty(None, QUIZ_REQUESTED_COUNT)
        supply = Counter(QUIZ_BANK_BANDS)
        for band, count in needed.items():
            assert supply.get(band, 0) >= count

    def test_bank_bands_and_answers_are_the_same_length(self) -> None:
        assert len(QUIZ_BANK_BANDS) == len(QUIZ_BANK_ANSWERS) == QUIZ_REQUESTED_COUNT

    def test_build_quiz_bank_questions_returns_one_row_per_band_answer_pair(self) -> None:
        rows = build_quiz_bank_questions(_TEACHER_ID)
        assert len(rows) == QUIZ_REQUESTED_COUNT
        assert [r.difficulty for r in rows] == QUIZ_BANK_BANDS
        assert [r.mcq_answer for r in rows] == QUIZ_BANK_ANSWERS

    def test_build_quiz_bank_questions_are_all_mcq_owned_by_the_teacher(self) -> None:
        rows = build_quiz_bank_questions(_TEACHER_ID)
        for row in rows:
            assert row.question_type == "mcq"
            assert row.owner_id == _TEACHER_ID
            assert row.paper_id is None
            assert row.source == QuestionSource.generated
            assert row.subject_code == SUBJECT_CODE
            # MCQ rows carry no mark-scheme-point text (quiz_marking_repo's
            # _split_marks_evenly documents point_count=0 as the normal MCQ shape).
            assert row.mark_scheme_points == []

    def test_build_quiz_bank_questions_prompts_are_distinct(self) -> None:
        rows = build_quiz_bank_questions(_TEACHER_ID)
        assert len({r.prompt for r in rows}) == QUIZ_REQUESTED_COUNT


# ---------------------------------------------------------------------------
# build_placement_bank_questions — P4.8 chunk C's placement-eligible bank.
# ---------------------------------------------------------------------------


class TestBuildPlacementPaperStem:
    def test_is_deterministic(self) -> None:
        assert build_placement_paper_stem("tag1") == build_placement_paper_stem("tag1")

    def test_differs_across_run_tags(self) -> None:
        """A distinct stem per run is *usually* produced, and that is all this
        asserts. It is **not** the rerun-safety guarantee: only the tag's first
        two characters reach the year, so distinct tags can and do share a stem
        (see ``TestBuildPlacementBankQuestions``'s stem-collision test).
        Uniqueness lives in the ``source_question_id`` suffix.
        """
        assert build_placement_paper_stem("a1b2c3d4e5f6") != build_placement_paper_stem(
            "f6e5d4c3b2a1"
        )

    def test_parses_as_a_caie_question_paper_filename(self) -> None:
        from lemely.io.metadata import parse_caie_qp_filename_metadata

        stem = build_placement_paper_stem("abcdef123456")
        meta = parse_caie_qp_filename_metadata(f"{stem}.pdf")
        assert meta.subject_code == "0625"
        assert meta.paper_number == PLACEMENT_PAPER_NUMBER
        assert meta.paper_variant == 1

    def test_the_stem_resolves_to_the_pinned_paper_number(self) -> None:
        """The stem, the enrolment pin and the reported ``paperNumber`` must
        all be the same paper, or the eligible pool stops being this seed's own
        rows — the exact drift ``PLACEMENT_PAPER_NUMBER``'s note describes.
        """
        from lemely.io.metadata import parse_caie_qp_filename_metadata

        meta = parse_caie_qp_filename_metadata(f"{build_placement_paper_stem('tag1')}.pdf")
        assert meta.paper_number == PLACEMENT_PAPER_NUMBER

    def test_the_pinned_paper_is_a_real_non_practical_timed_paper(self) -> None:
        """Placement excludes practical papers, so pinning to one would empty
        the pool and turn S-03 into a permanent (and wrong) ``no_questions``.
        """
        from lemely.io.paper_timing import get_paper_timings

        timings = get_paper_timings(PLACEMENT_SUBJECT_CODE)
        assert PLACEMENT_PAPER_NUMBER in timings


class TestIsPlacementSeedPrompt:
    def test_recognises_every_authored_row(self) -> None:
        for row in build_placement_bank_questions("tag1"):
            assert is_placement_seed_prompt(row.prompt)

    def test_recognises_another_runs_rows_too(self) -> None:
        """Earlier runs' rows stay in the bank (no teardown) and are
        legitimately in the eligible pool, so the guard must accept them —
        rejecting them would fail the seed on its own second run.
        """
        for row in build_placement_bank_questions("f6e5d4c3b2a1"):
            assert is_placement_seed_prompt(row.prompt)

    def test_rejects_a_real_corpus_prompt(self) -> None:
        """The inverse, and the failure actually worth catching: a real
        past-paper stem carries no marker, so :func:`seed` raises instead of
        answering it — the measured defect (a billed Gemini call per drawn
        theory question, and a 6/16 S-05 baseline built out of noise).
        """
        assert not is_placement_seed_prompt(
            "A cyclist travels 120 m in 15 s. Calculate the average speed."
        )

    def test_rejects_the_teacher_authored_quiz_bank_prompts(self) -> None:
        """The other rows this same script inserts must not be mistaken for
        placement rows — they are a different fixture with different answers.
        """
        for row in build_quiz_bank_questions(_TEACHER_ID):
            assert not is_placement_seed_prompt(row.prompt)


class TestBuildPlacementBankQuestions:
    def test_returns_one_row_per_topic_per_slot(self) -> None:
        rows = build_placement_bank_questions("tag1")
        assert len(rows) == len(PLACEMENT_TOPICS) * PLACEMENT_QUESTIONS_PER_TOPIC

    def test_clears_the_assembly_viability_floor_by_shape(self) -> None:
        """Not a substitute for the real Postgres-backed assembly test
        (``tests/test_placement_repo.py``) — just a fast check that this
        function did not regress below the floor that test measures against."""
        assert len(PLACEMENT_TOPICS) >= MIN_TOPICS
        assert len(PLACEMENT_TOPICS) * PLACEMENT_QUESTIONS_PER_TOPIC >= MIN_QUESTIONS

    def test_every_row_is_past_paper_mcq_on_the_declared_topics(self) -> None:
        rows = build_placement_bank_questions("tag1")
        for row in rows:
            assert row.source == QuestionSource.past_paper
            assert row.question_type == "mcq"
            assert row.subject_code == PLACEMENT_SUBJECT_CODE
            assert row.topic in PLACEMENT_TOPICS
            assert row.total_marks == PLACEMENT_QUESTION_MARKS
            assert row.mcq_answer == PLACEMENT_MCQ_ANSWER
            assert row.paper_id is None  # filled by link_past_paper_rows(), not here

    def test_every_row_links_to_this_runs_paper_stem(self) -> None:
        rows = build_placement_bank_questions("tag1")
        stem = build_placement_paper_stem("tag1")
        for row in rows:
            assert row.source_question_id is not None
            assert row.source_question_id.startswith(f"{stem}#")

    def test_source_question_ids_are_distinct(self) -> None:
        rows = build_placement_bank_questions("tag1")
        ids = [row.source_question_id for row in rows]
        assert len(set(ids)) == len(ids)

    def test_source_question_ids_differ_across_run_tags(self) -> None:
        """Two runs must not mint the same ``source_question_id``.

        Note this pair also differs in the *stem*, so on its own this test
        passed even while reruns were colliding for real — see
        :meth:`test_source_question_ids_differ_even_when_the_paper_stem_collides`
        for the case that actually failed.
        """
        ids_a = {row.source_question_id for row in build_placement_bank_questions("a1b2c3d4e5f6")}
        ids_b = {row.source_question_id for row in build_placement_bank_questions("f6e5d4c3b2a1")}
        assert ids_a.isdisjoint(ids_b)

    def test_source_question_ids_differ_even_when_the_paper_stem_collides(self) -> None:
        """The regression that actually fired, and the reason uniqueness cannot
        live in the stem.

        ``build_placement_paper_stem`` hashes only ``run_tag``'s **first two**
        characters into the session-year digits, so the year has a 100-value
        namespace and two runs share a ``papers`` row roughly every dozen runs
        (birthday bound). It happened: ``playwright-e2e`` failed on a real
        ``uq_question_bank_paper_question (paper_id, source_question_id)``
        IntegrityError for ``0625_s88_qp_21#12`` after a day of gate runs.

        These two tags share their first two characters, so they are guaranteed
        to produce the SAME stem — the previously-fatal case. The
        ``source_question_id`` values must still be disjoint, because the suffix
        now carries the whole 12-character tag. Reverting the suffix to a bare
        ``#{ref}`` fails this test and passes every other one in this class.
        """
        tag_a, tag_b = "aa11111111aa", "aa22222222bb"
        assert build_placement_paper_stem(tag_a) == build_placement_paper_stem(tag_b)
        ids_a = {row.source_question_id for row in build_placement_bank_questions(tag_a)}
        ids_b = {row.source_question_id for row in build_placement_bank_questions(tag_b)}
        assert ids_a.isdisjoint(ids_b)

    def test_no_prompt_contains_a_figure_dependent_trigger_word(self) -> None:
        """The whole point of this bank: every row must survive chunk 0's
        ``renderable_bank_filter`` so ``assemble`` actually has a pool to draw
        from — a prompt containing one of these words risks matching
        ``_FIGURE_DEPENDENT_PATTERN`` and silently vanishing.

        ``_FIGURE_DEPENDENT_PATTERN`` is Postgres POSIX regex syntax (``\\m``/
        ``\\M`` word boundaries), not valid Python ``re`` — evaluated only via
        ``QuestionBank.prompt.op("~*")`` against a live Postgres, so this test
        checks the trigger words the pattern is built from rather than
        compiling the pattern itself.
        """
        rows = build_placement_bank_questions("tag1")
        for row in rows:
            lowered = row.prompt.lower()
            for trigger in ("figure", "diagram", "fig."):
                assert trigger not in lowered, f"{row.prompt!r} contains trigger {trigger!r}"

    def test_prompts_are_distinct_and_say_synthetic(self) -> None:
        rows = build_placement_bank_questions("tag1")
        assert len({r.prompt for r in rows}) == len(rows)
        for row in rows:
            assert "synthetic" in row.prompt.lower() or "not real" in row.prompt.lower()

    def test_every_prompt_carries_unicode_maths_and_a_newline(self) -> None:
        """The two properties MISSION §4 asks a human to verify in screenshots.

        S-04 and S-21 are the only screens that render a ``question_bank.
        prompt``, and both draw from this pool — so if the sample is ever
        stripped from these prompts the captures go back to pure ASCII
        single-line text and "inspect the stems for maths rendering" becomes a
        **vacuous pass**, indistinguishable from a real one. That is precisely
        the shape of defect chunk E exists to close, so it is pinned here
        rather than left to the next reader's care.

        Asserted on the *assembled* prompt, not on
        :data:`PLACEMENT_MATHS_SAMPLE` itself: a test that only reads the
        constant would still pass if the interpolation that appends it were
        deleted.
        """
        rows = build_placement_bank_questions("tag1")
        assert rows
        for row in rows:
            assert "\n" in row.prompt, f"no newline for pre-line to preserve: {row.prompt!r}"
            # RUF001: the MULTIPLICATION SIGN is deliberate — asserting on
            # ASCII "x" here would pass against a prompt with no maths in it.
            assert "×" in row.prompt and "⁵" in row.prompt, (  # noqa: RUF001
                f"no Unicode maths to inspect: {row.prompt!r}"
            )

    def test_maths_sample_is_corpus_verbatim_not_hand_authored(self) -> None:
        """Pins the provenance claim the docstring and D4.24 both make.

        The sample is copied verbatim from banked stem ``0625_w23_qp_42#1c``.
        A screenshot of maths *written to make the screenshot pass* proves
        nothing about how the product renders corpus text, so the specific
        wording is load-bearing evidence, not decoration. Checked against the
        recorded text rather than the live DB so the suite stays hermetic.
        """
        assert PLACEMENT_MATHS_SAMPLE.startswith(
            "A car accelerates uniformly in a straight line from rest at time t = 0."
        )
        assert PLACEMENT_MATHS_SAMPLE.endswith(
            "Show that the work done by the car as it decelerates is approximately 1.1 × 10⁵ J."  # noqa: RUF001 — corpus-verbatim glyph, not ASCII "x"
        )
        assert PLACEMENT_MATHS_SAMPLE.count("\n") == 4


# ---------------------------------------------------------------------------
# PRACTICE_SET_COUNT — P4.9 chunk C's practice-set request size. Must stay
# inside the per-topic pool build_placement_bank_questions actually seeds, or
# PracticeService.create would report insufficient_pool for a set the seed
# itself builds (only S-20's own live preview should ever exercise that
# reason — see PRACTICE_SET_COUNT's docstring).
# ---------------------------------------------------------------------------


class TestPracticeSetCount:
    def test_fits_within_a_single_topics_seeded_row_count(self) -> None:
        assert PRACTICE_SET_COUNT <= PLACEMENT_QUESTIONS_PER_TOPIC

    def test_fits_comfortably_within_the_whole_hermetic_bank(self) -> None:
        rows = build_placement_bank_questions("tag1")
        assert len(rows) >= PRACTICE_SET_COUNT


# ---------------------------------------------------------------------------
# wrong_mcq_answer — the seeded quiz submission's deliberately-incorrect answers.
# ---------------------------------------------------------------------------


class TestWrongMcqAnswer:
    def test_never_returns_the_correct_letter(self) -> None:
        for correct in ("A", "B", "C", "D"):
            assert wrong_mcq_answer(correct) != correct

    def test_always_returns_a_valid_mcq_letter(self) -> None:
        for correct in ("A", "B", "C", "D"):
            assert wrong_mcq_answer(correct) in ("A", "B", "C", "D")

    def test_is_deterministic(self) -> None:
        assert wrong_mcq_answer("B") == wrong_mcq_answer("B")


# ---------------------------------------------------------------------------
# Output contract shape.
# ---------------------------------------------------------------------------


def _payload_kwargs(**overrides: object) -> dict[str, object]:
    """The minimal, valid set of build_result_payload kwargs, overridable per test."""
    base: dict[str, object] = {
        "run_tag": "tag123",
        "generated_at": _NOW,
        "teacher": {"userId": "t1"},
        "school_admin": {"userId": "a1"},
        "school_with_seats": {
            "schoolId": "sc1",
            "name": "P23 Seed School tag123",
            "seatQuota": 5,
            "admin": {"userId": "sa1"},
        },
        "class_row": {"classId": "c1", "name": "n", "joinCode": "J1"},
        "students": {
            "declining": {
                "userId": "d1",
                "expectedAtRiskReasons": ["declining_trend"],
                "parentInviteCode": "ABC123",
            },
            "inactive": {"userId": "i1", "expectedAtRiskReasons": ["inactive"]},
            "control": {"userId": "c1", "expectedAtRiskReasons": []},
            "correctedPaper": {
                "userId": "cp1",
                "expectedAtRiskReasons": [],
                "correctedPaperId": "attempt-1",
            },
        },
        "parent": {
            "userId": "p1",
            "email": "parent-tag123@e2e.lemely.local",
            "password": "Seed-tag123-Aa1!",
            "accessToken": "tok-p1",
            "linkedStudent": "declining",
        },
        "review_item": {
            "itemId": "ri1",
            "attemptId": "at1",
            "studentKey": "inactive",
            "legacyItemId": "ri2",
            "legacyAttemptId": "at2",
        },
        "quiz": {
            "quizId": "q1",
            "assignmentId": "as1",
            "submissionId": "sub1",
            "submittedBy": "control",
            "status": "marked",
        },
        "empty_teacher": {"userId": "et1"},
        "empty_parent": {
            "userId": "ep1",
            "email": "empty-parent-tag123@e2e.lemely.local",
            "password": "Seed-tag123-Aa1!",
            "accessToken": "tok-ep1",
        },
        "placement": {
            "subjectCode": "0625",
            "paperNumber": 2,
            "bankQuestionCount": 24,
            "students": {
                "unonboarded": {"userId": "pu1"},
                "available": {"userId": "pa1"},
                "inProgress": {"userId": "pi1", "quizId": "pq1", "assignmentId": "pas1"},
                "completed": {
                    "userId": "pc1",
                    "quizId": "pq2",
                    "assignmentId": "pas2",
                    "submissionId": "psub1",
                    "awardedMarks": 5,
                    "maximumMarks": 10,
                },
            },
        },
        "practice": {
            "subjectCode": "0625",
            "students": {
                "active": {
                    "userId": "pra1",
                    "unsubmittedAssignmentId": "prb-as1",
                    "markingAssignmentId": "prc-as1",
                    "markedAssignmentId": "pra-as1",
                    "deckId": "deck1",
                },
                "settled": {"userId": "prs1", "deckId": "deck2"},
                "bare": {"userId": "prz1"},
            },
        },
        "study_plan": {
            "subjectCode": "0625",
            "activeSessionId": "sp-sess1",
            "activeSessionTopic": "1.2 Motion",
            "activeSessionCount": 3,
            "completedSessionCount": 3,
        },
        "engagement": {
            "deviceLimit": {"userId": "dl1", "deviceCount": 3, "oldestDeviceLabel": "Chrome"},
            "leaderboard": {
                "classId": "c1",
                "weeklyXpByStudentKey": {"declining": 200, "inactive": 150},
                "expectedOrderByStudentKey": ["declining", "inactive"],
            },
        },
        "deletion": {
            "classId": "dc1",
            "className": "P8 Deletion Class tag123",
            "student": {"userId": "ds1", "subjectCode": "0625", "attemptIds": ["da1", "da2"]},
            "integrityStudent": {
                "userId": "di1",
                "subjectCode": "0625",
                "attemptId": "dia1",
                "reviewItemId": "dri1",
            },
            "remarkStudent": {"userId": "dr1", "attemptIds": ["drm1", "drm2"]},
            "reviewItemId": "dqi1",
            "consolePaperId": "dcp1",
        },
        "tutoring": {
            "subjectCode": "0625",
            "tutors": {"sufficient": {"tutorProfileId": "tp1"}},
        },
    }
    base.update(overrides)
    return base


class TestBuildResultPayload:
    def test_shape_matches_the_documented_contract(self) -> None:
        payload = build_result_payload(**_payload_kwargs())
        assert payload == {
            "runTag": "tag123",
            "generatedAt": _NOW.isoformat(),
            "teacher": {"userId": "t1"},
            "schoolAdmin": {"userId": "a1"},
            "schoolWithSeats": {
                "schoolId": "sc1",
                "name": "P23 Seed School tag123",
                "seatQuota": 5,
                "admin": {"userId": "sa1"},
            },
            "class": {"classId": "c1", "name": "n", "joinCode": "J1"},
            "students": {
                "declining": {
                    "userId": "d1",
                    "expectedAtRiskReasons": ["declining_trend"],
                    "parentInviteCode": "ABC123",
                },
                "inactive": {"userId": "i1", "expectedAtRiskReasons": ["inactive"]},
                "control": {"userId": "c1", "expectedAtRiskReasons": []},
                "correctedPaper": {
                    "userId": "cp1",
                    "expectedAtRiskReasons": [],
                    "correctedPaperId": "attempt-1",
                },
            },
            "parent": {
                "userId": "p1",
                "email": "parent-tag123@e2e.lemely.local",
                "password": "Seed-tag123-Aa1!",
                "accessToken": "tok-p1",
                "linkedStudent": "declining",
            },
            "reviewItem": {
                "itemId": "ri1",
                "attemptId": "at1",
                "studentKey": "inactive",
                "legacyItemId": "ri2",
                "legacyAttemptId": "at2",
            },
            "quiz": {
                "quizId": "q1",
                "assignmentId": "as1",
                "submissionId": "sub1",
                "submittedBy": "control",
                "status": "marked",
            },
            "emptyTeacher": {"userId": "et1"},
            "emptyParent": {
                "userId": "ep1",
                "email": "empty-parent-tag123@e2e.lemely.local",
                "password": "Seed-tag123-Aa1!",
                "accessToken": "tok-ep1",
            },
            "placement": {
                "subjectCode": "0625",
                "paperNumber": 2,
                "bankQuestionCount": 24,
                "students": {
                    "unonboarded": {"userId": "pu1"},
                    "available": {"userId": "pa1"},
                    "inProgress": {"userId": "pi1", "quizId": "pq1", "assignmentId": "pas1"},
                    "completed": {
                        "userId": "pc1",
                        "quizId": "pq2",
                        "assignmentId": "pas2",
                        "submissionId": "psub1",
                        "awardedMarks": 5,
                        "maximumMarks": 10,
                    },
                },
            },
            "practice": {
                "subjectCode": "0625",
                "students": {
                    "active": {
                        "userId": "pra1",
                        "unsubmittedAssignmentId": "prb-as1",
                        "markingAssignmentId": "prc-as1",
                        "markedAssignmentId": "pra-as1",
                        "deckId": "deck1",
                    },
                    "settled": {"userId": "prs1", "deckId": "deck2"},
                    "bare": {"userId": "prz1"},
                },
            },
            "studyPlan": {
                "subjectCode": "0625",
                "activeSessionId": "sp-sess1",
                "activeSessionTopic": "1.2 Motion",
                "activeSessionCount": 3,
                "completedSessionCount": 3,
            },
            "engagement": {
                "deviceLimit": {"userId": "dl1", "deviceCount": 3, "oldestDeviceLabel": "Chrome"},
                "leaderboard": {
                    "classId": "c1",
                    "weeklyXpByStudentKey": {"declining": 200, "inactive": 150},
                    "expectedOrderByStudentKey": ["declining", "inactive"],
                },
            },
            "deletion": {
                "classId": "dc1",
                "className": "P8 Deletion Class tag123",
                "student": {"userId": "ds1", "subjectCode": "0625", "attemptIds": ["da1", "da2"]},
                "integrityStudent": {
                    "userId": "di1",
                    "subjectCode": "0625",
                    "attemptId": "dia1",
                    "reviewItemId": "dri1",
                },
                "remarkStudent": {"userId": "dr1", "attemptIds": ["drm1", "drm2"]},
                "reviewItemId": "dqi1",
                "consolePaperId": "dcp1",
            },
            "tutoring": {
                "subjectCode": "0625",
                "tutors": {"sufficient": {"tutorProfileId": "tp1"}},
            },
        }

    def test_is_json_serializable(self) -> None:
        import json

        payload = build_result_payload(**_payload_kwargs())
        assert json.loads(json.dumps(payload)) == payload

    def test_contract_carries_parent_invite_code_and_parent_email(self) -> None:
        """Retiring phone-OTP parents (parent-invites redesign) means the
        contract's ``parent``/``emptyParent`` are email/password accounts, and
        ``students.declining`` carries the reusable code
        ``parent-journey.spec.ts`` redeems through the real ``/join/:code``
        flow instead of an already-linked pair."""
        payload = build_result_payload(**_payload_kwargs())

        assert payload["students"]["declining"]["parentInviteCode"] == "ABC123"
        assert payload["parent"]["email"] == "parent-tag123@e2e.lemely.local"
        assert "password" in payload["parent"]
        assert "phone" not in payload["parent"]
        assert payload["emptyParent"]["email"] == "empty-parent-tag123@e2e.lemely.local"
        assert "phone" not in payload["emptyParent"]


class TestSelfReviewSeed:
    def test_the_paper_has_point_rows_and_one_low_confidence_question(self) -> None:
        from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
        from lemely.db.question_points import derive_point_rows
        from scripts.seed_e2e import self_review_report, self_review_scheme

        report = self_review_report()
        scheme = self_review_scheme()
        by_id = {q.question_id: q for q in report.correction.questions}
        assert set(by_id) == {"1", "2"}
        assert by_id["1"].confidence_score >= REVIEW_CONFIDENCE_THRESHOLD
        assert by_id["2"].confidence_score < REVIEW_CONFIDENCE_THRESHOLD
        assert by_id["2"].needs_teacher_review is True
        assert not by_id["2"].plagiarism_flagged
        assert len(derive_point_rows(by_id["2"], scheme)) == 3
        assert [r["awarded"] for r in derive_point_rows(by_id["2"], scheme)] == [True, False, False]
        assert report.correction.awarded_marks == 3 and report.correction.maximum_marks == 5

    def test_question_2_points_carry_all_three_verdicts(self) -> None:
        """Task #66: without this, every seeded row leaves ``verdict`` NULL and
        no Playwright spec can assert a verdict chip renders (self-review's
        own post-reveal assertion is blocked on exactly this)."""
        from lemely.db.question_points import derive_point_rows
        from scripts.seed_e2e import self_review_report, self_review_scheme

        report = self_review_report()
        scheme = self_review_scheme()
        by_id = {q.question_id: q for q in report.correction.questions}
        rows = derive_point_rows(by_id["2"], scheme)
        assert [r["verdict"] for r in rows] == ["awarded", "withheld", "unverifiable"]
        assert any(r["evidence_span"] for r in rows)
        assert any(r["ecf_applied"] for r in rows)
        # The verdict path's own "awarded" boolean must still agree with
        # matched_point_ids -- the same invariant _awarded_from_verdicts
        # enforces on the real marking path.
        assert [r["awarded"] for r in rows] == [True, False, False]


class TestReviewItemVerdicts:
    """Task #66: the review-queue item (T-08) must also carry a per-point
    verdict ledger, so a first Playwright spec against ``/teacher/review``
    (task #7) has something non-null to assert on."""

    def test_review_item_question_carries_all_three_verdicts(self) -> None:
        from lemely.db.question_points import derive_point_rows
        from scripts.seed_e2e import (
            REVIEW_ITEM_MATCHED_POINT_IDS,
            review_item_point_verdicts,
            review_item_scheme,
        )

        report = accuracy_report_for_score(
            INACTIVE_SCORE,
            paper_number=1,
            confidence=ConfidenceBand.LOW,
            confidence_score=REVIEW_ITEM_CONFIDENCE_SCORE,
            needs_teacher_review=True,
            matched_point_ids=REVIEW_ITEM_MATCHED_POINT_IDS,
            point_verdicts=review_item_point_verdicts(),
        )
        scheme = review_item_scheme()
        question = report.correction.questions[0]
        rows = derive_point_rows(question, scheme)
        assert [r["verdict"] for r in rows] == ["awarded", "withheld", "unverifiable"]
        assert any(r["evidence_span"] for r in rows)
        assert any(r["ecf_applied"] for r in rows)
        assert [r["awarded"] for r in rows] == [True, False, False]
        # Score/grade untouched by attaching a scheme + verdicts -- same
        # invariant TestAccuracyReportForScore.
        # test_low_confidence_override_carries_the_score_and_needs_review pins.
        assert report.grade_prediction.percentage == INACTIVE_SCORE[0]
        assert report.grade_prediction.grade == INACTIVE_SCORE[1]


class TestLegacyReviewItem:
    """Task #67: the review queue's SECOND row -- a question with a mark
    scheme but neither a verdict nor a rationale on any point, the ordinary
    legacy shape `MarkerVerdicts`' section-suppression guard exists to hide
    (`web/src/portals/teacher/screens/ReviewItem.tsx`) and the only shape
    production sees today (`equivalence_gate` defaults off)."""

    def test_legacy_review_question_carries_no_verdict_and_no_rationale(self) -> None:
        from lemely.db.question_points import derive_point_rows

        report = accuracy_report_for_score(
            LEGACY_REVIEW_SCORE,
            paper_number=1,
            confidence=ConfidenceBand.LOW,
            confidence_score=LEGACY_REVIEW_CONFIDENCE_SCORE,
            needs_teacher_review=True,
            # Deliberately no matched_point_ids/point_verdicts -- see
            # legacy_review_scheme()'s own docstring.
        )
        scheme = legacy_review_scheme()
        question = report.correction.questions[0]
        rows = derive_point_rows(question, scheme)
        assert len(rows) == 2
        assert [r["verdict"] for r in rows] == [None, None]
        assert [r["rationale"] for r in rows] == [None, None]
        assert [r["evidence_span"] for r in rows] == ["", ""]
        assert [r["ecf_applied"] for r in rows] == [False, False]
        # Marker-source stays "deterministic" -- unlike the verdict-bearing
        # review item, nothing here is an I6 verdict.
        assert question.marker_source == "deterministic"
        assert question.needs_teacher_review is True
        assert question.confidence_score == LEGACY_REVIEW_CONFIDENCE_SCORE
        assert question.confidence_score < REVIEW_CONFIDENCE_THRESHOLD
        # Score/grade untouched by attaching a scheme -- same invariant
        # TestReviewItemVerdicts pins for the verdict-bearing row.
        assert report.grade_prediction.percentage == LEGACY_REVIEW_SCORE[0]
        assert report.grade_prediction.grade == LEGACY_REVIEW_SCORE[1]


class TestRationaleOnlyReviewItem:
    """Final-review coverage gap: a THIRD review-queue row, carrying a
    marker's per-point ``rationale`` (``point_notes``) but no ``verdict`` on
    any point -- the shape production ships today whenever a marker writes a
    note without ``equivalence_gate`` on. Neither `TestReviewItemVerdicts`
    (every point has a verdict) nor `TestLegacyReviewItem` (no point has
    anything) can stand in for this: `MarkerVerdicts`' section guard
    (`web/src/portals/teacher/screens/ReviewItem.tsx`) was widened to
    `p.verdict !== null || p.rationale` specifically so this rationale-only
    shape still renders, and that widening had no seeded row to prove it
    against until now."""

    def test_rationale_only_question_carries_rationale_but_no_verdict(self) -> None:
        from lemely.db.question_points import derive_point_rows
        from scripts.seed_e2e import (
            RATIONALE_ONLY_REVIEW_NOTE,
            rationale_only_review_point_notes,
            rationale_only_review_scheme,
        )

        report = accuracy_report_for_score(
            RATIONALE_ONLY_REVIEW_SCORE,
            paper_number=1,
            confidence=ConfidenceBand.LOW,
            confidence_score=RATIONALE_ONLY_REVIEW_CONFIDENCE_SCORE,
            needs_teacher_review=True,
            point_notes=rationale_only_review_point_notes(),
            # Deliberately no matched_point_ids/point_verdicts -- see
            # rationale_only_review_point_notes()'s own docstring.
        )
        scheme = rationale_only_review_scheme()
        question = report.correction.questions[0]
        rows = derive_point_rows(question, scheme)
        assert len(rows) == 2
        assert [r["verdict"] for r in rows] == [None, None]
        assert [r["rationale"] for r in rows] == [RATIONALE_ONLY_REVIEW_NOTE, None]
        assert [r["evidence_span"] for r in rows] == ["", ""]
        assert [r["ecf_applied"] for r in rows] == [False, False]
        # Marker-source stays "deterministic" -- point_notes alone is the
        # legacy path, never an I6 verdict.
        assert question.marker_source == "deterministic"
        assert question.needs_teacher_review is True
        assert question.confidence_score == RATIONALE_ONLY_REVIEW_CONFIDENCE_SCORE
        assert question.confidence_score < REVIEW_CONFIDENCE_THRESHOLD
        # Score/grade untouched by attaching a scheme -- same invariant
        # TestLegacyReviewItem/TestReviewItemVerdicts pin for the other rows.
        assert report.grade_prediction.percentage == RATIONALE_ONLY_REVIEW_SCORE[0]
        assert report.grade_prediction.grade == RATIONALE_ONLY_REVIEW_SCORE[1]


# ---------------------------------------------------------------------------
# Tutoring marketplace fixture (T29).
# ---------------------------------------------------------------------------

_REAL_NOW = datetime.now(UTC)


class TestTutoringOutcomeFixture:
    """The two cohorts, judged by `core.tutor_outcomes` itself (SPEC section e, ADR-T04)."""

    def test_seed_tutoring_outcome_fixture_is_sufficient(self) -> None:
        members, observations = tutoring_cohort_inputs(TUTORING_SUFFICIENT_COHORT, _REAL_NOW)
        outcome = outcome_for_subject(members, observations, now=_REAL_NOW)

        assert len(TUTORING_SUFFICIENT_COHORT) >= OUTCOME_K_MIN
        assert outcome.distribution.state == "sufficient"
        assert outcome.change.state == "sufficient"
        assert outcome.distribution.n_graded == len(TUTORING_SUFFICIENT_COHORT)
        assert outcome.change.n_paired == len(TUTORING_SUFFICIENT_COHORT)

        # The four conditions the brief names, each read off the figure or the
        # inputs, not off the fixture's own literals.
        assert all(m.eligible for m in members)
        assert all(close_instant(m) <= _REAL_NOW for m in members), "a window is still open"
        counts = [b.count for b in outcome.distribution.buckets]
        assert max(counts) <= outcome.distribution.n_graded - 2
        assert not any(m.ever_granted for m in members)  # never-granted = n >= k
        assert outcome.change.higher is not None
        assert (
            max(outcome.change.higher, outcome.change.same or 0, outcome.change.lower or 0)
            <= (outcome.change.n_paired or 0) - 2
        )

    def test_sufficient_fixture_has_exactly_k_so_dropping_one_hides_it(self) -> None:
        """Non-vacuity: the guard the fixture clears is the k floor, and it is live."""
        assert len(TUTORING_SUFFICIENT_COHORT) == OUTCOME_K_MIN
        members, observations = tutoring_cohort_inputs(TUTORING_SUFFICIENT_COHORT[:-1], _REAL_NOW)
        outcome = outcome_for_subject(members, observations, now=_REAL_NOW)
        assert outcome.distribution.state == "insufficient"
        assert outcome.change.state == "insufficient"

    def test_sufficient_fixture_windows_have_closed_with_room_to_spare(self) -> None:
        """A run that starts a week late must still find every window closed."""
        newest = max(tutoring_session_start(s, _REAL_NOW) for s in TUTORING_SUFFICIENT_COHORT)
        assert _REAL_NOW - (newest + DURING_WINDOW) >= timedelta(days=7)

    def test_seed_tutoring_insufficient_fixture(self) -> None:
        members, observations = tutoring_cohort_inputs(TUTORING_INSUFFICIENT_COHORT, _REAL_NOW)
        outcome = outcome_for_subject(members, observations, now=_REAL_NOW)

        assert 0 < len(TUTORING_INSUFFICIENT_COHORT) < OUTCOME_K_MIN
        assert all(m.eligible for m in members)  # it is the count that hides it, not exclusion
        assert outcome.distribution.state == "insufficient"
        assert outcome.change.state == "insufficient"
        assert outcome.distribution.n_graded is None
        assert outcome.distribution.buckets == ()
        assert outcome.change.n_paired is None

    def test_expected_outcome_matches_the_core_for_both_cohorts(self) -> None:
        sufficient = tutoring_expected_outcome(TUTORING_SUFFICIENT_COHORT, _REAL_NOW)
        insufficient = tutoring_expected_outcome(TUTORING_INSUFFICIENT_COHORT, _REAL_NOW)
        assert sufficient.distribution.state == "sufficient"
        assert insufficient.distribution.state == "insufficient"


class TestTutoringBookingPlan:
    def test_every_effective_state_is_planned(self) -> None:
        seen = {
            effective_state(
                plan.state,
                starts_at=tutoring_booking_times(plan, _REAL_NOW)[0],
                ends_at=tutoring_booking_times(plan, _REAL_NOW)[1],
                now=_REAL_NOW,
            )
            for plan in TUTORING_BOOKING_PLAN
        }
        # Expected side: the state names SPEC section a.3 lists, taken from the
        # core's own literal, so a state added there fails here.
        assert seen == set(get_args(EffectiveState))

    def test_a_tutor_late_cancel_with_a_reason_is_planned(self) -> None:
        late = [
            plan
            for plan in TUTORING_BOOKING_PLAN
            if plan.cancelled_by == "tutor"
            and plan.cancelled_hours_ago is not None
            and is_late_cancel(
                cancelled_by="tutor",
                cancelled_at=_REAL_NOW - timedelta(hours=plan.cancelled_hours_ago),
                starts_at=tutoring_booking_times(plan, _REAL_NOW)[0],
            )
        ]
        assert len(late) == 1

    def test_child_has_a_parent_requested_accepted_a_child_requested_and_an_awaiting_booking(
        self,
    ) -> None:
        child = [p for p in TUTORING_BOOKING_PLAN if p.student == "child"]

        def eff(plan_key: str) -> str:
            plan = next(p for p in child if p.key == plan_key)
            starts, ends = tutoring_booking_times(plan, _REAL_NOW)
            return effective_state(plan.state, starts_at=starts, ends_at=ends, now=_REAL_NOW)

        parent_requested = [p for p in child if p.requested_by == "parent"]
        child_requested = [p for p in child if p.requested_by == "student"]
        assert any(eff(p.key) == "accepted" for p in parent_requested)
        assert any(eff(p.key) == "requested" for p in child_requested)
        assert any(eff(p.key) == "awaiting_outcome" for p in child)

    def test_no_two_active_bookings_of_one_tutor_or_student_overlap(self) -> None:
        """The database's exclusion constraints would refuse the seed otherwise."""
        active = [p for p in TUTORING_BOOKING_PLAN if p.state in {"requested", "accepted"}]
        assert len(active) >= 6, "the overlap scan found nothing to compare"
        for i, a in enumerate(active):
            for b in active[i + 1 :]:
                if a.tutor == b.tutor or a.student == b.student:
                    a_start, a_end = tutoring_booking_times(a, _REAL_NOW)
                    b_start, b_end = tutoring_booking_times(b, _REAL_NOW)
                    assert a_end <= b_start or b_end <= a_start, (a.key, b.key)


# ---------------------------------------------------------------------------
# The writer, against a throwaway database.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tutoring_db() -> Any:
    from tests.tutoring_db import tutoring_database

    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: Any) -> Any:
    from tests.tutoring_db import emptied_after

    yield from emptied_after(tutoring_db)


def _account(sm: Any, role: Role, label: str, *, verified: bool = True) -> dict[str, Any]:
    from tests.tutoring_db import add_user

    uid = add_user(sm, role, display_name=f"Seed {label}", verified=verified)
    return {
        "userId": str(uid),
        "email": f"{label}@e2e.lemely.local",
        "password": "pw",
        "displayName": f"Seed {label}",
        "accessToken": f"tok-{label}",
    }


def _accounts(sm: Any) -> TutoringSeedAccounts:
    # Unverified, as `_signup_account` leaves every student: the fixture has to fix that.
    child = _account(sm, Role.student, "child", verified=False)
    parent = _account(sm, Role.parent, "parent")
    with sm.begin() as session:
        session.add(
            ParentChildLink(
                parent_id=uuid.UUID(parent["userId"]), child_id=uuid.UUID(child["userId"])
            )
        )
    return TutoringSeedAccounts(
        platform_admin=_account(sm, Role.platform_admin, "admin"),
        tutor_sufficient=_account(sm, Role.teacher, "tutor-a"),
        tutor_insufficient=_account(sm, Role.teacher, "tutor-b"),
        tutor_draft=_account(sm, Role.teacher, "tutor-draft"),
        student=_account(sm, Role.student, "sam"),
        discover=_account(sm, Role.student, "discover"),
        rival=_account(sm, Role.student, "rival"),
        child=child,
        parent=parent,
    )


@pytest.fixture
def seeded(sm: Any) -> tuple[dict[str, Any], TutoringSeedAccounts]:
    accounts = _accounts(sm)
    group = seed_tutoring_fixture(sm, run_tag="t29test", now=datetime.now(UTC), accounts=accounts)
    return group, accounts


class TestSeedTutoringFixtureInDatabase:
    def test_the_database_agrees_the_sufficient_tutor_shows_a_figure_and_the_other_does_not(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, accounts = seeded
        repo = TutorOutcomesRepository(sm)
        viewer = uuid.UUID(accounts.discover["userId"])

        sufficient = repo.outcomes_for_viewer(
            uuid.UUID(group["tutors"]["sufficient"]["tutorProfileId"]), viewer, Role.student
        )
        insufficient = repo.outcomes_for_viewer(
            uuid.UUID(group["tutors"]["insufficient"]["tutorProfileId"]), viewer, Role.student
        )

        assert sufficient is not None and insufficient is not None
        [physics] = sufficient.subjects
        assert physics.subject.code == TUTORING_SUBJECT_CODE
        assert physics.outcome.distribution.state == "sufficient"
        assert physics.outcome.distribution.n_graded == len(TUTORING_SUFFICIENT_COHORT)
        assert physics.outcome.change.state == "sufficient"
        [other] = insufficient.subjects
        assert other.outcome.distribution.state == "insufficient"
        assert other.outcome.change.state == "insufficient"

    def test_the_contract_states_the_expected_figure_the_database_reports(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, _ = seeded
        figure = group["outcomes"]["sufficient"]
        expected = tutoring_expected_outcome(TUTORING_SUFFICIENT_COHORT, datetime.now(UTC))
        assert figure["distributionState"] == "sufficient"
        assert figure["nGraded"] == expected.distribution.n_graded
        assert figure["buckets"] == {b.grade: b.count for b in expected.distribution.buckets}
        assert (figure["higher"], figure["same"], figure["lower"]) == (
            expected.change.higher,
            expected.change.same,
            expected.change.lower,
        )
        assert group["outcomes"]["insufficient"]["distributionState"] == "insufficient"

    def test_tutor_listing_states_and_indexing(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, accounts = seeded
        with sm() as session:
            rows = {
                key: session.get(TutorProfile, uuid.UUID(group["tutors"][key]["tutorProfileId"]))
                for key in ("sufficient", "insufficient", "draft")
            }
        assert all(row is not None for row in rows.values())
        assert rows["sufficient"].listing_state.value == "listed"
        assert rows["sufficient"].indexable is True
        assert rows["insufficient"].listing_state.value == "listed"
        assert rows["insufficient"].indexable is False
        assert rows["draft"].listing_state.value == "draft"
        assert rows["sufficient"].user_id == uuid.UUID(accounts.tutor_sufficient["userId"])
        assert group["tutors"]["sufficient"]["listingState"] == "listed"
        assert group["tutors"]["insufficient"]["indexable"] is False
        assert group["tutors"]["draft"]["listingState"] == "draft"

    def test_every_effective_state_is_present_in_the_database(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        with sm() as session:
            total = session.execute(sa.text("SELECT count(*) FROM tutor_bookings")).scalar_one()
            per_state = {
                name: session.execute(
                    sa.text(f"SELECT count(*) FROM tutor_bookings WHERE {predicate}")  # noqa: S608
                ).scalar_one()
                for name, predicate in EFFECTIVE_STATE_SQL.items()
            }
        assert set(per_state) == set(get_args(EffectiveState))
        assert all(count >= 1 for count in per_state.values()), per_state
        assert sum(per_state.values()) == total  # the predicates partition the rows

    def test_the_tutor_late_cancel_carries_its_reason(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, _ = seeded
        with sm() as session:
            row = session.get(TutorBooking, uuid.UUID(group["bookings"]["cancelledByTutorLate"]))
        assert row is not None
        assert row.state.value == "cancelled"
        assert row.cancelled_by_party is not None and row.cancelled_by_party.value == "tutor"
        assert row.cancel_reason and row.cancel_reason.strip()
        assert row.cancelled_at is not None
        assert is_late_cancel(
            cancelled_by="tutor", cancelled_at=row.cancelled_at, starts_at=row.starts_at
        )

    def test_the_childs_three_bookings(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, accounts = seeded
        with sm() as session:
            child = {
                key: session.get(TutorBooking, uuid.UUID(group["bookings"]["child"][key]))
                for key in ("parentAccepted", "childRequested", "awaitingOutcome")
            }
        assert all(row is not None for row in child.values())
        assert {r.student_id for r in child.values()} == {uuid.UUID(accounts.child["userId"])}
        assert child["parentAccepted"].requested_by_party.value == "parent"
        assert child["parentAccepted"].requested_by_user_id == uuid.UUID(accounts.parent["userId"])
        assert child["parentAccepted"].state.value == "accepted"
        assert child["childRequested"].requested_by_party.value == "student"
        assert child["childRequested"].state.value == "requested"
        now = datetime.now(UTC)
        assert child["awaitingOutcome"].state.value == "accepted"
        assert child["awaitingOutcome"].ends_at <= now

    def test_one_live_grant_with_audit_rows_and_one_ended_grant(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, accounts = seeded
        child = uuid.UUID(accounts.child["userId"])
        live = uuid.UUID(group["grants"]["live"]["grantId"])
        ended = uuid.UUID(group["grants"]["ended"]["grantId"])
        with sm() as session:
            live_row = session.get(TutorDataGrant, live)
            ended_row = session.get(TutorDataGrant, ended)
            audit = session.scalars(
                sa.select(TutorAccessAudit).where(TutorAccessAudit.grant_id == live)
            ).all()
            live_for_child = session.scalars(
                sa.select(TutorDataGrant).where(
                    TutorDataGrant.student_id == child, TutorDataGrant.revoked_at.is_(None)
                )
            ).all()
        assert live_row is not None and live_row.revoked_at is None
        assert live_row.student_id == child
        assert ended_row is not None and ended_row.revoked_at is not None
        assert ended_row.revoke_reason is not None and ended_row.revoke_reason.value == "student"
        assert [g.id for g in live_for_child] == [live]
        assert len(audit) == group["grants"]["live"]["accessLogCount"] >= 3
        assert {a.tutor_profile_id for a in audit} == {
            uuid.UUID(group["tutors"]["sufficient"]["tutorProfileId"])
        }
        assert all(a.accessed_at <= datetime.now(UTC) for a in audit)

    def test_the_booking_student_has_a_second_live_grant_to_revoke(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, accounts = seeded
        with sm() as session:
            row = session.get(TutorDataGrant, uuid.UUID(group["grants"]["revocable"]["grantId"]))
        assert row is not None and row.revoked_at is None
        assert row.student_id == uuid.UUID(accounts.student["userId"])
        assert row.student_id != uuid.UUID(accounts.child["userId"])

    def test_one_open_safety_concern_on_a_booking_and_one_resolved_report(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, accounts = seeded
        with sm() as session:
            open_report = session.get(
                TutoringReport, uuid.UUID(group["reports"]["openSafety"]["reportId"])
            )
            resolved = session.get(
                TutoringReport, uuid.UUID(group["reports"]["resolved"]["reportId"])
            )
            booking = session.get(
                TutorBooking, uuid.UUID(group["reports"]["openSafety"]["bookingId"])
            )
            notes = session.scalars(
                sa.select(TutorBookingNote).where(TutorBookingNote.booking_id == booking.id)
            ).all()
            open_count = session.execute(
                sa.text("SELECT count(*) FROM tutoring_reports WHERE state = 'open'")
            ).scalar_one()
        assert open_report is not None and resolved is not None and booking is not None
        assert open_report.state.value == "open"
        assert open_report.reason.value == "safety_concern"
        assert open_report.target_type.value == "booking"
        assert open_report.booking_id == booking.id
        assert booking.notes_frozen_at is not None  # a safety concern freezes the thread
        assert len(notes) >= 2  # there is a thread for the admin to read
        assert resolved.state.value != "open"
        assert resolved.resolved_by == uuid.UUID(accounts.platform_admin["userId"])
        assert open_count == 1

    def test_reviews_give_the_sufficient_tutor_a_rating_and_the_queue_a_pending_text(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, _ = seeded
        with sm() as session:
            profile = session.get(
                TutorProfile, uuid.UUID(group["tutors"]["sufficient"]["tutorProfileId"])
            )
            pending = session.execute(
                sa.text("SELECT count(*) FROM tutor_reviews WHERE text_state = 'pending'")
            ).scalar_one()
            approved = session.execute(
                sa.text("SELECT count(*) FROM tutor_reviews WHERE text_state = 'approved'")
            ).scalar_one()
        assert profile is not None
        assert profile.rating_count >= 3  # the card shows a rating from three reviews
        assert pending >= 1 and approved >= 1

    def test_a_second_run_with_another_tag_does_not_collide(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        first, _ = seeded
        again = seed_tutoring_fixture(
            sm, run_tag="t29again", now=datetime.now(UTC), accounts=_accounts(sm)
        )
        assert (
            again["tutors"]["sufficient"]["tutorProfileId"]
            != first["tutors"]["sufficient"]["tutorProfileId"]
        )
        assert again["outcomes"]["sufficient"]["distributionState"] == "sufficient"


class TestTutoringSubject:
    def test_an_existing_catalogue_subject_is_kept_and_its_name_reported(self, sm: Any) -> None:
        from tests.tutoring_db import add_subject

        add_subject(sm, TUTORING_SUBJECT_CODE, "Catalogue Physics")
        group = seed_tutoring_fixture(
            sm, run_tag="t29subj", now=datetime.now(UTC), accounts=_accounts(sm)
        )
        with sm() as session:
            names = (
                session.execute(
                    sa.text("SELECT name FROM subjects WHERE code = :c"),
                    {"c": TUTORING_SUBJECT_CODE},
                )
                .scalars()
                .all()
            )
        assert names == ["Catalogue Physics"]
        assert group["subjectName"] == "Catalogue Physics"


_CONTRACT_SPEC = Path(__file__).resolve().parents[1] / "web" / "e2e" / "seed-contract.spec.ts"
_ACCOUNT_LEAVES = ("userId", "email", "password", "displayName", "accessToken")
_TUTOR_LEAVES = (*_ACCOUNT_LEAVES, "tutorProfileId", "publicName", "headline", "listingState")
#: Leaves `seed-contract.spec.ts` checks in a test of their own instead of in SHAPE:
#: booleans, the bucket map and the insufficient figure's null counts and empty buckets.
_CHECKED_ELSEWHERE = re.compile(
    r"tutoring\.tutors\.\w+\.indexable"
    r"|tutoring\.outcomes\.sufficient\.buckets\.[A-Z*]+"
    r"|tutoring\.outcomes\.insufficient\.(?:nGraded|nPaired|higher|same|lower|buckets)"
)


def _declared_tutoring_paths(spec_text: str) -> set[str]:
    """Every ``tutoring.*`` path ``seed-contract.spec.ts``'s SHAPE declares, spreads expanded."""
    paths = set(re.findall(r'"(tutoring\.[\w.]+)":\s*"(?:string|number)"', spec_text))
    for prefix in re.findall(r'\.\.\.account\("(tutoring\.[\w.]+)"\)', spec_text):
        paths |= {f"{prefix}.{leaf}" for leaf in _ACCOUNT_LEAVES}
    for prefix in re.findall(r'\.\.\.tutor\("(tutoring\.[\w.]+)"\)', spec_text):
        paths |= {f"{prefix}.{leaf}" for leaf in _TUTOR_LEAVES}
    return paths


def _leaf_paths(value: object, prefix: str) -> set[str]:
    if isinstance(value, dict) and value:
        return {p for k, v in value.items() for p in _leaf_paths(v, f"{prefix}.{k}")}
    return {prefix}


class TestTutoringContractLockstep:
    """The TypeScript contract and the real ``tutoring`` group name the same leaves."""

    def test_every_declared_path_exists_and_every_leaf_is_declared(
        self, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, _ = seeded
        declared = _declared_tutoring_paths(_CONTRACT_SPEC.read_text(encoding="utf-8"))
        actual = {p for p in _leaf_paths(group, "tutoring") if not _CHECKED_ELSEWHERE.fullmatch(p)}
        # Non-vacuity: the account spreads alone give 8 accounts x 5 + 3 tutors x 4 leaves.
        assert len(declared) >= 80
        assert declared - actual == set(), "declared in seed-contract.spec.ts, not seeded"
        assert actual - declared == set(), "seeded, not declared in seed-contract.spec.ts"

    def test_declared_types_match_the_values(
        self, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        group, _ = seeded
        spec_text = _CONTRACT_SPEC.read_text(encoding="utf-8")
        typed = dict(re.findall(r'"(tutoring\.[\w.]+)":\s*"(string|number)"', spec_text))
        assert typed, "no typed tutoring path found in seed-contract.spec.ts"
        for path, kind in typed.items():
            node: Any = {"tutoring": group}
            for part in path.split("."):
                node = node[part]
            expected = str if kind == "string" else int
            assert isinstance(node, expected) and not isinstance(node, bool), (path, node)
            if kind == "string":
                assert node != "", path


class TestChildIsVerifiedForTheStudentTutoringRoutes:
    """T32: the directory, booking and sharing all need a verified email."""

    def test_the_fixture_verifies_the_unverified_child(
        self, sm: Any, seeded: tuple[dict[str, Any], TutoringSeedAccounts]
    ) -> None:
        _, accounts = seeded
        with sm() as session:
            verified_at = session.scalar(
                sa.select(User.email_verified_at).where(
                    User.id == uuid.UUID(accounts.child["userId"])
                )
            )
        assert verified_at is not None


class TestMainKeepsStdoutToTheJson:
    """T32: a repository's log line in front of the JSON made `e2e-seed.json` unparseable."""

    @pytest.fixture
    def restore_logging(self) -> Any:
        import logging

        import structlog

        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        yield
        structlog.reset_defaults()
        root.handlers[:] = handlers
        root.setLevel(level)

    def test_a_log_line_goes_to_stderr_and_stdout_is_one_json_document(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        restore_logging: Any,
    ) -> None:
        import json

        import structlog

        from scripts import seed_e2e

        def fake_seed(run_tag: str | None = None) -> dict[str, Any]:
            structlog.get_logger("repo").info("tutor_grant_created", grant_id="g-1")
            return {"runTag": "x"}

        monkeypatch.setattr(seed_e2e, "ensure_supabase_env", lambda: None)
        monkeypatch.setattr(seed_e2e, "seed", fake_seed)

        assert seed_e2e.main([]) == 0

        out, err = capsys.readouterr()
        assert json.loads(out) == {"runTag": "x"}
        assert "tutor_grant_created" in err


_E2E_DIR = Path(__file__).resolve().parents[1] / "web" / "e2e"


class TestInviteOnlyStudentKeepsTheSeededParentsInboxEmpty:
    """T32: redeeming `declining`'s code notifies the seeded parent (SPEC §b.4)."""

    def test_the_contract_declares_the_invite_only_students_code(self) -> None:
        spec = (_E2E_DIR / "seed-contract.spec.ts").read_text(encoding="utf-8")
        assert '"students.inviteOnly.parentInviteCode": "string"' in spec
        assert 'account("students.inviteOnly")' in spec
        assert "inviteOnly:" in (_E2E_DIR / "seed.ts").read_text(encoding="utf-8")

    def test_the_seed_mints_a_code_for_a_student_no_parent_is_linked_to(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "scripts" / "seed_e2e.py").read_text(
            encoding="utf-8"
        )
        assert '_signup_account("invite-only", Role.student, run_tag)' in source
        assert "get_or_create_parent_code(invite_only_uuid)" in source
        # The seeded parent is linked to exactly one student, and it is not this one.
        assert source.count("link_in_session(") == 1
        assert "link_in_session(link_session, parent_uuid, declining_uuid)" in source

    def test_the_fresh_visitor_journey_redeems_that_code_and_not_the_declining_one(self) -> None:
        text = (_E2E_DIR / "parent-journey.spec.ts").read_text(encoding="utf-8")
        first = text.index('test("a fresh visitor joins')
        second = text.index('test("the seeded parent sees')
        fresh_visitor = text[first:second]
        assert "seed.students.inviteOnly" in fresh_visitor
        assert "declining" not in fresh_visitor.replace("`declining`", "")
        assert "parentInviteCode" in fresh_visitor  # non-vacuity: the code is still redeemed
