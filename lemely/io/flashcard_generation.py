"""AI flashcard-deck generator using Gemini (P4.6 chunk B).

Mirrors :class:`lemely.io.question_generation.QuestionGenerator`'s structure
closely, on purpose: same client construction (a plain
:class:`~lemely.io.gemini.GeminiClient` is injected, never constructed
here), same cost-ledger accounting (``GeminiClient.generate_structured``
handles caching, retries, and the persistent USD ledger — nothing in this
module touches money or tokens directly), and the same prompt/response
idiom (a versioned prompt pair in :mod:`lemely.io.prompts`, a structured
Pydantic response schema, a ``task_tag`` for per-task model/thinking-budget
overrides).

Unlike ``QuestionGenerator`` (one question per weak area, up to a count),
this module generates **one deck for one topic** — see
:mod:`lemely.core.flashcards`'s module docstring for why a deck is singular
on topic. The caller (:class:`~lemely.db.flashcard_repo.FlashcardService`)
resolves *which* topic (caller-picked, or the caller's own top weak topic)
before calling :meth:`FlashcardGenerator.generate`; this module never reads
a ``WeaknessReport`` or touches the database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anthropic
import httpx

from lemely.core.flashcards import GeneratedFlashcardDeck
from lemely.io.prompts.flashcard_generation import (
    VERSION,
    build_flashcard_gen_system_prompt,
    build_flashcard_gen_user_prompt,
)

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient

#: What a request that passed its HTTP timeout raises, whichever SDK made it.
_TIMEOUT_ERRORS = (TimeoutError, httpx.TimeoutException, anthropic.APITimeoutError)
#: The HTTP status the Gemini API answers with when its own deadline passes.
_GATEWAY_TIMEOUT = 504


def _is_timeout(exc: BaseException | None) -> bool:
    """Whether ``exc`` or anything it was raised from is an SDK timeout."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, _TIMEOUT_ERRORS) or getattr(exc, "code", None) == _GATEWAY_TIMEOUT:
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


class FlashcardGenerator:
    """Generate a targeted flashcard deck for one syllabus topic via Gemini."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def generate(
        self,
        *,
        subject_code: str,
        topic: str,
        count: int,
        timeout_seconds: float | None = None,
    ) -> GeneratedFlashcardDeck:
        """Generate up to ``count`` flashcards for ``topic``.

        Args:
            subject_code: CAIE subject code (e.g. ``"0625"``).
            topic: The P4.2 ``"<code> <name>"`` syllabus topic to write cards
                for — already resolved by the caller (never derived here).
            count: The upper bound on cards to generate.
            timeout_seconds: A real HTTP timeout on the model request itself, so a hung
                call ends rather than running on after the caller gave up.

        Returns:
            A :class:`~lemely.core.flashcards.GeneratedFlashcardDeck` with
            *at most* ``count`` cards. Gemini may return fewer; this method
            never pads the result back up to ``count`` (P4.6 honesty rule —
            the caller must report the true generated count, not the
            requested one).

        Raises:
            TimeoutError: The request passed ``timeout_seconds``.
        """
        extra_cache_key = f"{subject_code}:{topic}:{count}"
        try:
            return self._client.generate_structured(
                system_prompt=build_flashcard_gen_system_prompt(subject_code),
                user_prompt=build_flashcard_gen_user_prompt(topic, count=count),
                response_schema=GeneratedFlashcardDeck,
                prompt_version=VERSION,
                task_tag="flashcard_generation",
                extra_cache_key=extra_cache_key,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            if _is_timeout(exc):
                raise TimeoutError from exc
            raise


__all__ = ["FlashcardGenerator"]
