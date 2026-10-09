"""The marker reports whether an answer addresses its question (check G8)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog

from lemely.core.binding import BindingCheck, BindingReport
from lemely.core.loose_schemas import MarkScheme, Question
from lemely.core.schemas import (
    AIMarkResponse,
    CorrectionResult,
    ExtractedAnswers,
    PointVerdict,
)
from lemely.io import correction_ai
from lemely.io.correction_ai import (
    _build_ai_corrected,
    _build_ai_corrected_from_verdicts,
    correct_paper,
)
from lemely.io.gemini import GeminiClient, _strip_schema
from lemely.io.prompts.correction_ai import MARKER_SYSTEM_PROMPT, VERSION
from lemely.runtime.config import MarkingOptions, PathsSettings, load_settings

OFF_TOPIC_REASON = "binding unverified: answer appears to address a different question"
# sha256 of MARKER_SYSTEM_PROMPT at VERSION "5", the text before this check existed.
VERSION_5_PROMPT_SHA256 = "e1281162f0086b769a6686d38caab22c7bdd56560377f599a50aa624af3cea49"
SECTION_START = "**Last field: `addresses_question`"
SECTION_END = "---\n\n## Worked Examples"
# What each worked reply example gained so the examples show the whole reply.
EXAMPLE_ADDITION = ',\n   addresses_question="yes"'


def _scheme(theory: int, *, mcq: bool = False) -> MarkScheme:
    """``theory`` one-mark written questions "1", "2", …, then an optional MCQ."""
    questions: list[dict[str, Any]] = [
        {
            "id": str(n),
            "marks": 1,
            "type": "explanation",
            "answer_points": [{"id": "p1", "point": f"point for question {n}", "marks": 1}],
        }
        for n in range(1, theory + 1)
    ]
    if mcq:
        questions.append({"id": str(theory + 1), "marks": 1, "type": "mcq", "mcq_answer": "A"})
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Biology",
                "subject_code": "0610",
                "paper_number": 4,
                "paper_variant": 1,
                "session_month": "May/June",
                "session_year": 2021,
                "paper_type": "theory_extended",
                "maximum_mark": len(questions),
                "scheme_format": "mixed" if mcq else "point_based",
            },
            "questions": questions,
        }
    )


def _question(scheme: MarkScheme, qid: str) -> Question:
    return next(q for q in scheme.all_questions_flat() if q.id == qid)


# What a gated extraction of a scan attaches when nothing failed and its one
# retry is already spent, so a paper-scope G8 failure on top of it is a hold.
GATED = BindingReport(
    binder="label",
    checks=[BindingCheck(id="G1", passed=True, scope="paper", detail="All ids are known.")],
    verdict="pass",
    retried=True,
)


def _extracted(
    answers: dict[str, str],
    *,
    binding: BindingReport | None = None,
    dropped: list[str] | None = None,
    source_scan: str = "x.pdf",
) -> ExtractedAnswers:
    return ExtractedAnswers.model_validate(
        {
            "paper_id": "p",
            "source_scan": source_scan,
            "answers": [
                {"question_id": qid, "answer": text, "confidence": 0.95}
                for qid, text in answers.items()
            ],
            "dropped_question_ids": dropped or [],
            "binding": binding.model_dump() if binding is not None else None,
        }
    )


def _reply(
    addresses: str | None,
    *,
    awarded: int = 1,
    confidence: float = 0.95,
    feedback: str = "fb",
) -> AIMarkResponse:
    """A marker reply; ``addresses=None`` leaves the field out, as an old reply would."""
    body: dict[str, Any] = {
        "awarded_marks": awarded,
        "confidence": confidence,
        "matched_point_ids": ["p1"] if awarded else [],
        "feedback": feedback,
    }
    if addresses is not None:
        body["addresses_question"] = addresses
    return AIMarkResponse.model_validate(body)


def _mark_with(replies: dict[str, AIMarkResponse], **kwargs: Any) -> CorrectionResult:
    """Run ``correct_paper`` with the marker's reply fixed per question id."""

    def fake(_self: object, question: Question, *_args: object, **_kwargs: object):
        return replies[question.id]

    with patch.object(correction_ai.AICorrector, "mark_question", autospec=True, side_effect=fake):
        return correct_paper(gemini_client=MagicMock(), **kwargs)


def _paper(
    flags: list[str | None],
    *,
    binding: BindingReport | None = GATED,
    source_scan: str = "x.pdf",
    **reply_kwargs: Any,
) -> CorrectionResult:
    """One written question per flag, every one answered and marked."""
    ids = [str(n) for n in range(1, len(flags) + 1)]
    return _mark_with(
        {qid: _reply(flag, **reply_kwargs) for qid, flag in zip(ids, flags, strict=True)},
        mark_scheme=_scheme(len(flags)),
        extracted_answers=_extracted(
            {qid: f"answer {qid}" for qid in ids}, binding=binding, source_scan=source_scan
        ),
    )


def _g8(result: CorrectionResult) -> BindingCheck:
    assert result.binding is not None
    (check,) = [c for c in result.binding.checks if c.id == "G8"]
    return check


def _assert_g8_never_applies(marked: Callable[[list[str | None]], CorrectionResult]) -> None:
    """No report and no review reason, whatever the marker said about five answers."""
    baseline = marked([None] * 5)
    for flags in (["no"] * 5, ["yes", "yes", "no", "yes", "yes"], ["yes"] * 5):
        result = marked(flags)
        assert result.binding is None, flags
        assert [q.addresses_question for q in result.questions] == flags
        assert [q.review_reason for q in result.questions] == [None] * 5, flags
        assert [q.needs_teacher_review for q in result.questions] == [
            q.needs_teacher_review for q in baseline.questions
        ], flags
        assert result.needs_teacher_review == baseline.needs_teacher_review, flags


def _fake_client(tmp_path: Path, bodies: list[dict[str, Any]], **gemini: Any) -> GeminiClient:
    return _fake_client_and_sdk(tmp_path, bodies, **gemini)[0]


def _fake_client_and_sdk(
    tmp_path: Path, bodies: list[dict[str, Any]], **gemini: Any
) -> tuple[GeminiClient, MagicMock]:
    genai = MagicMock()
    genai.models.generate_content.side_effect = [
        MagicMock(
            text=json.dumps(body),
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
        )
        for body in bodies
    ]
    lemely_env = {k: v for k, v in os.environ.items() if k.startswith("LEMELY_")}
    with patch.dict(os.environ):
        for key in lemely_env:
            del os.environ[key]
        settings = load_settings(toml_path=None, cwd=tmp_path)
    settings = settings.model_copy(
        update={
            "paths": PathsSettings(cache_dir=tmp_path / ".cache", output_dir=tmp_path / "out"),
            "gemini": settings.gemini.model_copy(update=gemini),
        }
    )
    return GeminiClient(settings, _genai_client=genai), genai


# --- prompt -----------------------------------------------------------------


def test_marker_prompt_version_is_7():
    assert VERSION == "7"


def test_marker_prompt_explains_addresses_question_and_says_it_never_changes_the_mark():
    start = MARKER_SYSTEM_PROMPT.index(SECTION_START)
    section = " ".join(
        MARKER_SYSTEM_PROMPT[start : MARKER_SYSTEM_PROMPT.index(SECTION_END)].split()
    )
    for value in ("`yes`", "`no`", "`unclear`"):
        assert value in section
    assert "mark scheme entry" in section
    assert "never changes awarded_marks, confidence, matched_point_ids or feedback" in section
    # Last in the reply: after every marking field the prompt lists.
    for field in ("- awarded_marks:", "- confidence:", "- matched_point_ids:", "- feedback:"):
        assert MARKER_SYSTEM_PROMPT.index(field) < start


def test_marker_prompt_keeps_no_narrow_and_breaks_ties_towards_unclear():
    start = MARKER_SYSTEM_PROMPT.index(SECTION_START)
    section = " ".join(
        MARKER_SYSTEM_PROMPT[start : MARKER_SYSTEM_PROMPT.index(SECTION_END)].split()
    )
    # A wrong attempt on the same subject matter is `yes`, named case by case.
    for wrong_attempt in (
        "a wrong method",
        "a wrong quantity or unit",
        "a definition offered where a calculation is needed",
        "a muddled or incomplete attempt",
    ):
        assert wrong_attempt in section.lower()
    assert "plainly about a different topic or task from anything this entry concerns" in section
    assert "Being wrong, however badly, is never a reason for `no`" in section
    assert "torn between `no` and anything else, choose `unclear`" in section
    # The count of marking fields depends on the marking flags, so none is stated.
    assert "four fields" not in section
    # One example per verdict, so the boundary is shown and not only described.
    examples = section[section.index("For instance:") : section.index("This field never")]
    assert [examples.count(f"-> `{value}`") for value in ("yes", "no", "unclear")] == [1, 1, 1]


def test_worked_reply_examples_include_addresses_question():
    worked = MARKER_SYSTEM_PROMPT[MARKER_SYSTEM_PROMPT.index(SECTION_END) :]
    assert worked.count("-> awarded_marks=") == 3
    assert worked.count(EXAMPLE_ADDITION) == 3
    assert MARKER_SYSTEM_PROMPT.count(EXAMPLE_ADDITION) == 3


def test_marker_prompt_is_otherwise_unchanged_from_version_5():
    start = MARKER_SYSTEM_PROMPT.index(SECTION_START)
    end = MARKER_SYSTEM_PROMPT.index(SECTION_END)
    without_section = MARKER_SYSTEM_PROMPT[:start] + MARKER_SYSTEM_PROMPT[end:]
    without_additions = without_section.replace(EXAMPLE_ADDITION, "")
    assert hashlib.sha256(without_additions.encode()).hexdigest() == VERSION_5_PROMPT_SHA256


def test_reply_schema_lists_addresses_question_last_with_a_description():
    schema = AIMarkResponse.model_json_schema()
    assert list(schema["properties"])[-1] == "addresses_question"
    field = schema["properties"]["addresses_question"]
    assert field["enum"] == ["yes", "no", "unclear"]
    assert "Never changes the marks" in field["description"]


def test_wire_schema_requires_addresses_question(tmp_path: Path):
    for is_3x in (True, False):
        sent = _strip_schema(AIMarkResponse.model_json_schema(), is_3x=is_3x)
        assert sent["required"] == ["awarded_marks", "confidence", "feedback", "addresses_question"]
    # And in the request the client builds, on the API line the default model uses.
    body = {"awarded_marks": 1, "confidence": 0.95, "matched_point_ids": ["p1"], "feedback": "ok"}
    client, sdk = _fake_client_and_sdk(tmp_path, [body])
    correct_paper(_scheme(1), _extracted({"1": "an answer"}), gemini_client=client)
    config = sdk.models.generate_content.call_args.kwargs["config"]
    sent = config.response_json_schema or config.response_schema
    assert "addresses_question" in sent["required"]


def test_python_side_still_parses_a_reply_without_it():
    reply = AIMarkResponse.model_validate_json(
        '{"awarded_marks": 1, "confidence": 0.8, "feedback": "ok"}'
    )
    assert reply.addresses_question == "unclear"
    assert "addresses_question" not in reply.model_fields_set
    explicit = AIMarkResponse.model_validate_json(
        '{"awarded_marks": 1, "confidence": 0.8, "feedback": "ok", "addresses_question": "unclear"}'
    )
    assert "addresses_question" in explicit.model_fields_set


# --- builders ---------------------------------------------------------------


@pytest.mark.parametrize("flag", ["yes", "no", "unclear"])
def test_ai_corrected_carries_addresses_question(flag: str):
    question = _question(_scheme(1), "1")
    legacy = _build_ai_corrected(question, "an answer", _reply(flag))
    assert legacy.addresses_question == flag
    assert legacy.point_verdicts == []

    with_verdicts = _reply(flag).model_copy(
        update={
            "point_verdicts": [
                PointVerdict(point_id="p1", verdict="awarded", evidence_span="an answer")
            ]
        }
    )
    direct = _build_ai_corrected_from_verdicts(question, "an answer", with_verdicts, None, None)
    assert direct.addresses_question == flag
    dispatched = _build_ai_corrected(question, "an answer", with_verdicts, equivalence_gate=True)
    assert dispatched.point_verdicts  # the verdict path, not the legacy body
    assert dispatched.addresses_question == flag


def test_omitted_field_is_recorded_as_no_judgement(tmp_path: Path):
    question = _question(_scheme(1), "1")
    omitted = _reply(None)
    assert _build_ai_corrected(question, "an answer", omitted).addresses_question is None
    verdicts = [PointVerdict(point_id="p1", verdict="awarded", evidence_span="an answer")]
    omitted_with_verdicts = omitted.model_copy(update={"point_verdicts": verdicts})
    for cq in (
        _build_ai_corrected_from_verdicts(question, "an answer", omitted_with_verdicts, None, None),
        _build_ai_corrected(question, "an answer", omitted_with_verdicts, equivalence_gate=True),
    ):
        assert cq.point_verdicts
        assert cq.addresses_question is None
    # An explicit `unclear` is a judgement and is kept as one.
    assert _build_ai_corrected(question, "an answer", _reply("unclear")).addresses_question == (
        "unclear"
    )

    # Through the client: the reply text has no such key, on a gated extraction.
    body = {"awarded_marks": 1, "confidence": 0.95, "matched_point_ids": ["p1"], "feedback": "ok"}
    result = correct_paper(
        _scheme(1),
        _extracted({"1": "an answer"}, binding=GATED),
        gemini_client=_fake_client(tmp_path, [body]),
    )
    assert result.questions[0].marker_source == "ai"
    assert result.questions[0].addresses_question is None
    assert _g8(result).passed


@pytest.mark.parametrize("said", ["no", None])
def test_judgement_and_its_absence_survive_the_reply_cache(tmp_path: Path, said: str | None):
    body = {"awarded_marks": 1, "confidence": 0.95, "matched_point_ids": ["p1"], "feedback": "ok"}
    if said is not None:
        body["addresses_question"] = said
    # One SDK reply for two runs: the second run can only be served from the cache.
    client, sdk = _fake_client_and_sdk(tmp_path, [body])
    runs = [
        correct_paper(_scheme(1), _extracted({"1": "an answer"}), gemini_client=client)
        for _ in range(2)
    ]
    assert sdk.models.generate_content.call_count == 1
    assert [run.questions[0].marker_source for run in runs] == ["ai", "ai"]
    assert [run.questions[0].addresses_question for run in runs] == [said, said]


def test_omitted_replies_are_counted_in_one_log_line_per_paper():
    with structlog.testing.capture_logs() as logs:
        _paper(["yes", None, "unclear", None, "no"])
    assert [entry for entry in logs if entry["event"] == "marker_omitted_addresses_question"] == [
        {
            "event": "marker_omitted_addresses_question",
            "log_level": "warning",
            "component": "correct_paper",
            "omitted": 2,
            "marked": 5,
        }
    ]

    with structlog.testing.capture_logs() as logs:
        _paper(["yes", "unclear", "no"])
        _paper([None, None], binding=None)
    events = [entry for entry in logs if entry["event"] == "marker_omitted_addresses_question"]
    # Nothing when every reply carried it; counted with or without a binding report.
    assert [(entry["omitted"], entry["marked"]) for entry in events] == [(2, 2)]

    # Rows no marker was called for have no judgement either, and are not replies.
    with structlog.testing.capture_logs() as logs:
        _mark_with(
            {"1": _reply(None), "2": _reply("yes")},
            mark_scheme=_scheme(3, mcq=True),
            extracted_answers=_extracted({"1": "an answer", "2": "an answer", "3": " ", "4": "A"}),
        )
    events = [entry for entry in logs if entry["event"] == "marker_omitted_addresses_question"]
    assert [(entry["omitted"], entry["marked"]) for entry in events] == [(1, 2)]


def test_mcq_and_blank_paths_leave_addresses_question_none():
    # 1 marked, 2 blank, 3 dropped by extraction, 4 fails in the marker, 5 MCQ.
    scheme = _scheme(4, mcq=True)
    extracted = _extracted({"1": "an answer", "2": "  ", "4": "an answer", "5": "A"}, dropped=["3"])

    def fake(_self: object, question: Question, *_args: object, **_kwargs: object):
        if question.id == "4":
            raise RuntimeError("marker unavailable")
        return _reply("no")

    with patch.object(correction_ai.AICorrector, "mark_question", autospec=True, side_effect=fake):
        result = correct_paper(scheme, extracted, gemini_client=MagicMock())

    by_id = {q.question_id: q for q in result.questions}
    assert {qid: q.marker_source for qid, q in by_id.items()} == {
        "1": "ai",
        "2": "blank",
        "3": "dropped",
        "4": "missing",
        "5": "deterministic",
    }
    assert by_id["1"].addresses_question == "no"
    for qid in ("2", "3", "4", "5"):
        assert by_id[qid].addresses_question is None, qid

    unmarked = correct_paper(scheme, extracted, mcq_only=True)
    assert [q.addresses_question for q in unmarked.questions] == [None] * 5


def test_reply_json_reaches_the_corrected_question(tmp_path: Path):
    body = {
        "awarded_marks": 0,
        "confidence": 0.95,
        "matched_point_ids": [],
        "feedback": "This describes osmosis, which this entry does not ask about.",
        "addresses_question": "no",
    }
    result = correct_paper(
        _scheme(1), _extracted({"1": "an answer"}), gemini_client=_fake_client(tmp_path, [body])
    )
    assert result.questions[0].addresses_question == "no"


def test_escalated_reply_addresses_question_is_the_one_kept(tmp_path: Path):
    first = {
        "awarded_marks": 0,
        "confidence": 0.50,
        "matched_point_ids": [],
        "feedback": "first pass",
        "addresses_question": "no",
    }
    second = {
        "awarded_marks": 1,
        "confidence": 0.95,
        "matched_point_ids": ["p1"],
        "feedback": "escalated pass",
        "addresses_question": "yes",
    }
    client = _fake_client(
        tmp_path,
        [first, second],
        escalation_model="gemini-2.5-pro",
        escalation_confidence_threshold=0.80,
        thinking_level_for={"correction": "low", "correction_borderline": "low"},
        thinking_budget_for={},
    )
    result = correct_paper(
        _scheme(1), _extracted({"1": "an answer"}, binding=GATED), gemini_client=client
    )
    (cq,) = result.questions
    assert (cq.feedback, cq.awarded_marks) == ("escalated pass", 1)
    assert cq.addresses_question == "yes"
    assert _g8(result).passed


@pytest.mark.parametrize("re_mark_says", ["yes", None])
def test_ecf_re_mark_keeps_the_re_marks_addresses_question(re_mark_says: str | None):
    scheme = MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Chemistry",
                "subject_code": "0620",
                "paper_number": 4,
                "paper_variant": 1,
                "session_month": "May/June",
                "session_year": 2021,
                "paper_type": "theory_extended",
                "maximum_mark": 2,
                "scheme_format": "point_based",
            },
            "questions": [
                {
                    "id": "1",
                    "marks": 0,
                    "type": "calculation",
                    "parts": [
                        {
                            "id": "1a",
                            "marks": 1,
                            "type": "calculation",
                            "parent_id": "1",
                            "answer_points": [
                                {
                                    "id": "p1",
                                    "point": "moles = mass / Mr",
                                    "marks": 1,
                                    "math_mark_type": "M",
                                }
                            ],
                        },
                        {
                            "id": "1b",
                            "marks": 1,
                            "type": "calculation",
                            "parent_id": "1",
                            "answer_points": [
                                {
                                    "id": "p1",
                                    "point": "final mass",
                                    "marks": 1,
                                    "math_mark_type": "A",
                                    "condition": "ecf",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )

    def reply(verdict: str, addresses: str | None, feedback: str) -> AIMarkResponse:
        body: dict[str, Any] = {
            "awarded_marks": 0,
            "confidence": 0.95,
            "feedback": feedback,
            "point_verdicts": [{"point_id": "p1", "verdict": verdict, "evidence_span": "x"}],
        }
        if addresses is not None:
            body["addresses_question"] = addresses
        return AIMarkResponse.model_validate(body)

    replies = [
        reply("withheld", "yes", "prerequisite"),
        reply("withheld", "no", "first pass"),
        reply("awarded", re_mark_says, "re-mark"),
    ]
    with patch.object(correction_ai.AICorrector, "mark_question", side_effect=replies):
        result = correct_paper(
            scheme,
            _extracted({"1a": "wrong value x", "1b": "consistent working x"}),
            gemini_client=MagicMock(),
            options=MarkingOptions(equivalence_gate=True, ecf_substitution=True),
        )
    second = result.questions[1]
    assert second.point_verdicts[0].ecf_applied
    assert second.feedback == "re-mark"
    assert second.addresses_question == re_mark_says


# --- the check, applied to a marked paper -----------------------------------


def test_run_of_off_topic_answers_sets_paper_verdict_hold():
    result = _paper(["yes", "no", "no", "no", "yes", "yes"])
    check = _g8(result)
    assert (check.passed, check.scope) == (False, "paper")
    assert check.question_ids == ["2", "3", "4"]
    assert result.binding is not None
    assert result.binding.verdict == "hold"
    # A held paper is stopped whole; the per-question reason is for a lone answer.
    assert all(q.review_reason is None for q in result.questions)
    assert not result.needs_teacher_review


def test_questions_reach_the_check_in_mark_scheme_order():
    # Extraction lists the answers back to front; the run is in scheme order.
    flags = {"1": "yes", "2": "no", "3": "yes", "4": "no", "5": "no", "6": "no"}
    result = _mark_with(
        {qid: _reply(flag) for qid, flag in flags.items()},
        mark_scheme=_scheme(6),
        extracted_answers=_extracted(
            {qid: f"answer {qid}" for qid in reversed(flags)}, binding=GATED
        ),
    )
    assert [q.question_id for q in result.questions] == ["1", "2", "3", "4", "5", "6"]
    assert "3 in a row" in _g8(result).detail


def test_single_off_topic_answer_sends_only_that_question_to_review():
    result = _paper(["yes", "yes", "no", "yes", "unclear"])
    check = _g8(result)
    assert (check.passed, check.scope, check.question_ids) == (False, "question", ["3"])
    assert result.binding is not None
    assert result.binding.verdict == "pass"

    by_id = {q.question_id: q for q in result.questions}
    assert by_id["3"].needs_teacher_review
    assert by_id["3"].review_reason == OFF_TOPIC_REASON
    for qid in ("1", "2", "4", "5"):
        assert not by_id[qid].needs_teacher_review, qid
        assert by_id[qid].review_reason is None, qid
    # The paper-level flag and totals are computed from the flagged rows.
    assert result.needs_teacher_review
    assert (result.awarded_marks, result.maximum_marks) == (5, 5)


def test_off_topic_reason_is_joined_onto_an_existing_review_reason():
    result = _paper(["yes", "no"], confidence=0.5)
    low_confidence = "confidence 0.50 below review threshold 0.90"
    assert result.questions[0].review_reason == low_confidence
    assert result.questions[1].review_reason == f"{low_confidence} | {OFF_TOPIC_REASON}"


def test_marks_are_not_changed_by_addresses_question():
    def marks(flags: list[str | None]) -> list[tuple[Any, ...]]:
        result = _paper(flags, awarded=1, feedback="credited p1")
        return [
            (q.awarded_marks, q.confidence_score, q.matched_point_ids, q.feedback)
            for q in result.questions
        ] + [(result.awarded_marks, result.maximum_marks)]

    baseline = marks([None] * 5)
    assert baseline[-1] == (5, 5)
    assert marks(["yes"] * 5) == baseline
    assert marks(["unclear"] * 5) == baseline
    assert marks(["yes", "yes", "no", "yes", "yes"]) == baseline  # question scope
    assert marks(["no"] * 5) == baseline  # paper scope


def test_plain_mapping_answers_get_no_binding_report():
    # Typed answers never came off a scan, so there is no binding to doubt.
    ids = ["1", "2", "3", "4", "5"]

    def marked(flags: list[str | None]) -> CorrectionResult:
        return _mark_with(
            {qid: _reply(flag) for qid, flag in zip(ids, flags, strict=True)},
            mark_scheme=_scheme(5),
            extracted_answers={qid: f"answer {qid}" for qid in ids},
        )

    _assert_g8_never_applies(marked)


def test_extracted_answers_without_a_report_get_no_binding_report():
    # No report means the gate did not run on this extraction; G8 stays off with it.
    _assert_g8_never_applies(lambda flags: _paper(flags, binding=None))


def test_quiz_style_extracted_answers_are_never_held():
    _assert_g8_never_applies(lambda flags: _paper(flags, binding=None, source_scan="quiz"))
    held = _paper(["no"] * 5, binding=GATED, source_scan="quiz")
    assert held.binding is not None  # the report decides, not where the answers came from
    assert held.binding.verdict == "hold"


@pytest.mark.parametrize(("retried", "expected"), [(False, "retry"), (True, "hold")])
def test_extraction_report_is_kept_with_g8_appended_and_verdict_recomputed(
    retried: bool, expected: str
):
    extraction_checks = [
        BindingCheck(id="G1", passed=True, scope="paper", detail="All ids are known."),
        BindingCheck(
            id="G6", passed=False, scope="question", question_ids=["2"], detail="One shape."
        ),
    ]
    report = BindingReport(
        binder="position",
        checks=extraction_checks,
        verdict="pass",
        retried=retried,
        model="gemini-test",
    )
    ids = ["1", "2", "3", "4"]
    result = _mark_with(
        {qid: _reply("no") for qid in ids},
        mark_scheme=_scheme(4),
        extracted_answers=_extracted({qid: f"answer {qid}" for qid in ids}, binding=report),
    )
    assert result.binding is not None
    assert result.binding.checks[:2] == extraction_checks
    assert [c.id for c in result.binding.checks] == ["G1", "G6", "G8"]
    assert (result.binding.binder, result.binding.retried, result.binding.model) == (
        "position",
        retried,
        "gemini-test",
    )
    assert result.binding.verdict == expected


@pytest.mark.parametrize(
    ("incoming", "retried", "flags", "expected"),
    [
        # A verdict with no failing paper-scope check behind it still stands.
        ("hold", True, ["yes", "yes", "yes"], "hold"),
        ("hold", False, ["yes", "yes", "yes"], "hold"),
        ("retry", False, ["yes", "yes", "yes"], "retry"),
        ("retry", True, ["yes", "yes", "yes"], "retry"),
        # G8 can raise it: a paper-scope failure after the retry is spent.
        ("retry", True, ["no", "no", "no"], "hold"),
        ("retry", False, ["no", "no", "no"], "retry"),
        ("hold", False, ["no", "no", "no"], "hold"),
        ("pass", False, ["no", "no", "no"], "retry"),
        ("pass", True, ["yes", "yes", "yes"], "pass"),
    ],
)
def test_g8_never_downgrades_an_incoming_verdict(
    incoming: str, retried: bool, flags: list[str], expected: str
):
    report = GATED.model_copy(update={"verdict": incoming, "retried": retried})
    result = _paper(flags, binding=report)
    assert result.binding is not None
    assert [c.id for c in result.binding.checks] == ["G1", "G8"]
    assert result.binding.verdict == expected


def test_a_hold_from_extraction_survives_a_clean_g8():
    report = BindingReport(
        binder="label",
        checks=[BindingCheck(id="G7", passed=False, scope="paper", detail="Shifted by one.")],
        verdict="hold",
        retried=True,
    )
    result = _mark_with(
        {"1": _reply("yes")},
        mark_scheme=_scheme(1),
        extracted_answers=_extracted({"1": "an answer"}, binding=report),
    )
    assert result.binding is not None
    assert _g8(result).passed
    assert result.binding.verdict == "hold"
