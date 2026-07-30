"""GeminiAnswerExtractor — extracts student responses from scanned exam papers (any paper type)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.answer_extraction import (
    EXTRACTOR_SYSTEM_PROMPT,
    VERSION,
    build_extractor_user_prompt,
    build_question_manifest_hash_key,
)
from lemely.runtime.events import EventType, bus


class _ExtractorOutput(BaseModel):
    """Inner schema we ask Gemini to return — just the answers list."""

    answers: list[ExtractedAnswer]


def _build_paper_id(mark_scheme: MarkScheme) -> str:
    m = mark_scheme.metadata
    session = m.session_month.value.replace("/", "")
    year = str(m.session_year) if m.session_year is not None else "specimen"
    return f"{m.subject_code}_{session}_{year}_p{m.paper_number}{m.paper_variant}"


def _canonical_id(q_id: str) -> str:
    """Strip whitespace, brackets, dots; lowercase — for fuzzy ID matching."""
    return re.sub(r"[\s()\[\].]", "", q_id).lower()


def normalize_extracted_answers(
    extracted: ExtractedAnswers,
    manifest_ids: list[str],
) -> ExtractedAnswers:
    """Re-map extracted answer IDs to canonical manifest IDs.

    First pass: fuzzy match by canonical form.
    Second pass: positional fallback for any remaining unmatched answers.
    """
    import structlog as _sl

    _norm_log = _sl.get_logger().bind(component="id_normalization")

    canonical_map: dict[str, str] = {_canonical_id(mid): mid for mid in manifest_ids}
    claimed: set[str] = set()
    new_answers: list[ExtractedAnswer] = []
    unmatched_positions: list[int] = []

    for ans in extracted.answers:
        canon = _canonical_id(ans.question_id)
        if canon in canonical_map:
            target = canonical_map[canon]
            new_answers.append(ans.model_copy(update={"question_id": target}))
            claimed.add(target)
        else:
            unmatched_positions.append(len(new_answers))
            new_answers.append(ans)

    unclaimed = [mid for mid in manifest_ids if mid not in claimed]
    for seq, pos in enumerate(unmatched_positions):
        if seq < len(unclaimed):
            target = unclaimed[seq]
            _norm_log.warning(
                "id_positional_fallback",
                extracted_id=new_answers[pos].question_id,
                mapped_to=target,
            )
            new_answers[pos] = new_answers[pos].model_copy(update={"question_id": target})

    return extracted.model_copy(update={"answers": new_answers})


# Gemini's self-reported confidence is often miscalibrated — it tends to be
# overconfident on ambiguous handwriting and underconfident on clean MCQ answers.
# This heuristic layer adjusts confidence using structural signals from the
# extraction result itself, with zero extra API calls.
def _calibrate_confidence(
    answer: ExtractedAnswer,
    question_type_hint: str | None = None,
) -> float:
    """Adjust raw Gemini confidence using structural signals from the extraction result."""
    conf = answer.confidence
    is_mcq_hint = question_type_hint == "mcq"

    # Detect MCQ from answer content: single letter A/B/C/D
    answer_stripped = answer.answer.strip()
    looks_like_mcq_answer = answer_stripped.upper() in {"A", "B", "C", "D"}

    if is_mcq_hint or looks_like_mcq_answer:
        conf = min(1.0, conf + 0.1) if looks_like_mcq_answer else min(conf, 0.2)
    else:
        # Non-MCQ: check answer completeness
        if len(answer_stripped) < 2:
            conf = min(conf, 0.3)

        # Working out present → slight boost (extractor found method, more reliable)
        if answer.working_out:
            conf = min(1.0, conf + 0.05)

    # Source region present → slight boost (extractor located answer spatially)
    if answer.source_region:
        conf = min(1.0, conf + 0.03)

    return conf


class GeminiAnswerExtractor:
    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def __call__(self, scan_path: Path, mark_scheme: MarkScheme) -> ExtractedAnswers:
        manifest_key = build_question_manifest_hash_key(mark_scheme)
        raw = self._client.generate_structured(
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=build_extractor_user_prompt(mark_scheme),
            file_paths=[scan_path],
            response_schema=_ExtractorOutput,
            prompt_version=VERSION,
            extra_cache_key=manifest_key,
            task_tag="extraction",
        )
        # Build a type-hint map from mark scheme for calibration
        type_hint_map: dict[str, str] = {}
        for q in mark_scheme.all_questions_flat():
            if not q.parts and q.marks > 0:
                type_hint_map[q.id] = q.type.value

        answers = raw.answers
        calibrated: list[ExtractedAnswer] = []
        for a in answers:
            hint = type_hint_map.get(a.question_id)
            new_conf = _calibrate_confidence(a, question_type_hint=hint)
            calibrated.append(a.model_copy(update={"confidence": new_conf}))
        answers = calibrated
        for a in answers:
            bus.publish(
                EventType.EXTRACTION_PROGRESS,
                question_id=a.question_id,
                confidence=a.confidence,
                has_working=a.working_out is not None,
            )
        manifest_ids = [
            q.id for q in mark_scheme.all_questions_flat() if q.marks > 0 and not q.parts
        ]
        normalized_result = normalize_extracted_answers(
            ExtractedAnswers(
                paper_id=_build_paper_id(mark_scheme),
                source_scan=str(scan_path),
                answers=answers,
            ),
            manifest_ids,
        )
        return normalized_result
