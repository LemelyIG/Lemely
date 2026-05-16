from __future__ import annotations

import json
import re
from typing import Any, Mapping

from models import MarkScheme, QuestionType

from .schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
)

_ANSWER_RE = re.compile(r"^\s*(?P<question>[A-Za-z0-9_().-]+)\s*[:.)-]?\s*(?P<answer>\S+)\s*$")


def parse_answer_input(answer_input: str | Mapping[str, Any]) -> dict[str, str]:
    if isinstance(answer_input, Mapping):
        return {
            str(question_id): str(answer).strip().upper()
            for question_id, answer in answer_input.items()
            if str(answer).strip()
        }

    text = answer_input.strip()
    if not text:
        return {}

    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("JSON answer input must be an object of question IDs to answers.")
        return parse_answer_input(parsed)

    answers: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _ANSWER_RE.match(line)
        if not match:
            raise ValueError(f"Could not parse answer line: {line}")
        answers[match.group("question")] = match.group("answer").upper()
    return answers


def _exam_metadata(mark_scheme: MarkScheme) -> ExamMetadata:
    metadata = mark_scheme.metadata
    return ExamMetadata(
        subject_code=metadata.subject_code,
        paper_number=metadata.paper_number,
        paper_variant=metadata.paper_variant,
        session_month=metadata.session_month.value,
        session_year=metadata.session_year,
        source_document=metadata.source_document,
    )


def _load_mark_scheme(mark_scheme: MarkScheme | Mapping[str, Any] | str) -> MarkScheme:
    if isinstance(mark_scheme, MarkScheme):
        return mark_scheme
    if isinstance(mark_scheme, str):
        return MarkScheme.model_validate_json(mark_scheme)
    return MarkScheme.model_validate(mark_scheme)


def correct_mcq_answers(
    mark_scheme: MarkScheme | Mapping[str, Any] | str,
    answer_input: str | Mapping[str, Any],
) -> CorrectionResult:
    scheme = _load_mark_scheme(mark_scheme)
    answers = parse_answer_input(answer_input)
    corrected: list[CorrectedQuestion] = []

    for question in scheme.all_questions_flat():
        if question.type != QuestionType.MCQ:
            continue

        expected = question.mcq_answer.value if question.mcq_answer else None
        student_answer = answers.get(question.id)

        if student_answer is None:
            corrected.append(
                CorrectedQuestion(
                    question_id=question.id,
                    awarded_marks=0,
                    maximum_marks=question.marks,
                    confidence=ConfidenceBand.LOW,
                    confidence_score=0.0,
                    needs_teacher_review=True,
                    student_answer=None,
                    expected_answer=expected,
                    topic=question.topic_hint,
                    review_reason="missing answer",
                )
            )
            continue

        if student_answer not in {"A", "B", "C", "D"}:
            corrected.append(
                CorrectedQuestion(
                    question_id=question.id,
                    awarded_marks=0,
                    maximum_marks=question.marks,
                    confidence=ConfidenceBand.LOW,
                    confidence_score=0.0,
                    needs_teacher_review=True,
                    student_answer=student_answer,
                    expected_answer=expected,
                    topic=question.topic_hint,
                    review_reason="invalid MCQ answer",
                )
            )
            continue

        is_correct = student_answer == expected
        corrected.append(
            CorrectedQuestion(
                question_id=question.id,
                awarded_marks=question.marks if is_correct else 0,
                maximum_marks=question.marks,
                confidence=ConfidenceBand.HIGH,
                confidence_score=1.0,
                needs_teacher_review=False,
                student_answer=student_answer,
                expected_answer=expected,
                topic=question.topic_hint,
            )
        )

    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
