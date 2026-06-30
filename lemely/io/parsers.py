from __future__ import annotations

from pathlib import Path

from lemely.core.loose_schemas import MarkScheme
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.mark_scheme_parsing import (
    PARSER_SYSTEM_PROMPT,
    PARSER_USER_PROMPT,
    VERSION,
)


class GeminiMarkSchemeParser:
    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def __call__(self, pdf_path: Path) -> MarkScheme:
        return self._client.generate_structured(
            system_prompt=PARSER_SYSTEM_PROMPT,
            user_prompt=PARSER_USER_PROMPT,
            file_paths=[pdf_path],
            response_schema=MarkScheme,
            prompt_version=VERSION,
            task_tag="mark_scheme",
        )
