"""Tests for QuestionGenerator, its N3 verification gates, and the
generate-quiz / teacher-quiz CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.generation import GeneratedQuestion, GeneratedQuiz, QuestionValidityCheck
from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import WeakArea, WeaknessReport
from lemely.io.question_gates import MAX_GENERATION_ATTEMPTS, verify_question
from lemely.io.question_generation import QuestionGenerator
from lemely.io.teacher_quiz import TeacherQuizBuilder
from lemely.runtime.errors import ParseError


def _weakness(topics: list[str]) -> WeaknessReport:
    return WeaknessReport(
        weak_areas=[
            WeakArea(topic=t, lost_marks=3, maximum_marks=10, accuracy=0.7, question_ids=[f"q{i}"])
            for i, t in enumerate(topics)
        ]
    )


def _generated_question(
    topic: str,
    *,
    question_type: QuestionType = QuestionType.EXPLANATION,
    solution_expr: str | None = None,
    answer: str | None = None,
) -> GeneratedQuestion:
    return GeneratedQuestion(
        topic=topic,
        difficulty="standard",
        prompt=f"Explain {topic}.",
        model_answer=f"Model answer for {topic}.",
        mark_scheme_points=[f"Point 1 for {topic}", f"Point 2 for {topic}"],
        total_marks=2,
        question_type=question_type,
        solution_expr=solution_expr,
        answer=answer,
    )


def _validity_response(
    *,
    well_posed: bool = True,
    missing_data: bool = False,
    contradictory: bool = False,
    single_answer: bool = True,
) -> QuestionValidityCheck:
    return QuestionValidityCheck(
        well_posed=well_posed,
        missing_data=missing_data,
        contradictory=contradictory,
        single_answer=single_answer,
    )


def _dispatch_client(*, quiz_sequence, validity_sequence=None) -> MagicMock:
    """A MagicMock GeminiClient whose generate_structured dispatches on
    response_schema (GeneratedQuiz vs QuestionValidityCheck), matching how
    QuestionGenerator/question_gates actually call it."""
    client = MagicMock()
    quiz_iter = iter(quiz_sequence)
    validity_iter = iter(validity_sequence or [])

    def _side_effect(*, response_schema, **kwargs):
        if response_schema is GeneratedQuiz:
            return next(quiz_iter)
        if response_schema is QuestionValidityCheck:
            return next(validity_iter)
        raise AssertionError(f"unexpected response_schema {response_schema!r}")

    client.generate_structured.side_effect = _side_effect
    return client


class TestQuestionGeneratorUnit:
    def test_calls_generate_structured_with_generation_tag(self) -> None:
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[_generated_question("Waves")])
            ],
            validity_sequence=[_validity_response()],
        )
        generator = QuestionGenerator(client)
        result = generator.generate(_weakness(["Waves"]), subject_code="0625", count=1)

        assert isinstance(result, GeneratedQuiz)
        assert len(result.questions) == 1
        assert result.questions[0].verified_by == "validity_only"
        generation_calls = [
            c
            for c in client.generate_structured.call_args_list
            if c.kwargs["response_schema"] is GeneratedQuiz
        ]
        assert len(generation_calls) == 1
        assert generation_calls[0].kwargs["task_tag"] == "generation"

    def test_caps_at_min_count_len_weak_areas(self) -> None:
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[_generated_question("Waves")]),
                GeneratedQuiz(subject_code="0625", questions=[_generated_question("Optics")]),
            ],
            validity_sequence=[_validity_response(), _validity_response()],
        )
        generator = QuestionGenerator(client)
        # count=5 but only 2 weak areas: one generation call per area, never 5.
        result = generator.generate(_weakness(["Waves", "Optics"]), subject_code="0625", count=5)
        generation_calls = [
            c
            for c in client.generate_structured.call_args_list
            if c.kwargs["response_schema"] is GeneratedQuiz
        ]
        assert len(generation_calls) == 2
        assert len(result.questions) == 2

    def test_questions_have_model_answer_and_points(self) -> None:
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[_generated_question("Waves")]),
                GeneratedQuiz(subject_code="0625", questions=[_generated_question("Forces")]),
            ],
            validity_sequence=[_validity_response(), _validity_response()],
        )
        generator = QuestionGenerator(client)
        result = generator.generate(_weakness(["Waves", "Forces"]), subject_code="0625")
        assert len(result.questions) == 2
        for q in result.questions:
            assert q.model_answer
            assert q.mark_scheme_points
            assert q.verified_by == "validity_only"

    def test_verified_by_and_rejection_reason_from_gemini_are_never_trusted(self) -> None:
        """A GeneratedQuestion whose JSON output happened to self-report
        verified_by must not have that value pass through untouched — only
        verify_question's own finding may end up in the returned item."""
        hallucinated = _generated_question("Waves").model_copy(
            update={"verified_by": "sympy", "rejection_reason": "should never survive"}
        )
        client = _dispatch_client(
            quiz_sequence=[GeneratedQuiz(subject_code="0625", questions=[hallucinated])],
            validity_sequence=[_validity_response()],
        )
        generator = QuestionGenerator(client)
        result = generator.generate(_weakness(["Waves"]), subject_code="0625", count=1)
        assert result.questions[0].verified_by == "validity_only"
        assert result.questions[0].rejection_reason is None


class TestRegenerationLimits:
    def test_stops_after_3_attempts_and_does_not_loop(self) -> None:
        """N3 step 4: reject -> regenerate up to 3, and never an infinite
        loop. A persistently-wrong stated answer must exhaust the budget
        and be dropped, not retried forever."""
        bad = _generated_question(
            "Waves", question_type=QuestionType.CALCULATION, solution_expr="1 + 1", answer="99"
        )
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[bad]),
                GeneratedQuiz(subject_code="0625", questions=[bad]),
                GeneratedQuiz(subject_code="0625", questions=[bad]),
            ],
            validity_sequence=[_validity_response(), _validity_response(), _validity_response()],
        )
        generator = QuestionGenerator(client)
        result = generator.generate(_weakness(["Waves"]), subject_code="0625", count=1)

        assert result.questions == []
        generation_calls = [
            c
            for c in client.generate_structured.call_args_list
            if c.kwargs["response_schema"] is GeneratedQuiz
        ]
        assert len(generation_calls) == MAX_GENERATION_ATTEMPTS == 3

    def test_a_later_attempt_that_passes_is_returned(self) -> None:
        bad = _generated_question(
            "Waves", question_type=QuestionType.CALCULATION, solution_expr="1 + 1", answer="99"
        )
        good = _generated_question(
            "Waves", question_type=QuestionType.CALCULATION, solution_expr="1 + 1", answer="2"
        )
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[bad]),
                GeneratedQuiz(subject_code="0625", questions=[good]),
            ],
            validity_sequence=[_validity_response(), _validity_response()],
        )
        generator = QuestionGenerator(client)
        result = generator.generate(_weakness(["Waves"]), subject_code="0625", count=1)

        assert len(result.questions) == 1
        assert result.questions[0].verified_by == "sympy"
        # The rejection reason from attempt 1 must have reached attempt 2's prompt.
        second_call = [
            c
            for c in client.generate_structured.call_args_list
            if c.kwargs["response_schema"] is GeneratedQuiz
        ][1]
        assert "sympy" in second_call.kwargs["user_prompt"]


class TestVerifyQuestionValidityGate:
    def test_ill_posed_item_rejected_by_validity_pass(self) -> None:
        """Acceptance (1): a seeded ill-posed item (missing quantity) is
        rejected by the validity pass, from a recorded fixture response."""
        question = _generated_question(
            "Motion", question_type=QuestionType.CALCULATION, solution_expr="2 * 3", answer="6"
        )
        client = MagicMock()
        # Recorded fixture: Gemini's validity-check response for a question
        # that omits a needed quantity.
        client.generate_structured.return_value = _validity_response(
            well_posed=False, missing_data=True
        )
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason is not None
        assert "missing data" in result.rejection_reason
        client.generate_with_code_execution.assert_not_called()

    def test_non_solvable_type_passes_validity_only(self) -> None:
        question = _generated_question("Waves", question_type=QuestionType.EXPLANATION)
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "validity_only"
        assert result.rejection_reason is None
        client.generate_with_code_execution.assert_not_called()


class TestVerifyQuestionSympyGate:
    def test_answer_wrong_by_10_percent_rejected_by_sympy(self) -> None:
        """Acceptance (2), SymPy half: a stated answer wrong by 10% is
        rejected by SymPy, and rejection_reason records why."""
        question = _generated_question(
            "Speed",
            question_type=QuestionType.CALCULATION,
            solution_expr="100 / 4",  # = 25
            answer="27.5",  # +10%
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason is not None
        assert "sympy" in result.rejection_reason
        client.generate_with_code_execution.assert_not_called()

    def test_correct_item_passes_and_tagged_sympy(self) -> None:
        question = _generated_question(
            "Speed", question_type=QuestionType.CALCULATION, solution_expr="100 / 4", answer="25"
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sympy"
        assert result.rejection_reason is None
        client.generate_with_code_execution.assert_not_called()


class TestVerifyQuestionSandboxGate:
    def test_nonparseable_expression_routes_to_code_execution(self) -> None:
        """Acceptance (2), sandbox half: a non-parseable expression routes
        to the code-execution path and compares its result against a
        recorded code_execution_result fixture."""
        question = _generated_question(
            "Circuits",
            question_type=QuestionType.CALCULATION,
            solution_expr="N/A",
            answer="12",
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        # Recorded fixture: the code_execution_result output Gemini returned.
        client.generate_with_code_execution.return_value = "12"
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sandbox"
        assert result.rejection_reason is None
        client.generate_with_code_execution.assert_called_once()

    def test_sandbox_mismatch_is_rejected(self) -> None:
        question = _generated_question(
            "Circuits",
            question_type=QuestionType.CALCULATION,
            solution_expr="N/A",
            answer="12",
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.return_value = "99"
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason is not None
        assert "sandbox" in result.rejection_reason

    def test_missing_solution_expr_also_routes_to_sandbox(self) -> None:
        question = _generated_question(
            "Circuits", question_type=QuestionType.CALCULATION, solution_expr=None, answer="12"
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.return_value = "12"
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sandbox"


class TestRecallScopedToNumeric:
    def test_prose_recall_is_validity_only_and_never_spends_a_tool_call(self) -> None:
        """MUST-FIX 2: a prose RECALL item (no parseable numeric answer)
        must not be routed through the solver/sandbox path at all — it has
        no stated answer a solver can check, so treating it as solvable
        burns a paid code_execution call and then always rejects it with
        the misleading reason 'code execution result does not match the
        stated answer' (measured failure scenario: a 0625 quiz whose weak
        areas are recall topics -> 5 areas x 3 attempts = 45 Gemini calls
        including 15 tool calls, and 0 questions returned)."""
        question = _generated_question(
            "Photosynthesis",
            question_type=QuestionType.RECALL,
            answer="Photosynthesis converts light energy into chemical energy.",
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "validity_only"
        assert result.rejection_reason is None
        client.generate_with_code_execution.assert_not_called()

    def test_numeric_recall_is_still_solved_via_sympy(self) -> None:
        """Plan:611 scopes RECALL admission to *numeric* recall — this must
        keep working, not just the prose exclusion above."""
        question = _generated_question(
            "Atomic number of carbon",
            question_type=QuestionType.RECALL,
            solution_expr="6",
            answer="6",
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sympy"
        assert result.rejection_reason is None
        client.generate_with_code_execution.assert_not_called()

    def test_missing_answer_is_rejected_before_spending_a_tool_call(self) -> None:
        """MUST-FIX 2's backstop: an item with no stated answer at all must
        be rejected before _run_code_execution ever runs — not after a
        wasted call whose comparison against None always fails."""
        question = _generated_question(
            "Speed", question_type=QuestionType.CALCULATION, solution_expr="100 / 4", answer=None
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason == "no stated answer to verify"
        client.generate_with_code_execution.assert_not_called()


class TestRejectionLogging:
    def test_rejection_is_logged_with_subject_topic_reason_and_attempt(self) -> None:
        """MUST-FIX 3: every rejection must be logged with enough structure
        to diagnose a generation-quality regression in production —
        subject_code, topic, verified_by, rejection_reason, and which
        attempt it was. Asserted on the structured fields a call carries,
        never on log text (a text assertion would reproduce the very
        defect this test exists to catch: an item vanishing with no
        traceable record)."""
        question = _generated_question(
            "Motion", question_type=QuestionType.CALCULATION, solution_expr="2 * 3", answer="6"
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response(
            well_posed=False, missing_data=True
        )
        with patch("lemely.io.question_gates.structlog") as mock_structlog:
            mock_log = mock_structlog.get_logger.return_value
            verify_question(client, question, subject_code="0625", attempt=1)

        assert mock_log.warning.called
        _, kwargs = mock_log.warning.call_args
        assert kwargs["subject_code"] == "0625"
        assert kwargs["topic"] == "Motion"
        assert kwargs["verified_by"] is None
        assert kwargs["rejection_reason"] is not None
        assert kwargs["attempt"] == 1


class TestGenerationSummaryLogging:
    def test_summary_records_requested_generated_and_dropped_counts(self) -> None:
        """MUST-FIX 3's backstop: `generate()` must record a per-subject
        summary count of what it requested vs. what it returned, so a
        teacher receiving fewer questions than requested is visible in
        production even when every individual rejection scrolled off. This
        is what makes an area dropped with no error anywhere else
        detectable."""
        bad = _generated_question(
            "Waves", question_type=QuestionType.CALCULATION, solution_expr="1 + 1", answer="99"
        )
        good = _generated_question("Optics")
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[bad]),
                GeneratedQuiz(subject_code="0625", questions=[bad]),
                GeneratedQuiz(subject_code="0625", questions=[bad]),
                GeneratedQuiz(subject_code="0625", questions=[good]),
            ],
            validity_sequence=[
                _validity_response(),
                _validity_response(),
                _validity_response(),
                _validity_response(),
            ],
        )
        generator = QuestionGenerator(client)
        with patch("lemely.io.question_generation.structlog") as mock_structlog:
            mock_log = mock_structlog.get_logger.return_value
            result = generator.generate(
                _weakness(["Waves", "Optics"]), subject_code="0625", count=2
            )

        assert len(result.questions) == 1
        assert mock_log.info.called
        _, kwargs = mock_log.info.call_args
        assert kwargs["subject_code"] == "0625"
        assert kwargs["requested"] == 2
        assert kwargs["generated"] == 1
        assert kwargs["dropped"] == 1


class TestUnparseableNeverVerified:
    def test_sandbox_call_failure_is_never_tagged_verified(self) -> None:
        """UNPARSEABLE (which covers both unreadable text and a solver
        timeout) must never be recorded as verified — including when the
        code-execution fallback itself cannot produce a usable result."""
        question = _generated_question(
            "Circuits",
            question_type=QuestionType.CALCULATION,
            solution_expr="N/A",
            answer="12",
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.side_effect = ParseError(
            "no code_execution_result part"
        )
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason is not None

    def test_empty_sandbox_output_is_never_tagged_verified(self) -> None:
        question = _generated_question(
            "Circuits",
            question_type=QuestionType.CALCULATION,
            solution_expr="N/A",
            answer="12",
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.return_value = "   "
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None


class TestTeacherQuizVerifiedBy:
    def test_every_shortfall_item_carries_verified_by(self) -> None:
        """Acceptance (3): every teacher-quiz shortfall item carries
        verified_by."""
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(
                    subject_code="0625",
                    questions=[_generated_question("Waves")],
                ),
                GeneratedQuiz(
                    subject_code="0625",
                    questions=[_generated_question("Optics")],
                ),
            ],
            validity_sequence=[_validity_response(), _validity_response()],
        )
        generator = QuestionGenerator(client)
        builder = TeacherQuizBuilder(generator, existing_questions=[])
        weaknesses = _weakness(["Waves", "Optics"])
        quiz = builder.build("0625", weaknesses, count=2)

        assert len(quiz.questions) == 2
        for q in quiz.questions:
            assert q.verified_by is not None

    def test_existing_pool_items_are_not_forced_through_the_gate(self) -> None:
        """Only the generated shortfall goes through the gate — a
        pre-existing bank question is selected as-is (unchanged contract)."""
        existing = _generated_question("Forces")
        generator = QuestionGenerator(MagicMock())
        builder = TeacherQuizBuilder(generator, existing_questions=[existing])
        quiz = builder.build("0625", _weakness([]), count=1)

        assert len(quiz.questions) == 1
        assert quiz.questions[0].verified_by is None


class TestGenerateQuizCLI:
    def test_default_path_no_gemini_client(self, tmp_path) -> None:
        import json

        weakness_file = tmp_path / "weakness.json"
        weakness_file.write_text(
            json.dumps(
                {
                    "weak_areas": [
                        {
                            "topic": "Waves",
                            "lost_marks": 3,
                            "maximum_marks": 10,
                            "accuracy": 0.7,
                            "question_ids": ["q1"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch("lemely.io.gemini.GeminiClient") as mock_gc:
            runner = CliRunner()
            result = runner.invoke(cli, ["generate-quiz", str(weakness_file)])
            mock_gc.assert_not_called()
        assert result.exit_code == 0

    def test_use_ai_without_subject_code_fails(self, tmp_path) -> None:
        import json

        weakness_file = tmp_path / "weakness.json"
        weakness_file.write_text(json.dumps({"weak_areas": []}), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, ["generate-quiz", str(weakness_file), "--use-ai"])
        assert result.exit_code == 2
        assert "subject-code" in result.output.lower() or "subject_code" in result.output.lower()


class TestTeacherQuizCLI:
    def test_shortfall_items_carry_verified_by_in_json_output(self) -> None:
        """Acceptance (3), end to end: `teacher-quiz --json` output has
        verified_by set on every generated item."""
        client = _dispatch_client(
            quiz_sequence=[
                GeneratedQuiz(subject_code="0625", questions=[_generated_question("Waves")]),
            ],
            validity_sequence=[_validity_response()],
        )
        with patch("lemely.io.gemini.GeminiClient", return_value=client):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--json",
                    # --quiet (-> WARNING): workaround for click.testing.CliRunner's
                    # stream-mixing behaviour. Logs go to stderr in production
                    # (logging.py:35), but CliRunner merges stderr into .output.
                    # The generation summary (MUST-FIX 3) logs at INFO, which
                    # would land inside the JSON payload during test execution.
                    # This is not a production issue — real --json piping works
                    # correctly. (mix_stderr=False was removed in click 8.2, so
                    # this workaround is required with click 8.3.3.)
                    "--quiet",
                    "teacher-quiz",
                    "--subject",
                    "0625",
                    "--topics",
                    "Waves",
                    "--count",
                    "1",
                ],
            )
        assert result.exit_code == 0, result.output
        import json as _json

        payload = _json.loads(result.output)
        assert payload["questions"], payload
        for q in payload["questions"]:
            assert q["verified_by"] is not None
