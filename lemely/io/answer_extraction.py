"""GeminiAnswerExtractor — extracts student responses from scanned exam papers (any paper type)."""

from __future__ import annotations

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


class _ExtractorOutput(BaseModel):
    """Inner schema we ask Gemini to return — just the answers list."""

    answers: list[ExtractedAnswer]


def _build_paper_id(mark_scheme: MarkScheme) -> str:
    m = mark_scheme.metadata
    session = m.session_month.value.replace("/", "")
    year = str(m.session_year) if m.session_year is not None else "specimen"
    return f"{m.subject_code}_{session}_{year}_p{m.paper_number}{m.paper_variant}"


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
        )
        return ExtractedAnswers(
            paper_id=_build_paper_id(mark_scheme),
            source_scan=str(scan_path),
            answers=raw.answers,
        )
