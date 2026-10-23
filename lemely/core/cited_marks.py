"""Is every awarded mark backed by a quote from its mark scheme? (spec §4 B2 fallback)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lemely.core.loose_schemas import Question
    from lemely.core.schemas import AIMarkResponse, CorrectedQuestion

UNCITED_MARK = "uncited_mark"
_MIN_QUOTE_CHARS = 3


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def scheme_text(question: Question) -> str:
    """Every string in the question's mark-scheme subtree, one per line."""
    return "\n".join(_strings(question.model_dump(mode="json", exclude_none=True)))


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def uncited(question: Question, mark: AIMarkResponse) -> bool:
    """True when awarded marks lack valid quotes.

    A mark with ``awarded_marks > 0`` is uncited when it has fewer valid quotes than
    ``max(1, len(set(matched_point_ids)))``, or any quote is invalid. A quote is valid
    when, case-folded and whitespace-collapsed, it is at least 3 characters and a
    substring of the question's mark-scheme text.
    """
    if mark.awarded_marks <= 0:
        return False
    quotes = [_norm(q) for q in getattr(mark, "evidence_quotes", None) or []]
    text = _norm(scheme_text(question))
    valid = [q for q in quotes if len(q) >= _MIN_QUOTE_CHARS and q in text]
    needed = max(1, len(set(mark.matched_point_ids)))
    return len(valid) < needed or len(valid) != len(quotes)


def flag_uncited(cq: CorrectedQuestion) -> CorrectedQuestion:
    """``cq`` sent to a teacher, with ``uncited_mark`` added to its reason."""
    reason = UNCITED_MARK if not cq.review_reason else f"{cq.review_reason} | {UNCITED_MARK}"
    return cq.model_copy(update={"needs_teacher_review": True, "review_reason": reason})
