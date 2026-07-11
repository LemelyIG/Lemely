from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from lemely.core.loose_schemas import MarkScheme
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.mark_scheme_parsing import (
    PARSER_SYSTEM_PROMPT,
    PARSER_USER_PROMPT,
    VERSION,
)
from lemely.runtime.errors import ParseError

ParserCallable = Callable[[Path], MarkScheme]


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


class ChainedMarkSchemeParser:
    """Try the deterministic parser first; fall back to Gemini on ``ParseError``.

    Lets the cheap, fast, offline path handle the majority of papers while
    complex question types (levels-based, indicative content) are transparently
    delegated to the AI parser.
    """

    def __init__(self, primary: ParserCallable, fallback: ParserCallable) -> None:
        self._primary = primary
        self._fallback = fallback

    def __call__(self, pdf_path: Path) -> MarkScheme:
        try:
            return self._primary(pdf_path)
        except ParseError:
            return self._fallback(pdf_path)
