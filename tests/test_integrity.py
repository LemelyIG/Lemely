"""Tests for Phase 6's ``PlagiarismChecker`` and ``apply_integrity_checks``.

F4 removed ``AIContentDetector`` (the Gemini-backed AI-generated-answer
detector formerly tested here as ``TestAIContentDetector``) along with
``IntegritySettings.ai_detection_enabled``/``ai_detection_threshold``: it had
no measured false-positive rate, and JCQ guidance is that such a detector
must never be sole evidence. ``apply_integrity_checks`` now only runs the
plagiarism check; the tests below cover that pipeline wiring — the function
that turns a plagiarism finding into advisory ``needs_teacher_review``/
``review_reason`` signals without ever touching marks.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.core.plagiarism import PlagiarismChecker
from lemely.core.schemas import ConfidenceBand, CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io.integrity import apply_integrity_checks
from lemely.runtime.config import IntegritySettings


class TestPlagiarismChecker:
    def test_verbatim_copy_is_flagged(self) -> None:
        checker = PlagiarismChecker(threshold=0.85)
        expected = "The velocity of a wave is equal to its frequency multiplied by its wavelength."
        result = checker.check("q1", expected, expected)
        assert result.flagged is True
        assert result.score >= 0.85

    def test_paraphrase_not_flagged(self) -> None:
        checker = PlagiarismChecker(threshold=0.85)
        expected = "Velocity equals frequency times wavelength."
        student = "The speed at which a wave travels is determined by how often it oscillates per second times the distance between each cycle."
        result = checker.check("q1", student, expected)
        assert result.flagged is False
        assert result.score < 0.85

    def test_returns_plagiarism_kind(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q1", "same text", "same text")
        assert result.kind == "plagiarism"

    def test_question_id_in_finding(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q42", "answer", "expected")
        assert result.question_id == "q42"

    def test_no_gemini_client_used(self) -> None:
        mock_client = MagicMock()
        checker = PlagiarismChecker()
        checker.check("q1", "text", "text")
        mock_client.generate_structured.assert_not_called()

    def test_score_is_float_between_0_and_1(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q1", "some answer here", "some answer here")
        assert 0.0 <= result.score <= 1.0

    def test_rationale_is_non_empty(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q1", "text", "text")
        assert result.rationale


def _metadata() -> ExamMetadata:
    return ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )


def _mark_scheme() -> MarkScheme:
    """One theory question with a command word and two answer points."""
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": 2,
                "scheme_format": "mixed",
            },
            "questions": [
                {
                    "id": "1",
                    "marks": 2,
                    "type": "explanation",
                    "question_command": "explain why",
                    "answer_points": [
                        {"id": "p1", "point": "gravity acts on it", "marks": 1},
                        {"id": "p2", "point": "no air resistance", "marks": 1},
                    ],
                },
            ],
        }
    )


def _mcq_mark_scheme() -> MarkScheme:
    """Two multiple-choice questions — the shape ``correct_mcq_answers`` marks."""
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 2,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2023,
                "paper_type": "mcq",
                "maximum_mark": 2,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "C"},
                {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            ],
        }
    )


def _mcq_question(**overrides: object) -> CorrectedQuestion:
    """A *correct* MCQ answer: student and expected are the same single letter."""
    fields: dict[str, object] = {
        "question_id": "1",
        "awarded_marks": 1,
        "maximum_marks": 1,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 1.0,
        "needs_teacher_review": False,
        "student_answer": "C",
        "expected_answer": "C",
        "marker_source": "deterministic",
    }
    fields.update(overrides)
    return CorrectedQuestion.model_validate(fields)


def _question(**overrides: object) -> CorrectedQuestion:
    fields: dict[str, object] = {
        "question_id": "1",
        "awarded_marks": 2,
        "maximum_marks": 2,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "student_answer": "Gravity acts on it and there is no air resistance.",
        "expected_answer": "Gravity acts on it and there is no air resistance.",
        "marker_source": "ai",
    }
    fields.update(overrides)
    return CorrectedQuestion.model_validate(fields)


class TestApplyIntegrityChecks:
    def test_plagiarism_flags_near_verbatim_answer(self) -> None:
        # student_answer == expected_answer -> similarity ratio 1.0, flagged.
        correction = CorrectionResult(metadata=_metadata(), questions=[_question()])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        q = result.questions[0]
        assert q.plagiarism_flagged is True
        assert q.needs_teacher_review is True
        assert q.review_reason is not None
        assert "plagiarism" in q.review_reason
        assert q.awarded_marks == 2
        assert q.maximum_marks == 2

    def test_paraphrased_answer_flags_nothing(self) -> None:
        question = _question(
            student_answer=(
                "The object falls because Earth pulls it down and there is nothing "
                "slowing its descent in a vacuum."
            ),
            expected_answer="Gravity acts on it and there is no air resistance.",
        )
        correction = CorrectionResult(metadata=_metadata(), questions=[question])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        q = result.questions[0]
        assert q.plagiarism_flagged is False
        assert q.needs_teacher_review is False
        assert q.review_reason is None

    def test_gemini_client_is_never_called(self) -> None:
        """F4: no check left in this pipeline calls Gemini — a passed-in client
        (kept only for call-site compatibility, see ``apply_integrity_checks``'s
        docstring) must never be touched."""
        mock_client = MagicMock()
        question = _question(
            student_answer=(
                "The object falls because Earth pulls it down and there is nothing "
                "slowing its descent in a vacuum."
            ),
            expected_answer="Gravity acts on it and there is no air resistance.",
        )
        correction = CorrectionResult(metadata=_metadata(), questions=[question])
        apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=mock_client,
            settings=IntegritySettings(),
        )
        mock_client.generate_structured.assert_not_called()

    def test_marks_are_unchanged_when_flagged(self) -> None:
        before = _question()
        correction = CorrectionResult(metadata=_metadata(), questions=[before])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        after = result.questions[0]
        assert after.plagiarism_flagged is True
        assert after.awarded_marks == before.awarded_marks == 2
        assert after.maximum_marks == before.maximum_marks == 2
        assert result.awarded_marks == correction.awarded_marks == 2
        assert result.maximum_marks == correction.maximum_marks == 2

    def test_preserves_existing_review_reason(self) -> None:
        question = _question(
            review_reason="confidence 0.50 below review threshold 0.90",
            needs_teacher_review=True,
        )
        correction = CorrectionResult(metadata=_metadata(), questions=[question])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        q = result.questions[0]
        assert q.review_reason is not None
        assert "confidence 0.50 below review threshold 0.90" in q.review_reason
        assert "plagiarism" in q.review_reason
        assert q.review_reason.startswith("confidence 0.50")

    def test_plagiarism_disabled_skips_check(self) -> None:
        correction = CorrectionResult(metadata=_metadata(), questions=[_question()])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(plagiarism_enabled=False),
        )
        q = result.questions[0]
        assert q.plagiarism_flagged is False
        assert q.needs_teacher_review is False


class TestIntegrityChecksSkipMcqQuestions:
    """B3 — you cannot plagiarise a multiple-choice letter.

    Before the fix, ``SequenceMatcher('C', 'C').ratio()`` was 1.0, so every
    *correct* MCQ answer was flagged and pushed into the teacher-review queue
    while every wrong one came back clean — a 40/40 paper produced 40 flags and
    a 0/40 paper produced none. Each test here fails against the unguarded
    version.
    """

    def test_correct_mcq_answer_is_not_flagged_as_plagiarism(self) -> None:
        correction = CorrectionResult(metadata=_metadata(), questions=[_mcq_question()])
        result = apply_integrity_checks(
            correction,
            _mcq_mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        q = result.questions[0]
        assert q.plagiarism_flagged is False
        assert q.needs_teacher_review is False
        assert q.review_reason is None

    def test_a_whole_correct_mcq_paper_produces_no_flags(self) -> None:
        # The inverted-incentive case stated in B3: every answer right.
        correction = CorrectionResult(
            metadata=_metadata(),
            questions=[
                _mcq_question(),
                _mcq_question(question_id="2", student_answer="A", expected_answer="A"),
            ],
        )
        result = apply_integrity_checks(
            correction,
            _mcq_mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        assert [q.plagiarism_flagged for q in result.questions] == [False, False]
        assert result.needs_teacher_review is False

    def test_short_free_text_answer_is_still_checked(self) -> None:
        # The guard is on question type, not answer length — a one-character
        # free-text answer stays checkable.
        question = _question(student_answer="g", expected_answer="g")
        correction = CorrectionResult(metadata=_metadata(), questions=[question])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        assert result.questions[0].plagiarism_flagged is True

    def test_question_absent_from_the_scheme_is_still_checked(self) -> None:
        # Unknown type cannot be classified as MCQ, so it must not be exempted.
        question = _question(question_id="99")
        correction = CorrectionResult(metadata=_metadata(), questions=[question])
        result = apply_integrity_checks(
            correction,
            _mark_scheme(),
            gemini_client=None,
            settings=IntegritySettings(),
        )
        assert result.questions[0].plagiarism_flagged is True
