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

import uuid
from datetime import UTC, datetime

from lemely.core.at_risk import (
    AtRiskReason,
    BelowTargetEvidence,
    TargetRuleStatus,
    assess_at_risk,
)
from lemely.core.difficulty import allocate_difficulty
from lemely.core.history import GRADE_ORDER, StudentHistory, is_grade_bearing
from lemely.core.placement import MIN_QUESTIONS, MIN_TOPICS
from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD, ConfidenceBand
from lemely.db.models.enums import QuestionSource
from scripts.seed_e2e import (
    BELOW_TARGET_GRADE,
    BELOW_TARGET_POSITIONS_BELOW,
    BELOW_TARGET_SCORE,
    CONTROL_SCORES,
    CORRECTED_SCORE,
    DECLINING_DAYS_AGO,
    DECLINING_SCORES,
    INACTIVE_SCORE,
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
    REVIEW_ITEM_CONFIDENCE_SCORE,
    SUBJECT_CODE,
    accuracy_report_for_score,
    below_target_recorded_at,
    build_email,
    build_empty_parent_phone,
    build_password,
    build_phone,
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
    paper_record_for_scenario,
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

    def test_build_phone_shape(self) -> None:
        phone = build_phone("abcdef123456")
        assert phone.startswith("+20")
        assert len(phone) == 13  # "+20" + 10 digits
        assert phone[3:].isdigit()

    def test_build_phone_is_deterministic(self) -> None:
        assert build_phone("sametag0000") == build_phone("sametag0000")

    def test_build_phone_differs_across_tags(self) -> None:
        assert build_phone("tag-one-000") != build_phone("tag-two-111")

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
# build_empty_parent_phone — must never collide with build_phone(run_tag).
# ---------------------------------------------------------------------------


class TestBuildEmptyParentPhone:
    def test_differs_from_the_linked_parents_phone_for_the_default_tag_length(self) -> None:
        """The exact regression this function exists to prevent: a same-tag
        *suffix* would leave build_phone's first-10-characters window
        unchanged for any run_tag of length >= 10 (the default 12-hex-char
        tag included), silently colliding with the linked parent's own
        number and tripping the 30s per-phone OTP cooldown."""
        run_tag = "abcdef123456"
        assert build_empty_parent_phone(run_tag) != build_phone(run_tag)

    def test_is_deterministic(self) -> None:
        assert build_empty_parent_phone("tag1") == build_empty_parent_phone("tag1")

    def test_differs_across_tags(self) -> None:
        # Tags differing from their first character: build_phone only reads
        # the first 10 characters, so two tags that only differ *after*
        # position 10 - "empty-"'s own 6 chars would still collide (see
        # test_differs_from_the_linked_parents_phone_for_the_default_tag_length).
        assert build_empty_parent_phone("one-tag") != build_empty_parent_phone("two-tag")

    def test_shape_matches_build_phone(self) -> None:
        phone = build_empty_parent_phone("abcdef123456")
        assert phone.startswith("+20")
        assert len(phone) == 13


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
        "class_row": {"classId": "c1", "name": "n", "joinCode": "J1"},
        "students": {
            "declining": {"userId": "d1", "expectedAtRiskReasons": ["declining_trend"]},
            "inactive": {"userId": "i1", "expectedAtRiskReasons": ["inactive"]},
            "control": {"userId": "c1", "expectedAtRiskReasons": []},
            "correctedPaper": {
                "userId": "cp1",
                "expectedAtRiskReasons": [],
                "correctedPaperId": "attempt-1",
            },
        },
        "parent": {"userId": "p1", "phone": "+201000000000", "linkedStudent": "declining"},
        "review_item": {"itemId": "ri1", "attemptId": "at1", "studentKey": "inactive"},
        "quiz": {
            "quizId": "q1",
            "assignmentId": "as1",
            "submissionId": "sub1",
            "submittedBy": "control",
            "status": "marked",
        },
        "empty_teacher": {"userId": "et1"},
        "empty_parent": {"userId": "ep1", "phone": "+201000000001"},
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
            "class": {"classId": "c1", "name": "n", "joinCode": "J1"},
            "students": {
                "declining": {"userId": "d1", "expectedAtRiskReasons": ["declining_trend"]},
                "inactive": {"userId": "i1", "expectedAtRiskReasons": ["inactive"]},
                "control": {"userId": "c1", "expectedAtRiskReasons": []},
                "correctedPaper": {
                    "userId": "cp1",
                    "expectedAtRiskReasons": [],
                    "correctedPaperId": "attempt-1",
                },
            },
            "parent": {"userId": "p1", "phone": "+201000000000", "linkedStudent": "declining"},
            "reviewItem": {"itemId": "ri1", "attemptId": "at1", "studentKey": "inactive"},
            "quiz": {
                "quizId": "q1",
                "assignmentId": "as1",
                "submissionId": "sub1",
                "submittedBy": "control",
                "status": "marked",
            },
            "emptyTeacher": {"userId": "et1"},
            "emptyParent": {"userId": "ep1", "phone": "+201000000001"},
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
        }

    def test_is_json_serializable(self) -> None:
        import json

        payload = build_result_payload(**_payload_kwargs())
        assert json.loads(json.dumps(payload)) == payload
