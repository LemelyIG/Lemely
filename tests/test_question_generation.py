"""Tests for QuestionGenerator, its N3 verification gates, and the
generate-quiz / teacher-quiz CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.generation import GeneratedQuestion, GeneratedQuiz, QuestionValidityCheck
from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import WeakArea, WeaknessReport
from lemely.io.question_gates import MAX_GENERATION_ATTEMPTS, verify_question
from lemely.io.question_generation import QuestionGenerator
from lemely.io.teacher_quiz import TeacherQuizBuilder
from lemely.runtime.errors import CostCeilingError, ParseError


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

    def test_a_cost_ceiling_breach_in_the_sandbox_stops_the_generator(self) -> None:
        """The regenerate loop must not turn a budget stop into one more
        attempt: the error propagates out of QuestionGenerator.generate."""
        unprovable = _generated_question(
            "Circuits", question_type=QuestionType.CALCULATION, solution_expr="N/A", answer="12"
        )
        client = _dispatch_client(
            quiz_sequence=[GeneratedQuiz(subject_code="0625", questions=[unprovable])] * 3,
            validity_sequence=[_validity_response()] * 3,
        )
        client.generate_with_code_execution.side_effect = CostCeilingError("USD ceiling exceeded")
        with pytest.raises(CostCeilingError):
            QuestionGenerator(client).generate(
                _weakness(["Circuits"]), subject_code="0625", count=1
            )
        client.generate_with_code_execution.assert_called_once()


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

    @pytest.mark.parametrize(
        ("solution_expr", "answer"),
        [
            # The original six (Task 5, round 1).
            ("22/7", "3.14"),
            ("9.81*2", "19.6"),
            ("100/3", "33.3"),
            ("sqrt(2)", "1.41"),
            ("2*pi", "6.28"),
            ("0.5*3*4**2", "24 J"),
            # Fix round 2, Critical 1: the SAME irrational constant, written
            # identically or in an algebraically-equal different form. The
            # round-1 bug N()'d only the exact side, turning these into a
            # symbolic-vs-numeric term-key mismatch (false NOT_EQUAL).
            ("sqrt(2)", "sqrt(2)"),
            ("4*pi", "4*pi"),
            ("1/sqrt(2)", "sqrt(2)/2"),
            # Fix round 2, Critical 2: bare scientific notation, no unit --
            # the round-1 unit-stripper's regex truncated "2e3" to "2".
            ("2000", "2e3"),
            ("0.0015", "1.5e-3"),
            # Fix round 2, Important 3: a compound unit, and pi written with
            # a space instead of `*` (round 1's greedy letter-strip regex
            # discarded the `pi` factor entirely).
            ("9.81*2", "19.6 m/s"),
            ("2*pi", "2 pi"),
            # Fix round 2: "<mantissa> x 10^<exp>" magnitude notation is
            # PARSED (not refused) -- by lemely.core.equivalence since #270.
            ("24000", "2.4 x 10^4 J"),
        ],
    )
    def test_rounded_or_unit_bearing_stated_answers_verify_at_gate_sig_figs(
        self, solution_expr: str, answer: str
    ) -> None:
        """Spec 2026-09-26 §10 (#5): a stated answer rounded to 3 s.f., an
        exact symbolic solution against a decimal, and a unit-bearing
        answer all verify at the SymPy step with no paid sandbox call."""
        question = _generated_question(
            "Speed",
            question_type=QuestionType.CALCULATION,
            solution_expr=solution_expr,
            answer=answer,
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sympy", result.rejection_reason
        client.generate_with_code_execution.assert_not_called()

    @pytest.mark.parametrize(
        ("solution_expr", "answer"),
        [
            # Fix round 2, Critical 2: a genuinely wrong scientific-notation
            # answer must still be rejected -- not accidentally accepted by
            # a broken unit-stripper corrupting the comparison.
            ("2", "2e3"),
            ("1.5", "1.5e-3"),
            # Fix round 2, Important 3: "x 10^n" magnitude, wrong by orders
            # of magnitude once correctly parsed.
            ("2.4", "2.4 x 10^4 J"),
            ("3", "3.0 x 10^8 m/s"),
            # Fix round 2, Important 3: a genuinely different quantity
            # (a factor of pi, or an extra free-symbol term) must never be
            # silently reduced to the bare number by over-eager stripping.
            ("24", "24 pi"),
            ("6", "6x"),
            ("6", "6 x"),
            ("24", "24 x - 1"),
            ("24", "24 J 5"),
            # Plain wrong answers, no unit/notation involved at all.
            ("27.5", "25"),
            ("100/4", "27.5"),
            # Fix round 4, Important: SI-prefixed and % tails are left
            # completely untouched (never scaled), so a stated answer that
            # is wrong by exactly the prefix's magnitude must still be
            # rejected -- not silently accepted by a strip that discards
            # the prefix without applying it.
            ("0.5*3*4**2", "24 kJ"),
            ("24", "24 mJ"),
            ("24", "24 mm"),
            ("24", "24.0 kJ"),
            # Fix round 4, Important (documenting the actual outcome for
            # the CORRECT-but-prefixed direction of the same policy): since
            # a prefix is never scaled, a genuinely correct prefixed answer
            # does not verify via SymPy either -- "24 kJ" parses as the
            # free symbol `kJ` (spec 2026-09-26 controller decision: never
            # scale by prefix, `m`/`T` are too ambiguous between unit and
            # milli-/tesla-vs-variable), so the comparison against a
            # unitless 24000 is a genuine structural mismatch, not a
            # magnitude one.
            ("24000", "24 kJ"),
            ("0.024", "24 mm"),
        ],
    )
    def test_incorrect_or_malformed_stated_answers_are_rejected_by_sympy_not_sandbox(
        self, solution_expr: str, answer: str
    ) -> None:
        """Fix round 2: every one of these must be a HARD sympy-step
        rejection (a real disproof) -- never routed to the sandbox, which
        would mean the sig-fig gate merely failed to prove rather than
        actively disproved."""
        question = _generated_question(
            "Speed",
            question_type=QuestionType.CALCULATION,
            solution_expr=solution_expr,
            answer=answer,
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason is not None
        assert "sympy" in result.rejection_reason
        client.generate_with_code_execution.assert_not_called()

    def test_a_percent_stated_answer_is_rejected_though_not_by_sympy_directly(self) -> None:
        """Fix round 4, Important: "%" is never stripped either (0.24 vs
        "24 %" would need a /100 scale this module refuses to guess at,
        same reasoning as an SI prefix). Unlike the plain prefix cases
        above, "%" makes `parse_expr_safe` return `None` outright (it is
        not a valid identifier character), so `_compare_stated` reports
        UNPARSEABLE rather than NOT_EQUAL -- which correctly falls through
        to the sandbox (the existing, documented UNPARSEABLE behaviour),
        rather than a hard sympy-level reject. The final verified_by must
        still end up None once the sandbox's own answer also fails to
        match."""
        question = _generated_question(
            "Speed", question_type=QuestionType.CALCULATION, solution_expr="24", answer="24 %"
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.return_value = "24"
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by is None
        assert result.rejection_reason is not None
        client.generate_with_code_execution.assert_called_once()

    @pytest.mark.parametrize(
        "stated",
        ["24 kJ", "24.0 kJ", "24 mJ", "24 mm", "24 %"],
    )
    def test_prefixed_or_percent_tails_are_never_stripped(self, stated: str) -> None:
        """Fix round 4, Important, at the helper level: an SI-prefixed or
        "%" tail must leave `stated` completely untouched -- round 2/3's
        `_UNIT_ATOM_RE` allowed an optional prefix and included "%" in the
        base whitelist, so it silently discarded the prefix's magnitude
        (or the /100 scale) instead of refusing to strip at all."""
        from lemely.io.question_gates import _strip_trailing_unit

        assert _strip_trailing_unit(stated) == stated

    @pytest.mark.parametrize(
        ("stated", "value"),
        [
            ("2.5 h", "2.5"),
            ("30 min", "30"),
            ("1.57 rad", "1.57"),
            ("0.3 T", "0.3"),
            ("4.7 F", "4.7"),
            ("2 H", "2"),
            ("45 deg", "45"),
        ],
    )
    def test_the_seven_missing_unprefixed_units_are_stripped(self, stated: str, value: str) -> None:
        """#266: hours, minutes, radians, tesla, farad, henry and degrees were
        not in the whitelist, so "2.5 h" fell through to a paid sandbox call."""
        from lemely.io.question_gates import _strip_trailing_unit

        assert _strip_trailing_unit(stated) == value

    @pytest.mark.parametrize(
        ("solution_expr", "answer"),
        [("5/2", "2.5 h"), ("0.3", "0.3 T"), ("pi/2", "1.57 rad"), ("45", "45 deg")],
    )
    def test_the_new_units_verify_at_the_sympy_step_with_no_sandbox_call(
        self, solution_expr: str, answer: str
    ) -> None:
        question = _generated_question(
            "Fields",
            question_type=QuestionType.CALCULATION,
            solution_expr=solution_expr,
            answer=answer,
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sympy", result.rejection_reason
        client.generate_with_code_execution.assert_not_called()

    @pytest.mark.parametrize(
        "stated", ["24 d", "24 x", "24 Q", "24 hh", "24 mT", "24 nF", "24 kH", "24 mm"]
    )
    def test_a_bare_non_unit_letter_or_a_prefixed_new_unit_is_still_not_stripped(
        self, stated: str
    ) -> None:
        """The dangling-letter and prefix guards must hold for the new single
        capitals too: "mT" is a prefixed tesla, not metre-then-tesla."""
        from lemely.io.question_gates import _strip_trailing_unit

        assert _strip_trailing_unit(stated) == stated

    def test_prefixed_stated_answers_never_report_equal_proven_via_the_stripper(self) -> None:
        """Fix round 4, Important, at the helper level: neither direction
        of the SI-prefix policy -- a wrong answer matching only because
        the prefix's magnitude was discarded, or a genuinely correct
        prefixed answer -- ever reaches `EQUAL_PROVEN` through
        `_compare_stated`. Both come out `not_equal`: the prefixed tail is
        never stripped, so it parses as a free symbol (`kJ`, `mm`) with a
        real, unresolvable coefficient mismatch against the unitless
        exact side, in EITHER direction."""
        from lemely.core.equivalence import VerdictKind
        from lemely.io.question_gates import _compare_stated

        # Wrong-by-the-prefix's-magnitude (must never verify).
        assert _compare_stated("0.5*3*4**2", "24 kJ").kind is VerdictKind.NOT_EQUAL
        assert _compare_stated("24", "24 mJ").kind is VerdictKind.NOT_EQUAL
        assert _compare_stated("24", "24 mm").kind is VerdictKind.NOT_EQUAL
        # Correct-but-prefixed (documents the actual outcome: also
        # not_equal, for the same reason -- a real, unresolvable free
        # symbol, not a magnitude mismatch this module could fix by
        # scaling).
        assert _compare_stated("24000", "24 kJ").kind is VerdictKind.NOT_EQUAL
        assert _compare_stated("0.024", "24 mm").kind is VerdictKind.NOT_EQUAL

    def test_x_times_ten_magnitude_is_read_by_equivalence_without_overflow(self) -> None:
        """Fix round 4, Minor, carried by #270: the gate used to rewrite
        ``"<mantissa> x 10^<exp>"`` itself with its own regex, and before
        that computed ``mantissa * 10.0**exponent`` in Python floats, which
        raised an uncaught `OverflowError` for an exponent this large
        and aborted the whole generation request. #270 moved the rule from
        the gate into `lemely.core.equivalence` (``_TIMES_X_RE``): the shape
        reaches `parse_expr_safe` unchanged, which reads the ``x`` as times
        and lets SymPy's arbitrary-precision arithmetic hold ``10**400``
        exactly. Asserted on the parse rather than through
        `verify_question`/`_compare_stated`: for a magnitude this extreme,
        `equivalence.equivalent`'s own tolerance check (`_magnitude`'s
        ``complex(value.evalf())``) overflows past double-precision range,
        ~1e308, and resolves the comparison first either way."""
        from lemely.core.equivalence import parse_expr_safe

        expr = parse_expr_safe("2 x 10^400 J")
        j = parse_expr_safe("J")
        assert expr is not None
        assert j is not None
        assert expr == 2 * 10**400 * j

    def test_x_times_ten_magnitude_is_read_by_equivalence_without_underflow(self) -> None:
        """Fix round 4, Minor, carried by #270: the float computation
        silently underflowed a very negative exponent to exactly ``0.0``,
        discarding the mantissa. The rule now lives in
        `lemely.core.equivalence` (#270 moved it from the gate), and the
        parse is exact -- never a Python float, so no underflow. See the
        previous test's docstring for why this is asserted on the parse."""
        from lemely.core.equivalence import parse_expr_safe

        expr = parse_expr_safe("2 x 10^-400 J")
        j = parse_expr_safe("J")
        assert expr is not None
        assert j is not None
        assert expr != 0
        assert expr == 2 * j / 10**400

    @pytest.mark.parametrize(
        "stated",
        ["24 km/s", "24 kJ/s", "24 / s", "24*s"],
    )
    def test_dangling_operator_tails_are_never_stripped(self, stated: str) -> None:
        """Task 5 addendum (a), folded into fix round 5: `"24 km/s"` used
        to strip to `"24 km/"`, `"24 kJ/s"` to `"24 kJ/"`, `"24 / s"` to
        `"24 /"` and `"24*s"` to `"24*"` -- each a dangling operator that
        fails to parse (UNPARSEABLE), buying a needless paid sandbox
        call. `_UNIT_TAIL_RE`'s lookbehind now also excludes a preceding
        separator (`/`, the middle dot, `*`, `^`), and
        `_strip_trailing_unit` refuses a strip that would still leave one
        dangling -- none of these four may be touched at all."""
        from lemely.io.question_gates import _strip_trailing_unit

        assert _strip_trailing_unit(stated) == stated

    @pytest.mark.parametrize(
        "stated",
        ["24 km/s", "24 kJ/s", "24 / s", "24*s"],
    )
    def test_dangling_operator_tails_leave_step_1s_not_equal_standing(self, stated: str) -> None:
        """Task 5 addendum (a): since none of these four are ever
        stripped, `_compare_stated` never recurses into step 3 at all --
        the verdict returned is exactly step 1's own real, structural
        disproof, never silently downgraded to UNPARSEABLE (which would
        route to the sandbox) by a bad strip."""
        from lemely.core.equivalence import VerdictKind
        from lemely.io.question_gates import _compare_stated

        assert _compare_stated("24", stated).kind is VerdictKind.NOT_EQUAL

    @pytest.mark.parametrize(
        ("exact", "stated"),
        [
            ("2", "2 x 10^400"),
            ("2", "2*10**400"),
            ("2", "2 x 10^308"),
        ],
    )
    def test_extreme_magnitude_comparisons_never_raise_and_never_verify(
        self, exact: str, stated: str
    ) -> None:
        """Task 5 addendum (b), folded into fix round 5:
        `_ToleranceSpec._sig_figs_candidate` (lemely/core/equivalence.py)
        computes `math.floor(math.log10(abs(ref)))`, which raises
        `OverflowError` once `ref` overflows to `inf` as a Python float --
        reachable through `GATE_SIG_FIGS=3`, which every comparison this
        module makes passes as `sig_figs`. `_safe_equivalent` catches it
        (and a `ValueError`) and reports UNPARSEABLE instead of letting it
        escape uncaught -- nothing catches it around `verify_question`."""
        from lemely.core.equivalence import VerdictKind
        from lemely.io.question_gates import _compare_stated

        verdict = _compare_stated(exact, stated)
        assert verdict.kind is not VerdictKind.EQUAL_PROVEN


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

    def test_sandbox_result_rounded_differently_still_verifies(self) -> None:
        question = _generated_question(
            "Circuits", question_type=QuestionType.CALCULATION, solution_expr="N/A", answer="19.6"
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.return_value = "19.62"
        result = verify_question(client, question, subject_code="0625")

        assert result.verified_by == "sandbox"

    def test_cost_ceiling_breach_in_the_sandbox_call_propagates(self) -> None:
        """Spec 2026-09-26 §9 (#8): CostCeilingError subclasses
        ExternalServiceError, so the sandbox handler used to swallow a
        budget stop as "produced no usable result" and reject the question
        instead of stopping the run."""
        question = _generated_question(
            "Circuits", question_type=QuestionType.CALCULATION, solution_expr="N/A", answer="12"
        )
        client = MagicMock()
        client.generate_structured.return_value = _validity_response()
        client.generate_with_code_execution.side_effect = CostCeilingError("USD ceiling exceeded")
        with pytest.raises(CostCeilingError):
            verify_question(client, question, subject_code="0625")


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
                    # this workaround is required on the pinned click 8.4.2.)
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
