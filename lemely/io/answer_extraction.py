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
        answers = raw.answers
        for a in answers:
            bus.publish(
                EventType.EXTRACTION_PROGRESS,
                question_id=a.question_id,
                confidence=a.confidence,
                has_working=a.working_out is not None,
            )
        manifest_ids = [
            q.id for q in mark_scheme.all_questions_flat()
            if q.marks > 0 and not q.parts
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
