"""Is every awarded mark backed by a quote from its mark scheme? (spec §4 B2 fallback)."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from lemely.core.loose_schemas import Question
    from lemely.core.schemas import AIMarkResponse, CorrectedQuestion

UNCITED_MARK = "uncited_mark"
_MIN_QUOTE_CHARS = 3

# The prompt shows the marker the question as JSON, so a model quoting what it saw may
# copy the JSON escapes (a newline as backslash-n). Both spellings are accepted.
_JSON_ESCAPE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})')
_JSON_SIMPLE = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
# Minus, hyphen and dash variants map to "-"; curly quotes to straight ones (by code point).
_PUNCTUATION = {
    **dict.fromkeys((0x2212, 0x2010, 0x2011, 0x2012, 0x2013, 0x2014), "-"),
    **dict.fromkeys((0x2018, 0x2019), "'"),
    **dict.fromkeys((0x201C, 0x201D), '"'),
}


# Labels, not mark-scheme wording: an id, the question type or a mark-code name is
# not something a mark rests on, so quoting one never cites a mark.
_LABEL_KEYS = frozenset(
    {
        "id",
        "parent_id",
        "type",
        "scheme_format",
        "assessment_objectives",
        "topic_hint",
        "question_command",
        "math_mark_type",
    }
)


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _LABEL_KEYS:
                yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _dump(model: object) -> object:
    # The same fields the prompt renders: ``exclude_none`` and ``exclude_defaults``.
    return model.model_dump(mode="json", exclude_none=True, exclude_defaults=True)  # type: ignore[attr-defined]


def scheme_text(question: Question) -> str:
    """Every quotable string in the question's mark-scheme subtree, one per line.

    Labels (ids, the question type, the mark-code name) are left out.
    """
    return "\n".join(_strings(_dump(question)))


def _unescape(match: re.Match[str]) -> str:
    code = match.group(1)
    if code.startswith("u"):
        return chr(int(code[1:], 16))
    return _JSON_SIMPLE.get(code, code)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION)
    return " ".join(text.casefold().split())


def _norm(text: str) -> str:
    """``text`` as compared: decoded JSON escapes, NFKC, ASCII dashes and quotes, folded."""
    return _fold(_JSON_ESCAPE.sub(_unescape, text))


def _variants(text: str) -> set[str]:
    r"""The quote as written and with JSON escapes decoded (a LaTeX ``\\neq`` is not a newline)."""
    return {_fold(text), _norm(text)}


def _points(question: Question) -> dict[str, list[str]]:
    """Each answer point's strings by id, over the question and its parts."""
    found: dict[str, list[str]] = {}
    stack = [question]
    while stack:
        current = stack.pop()
        for point in current.answer_points:
            found[point.id] = list(_strings(_dump(point)))
        stack.extend(current.parts)
    return found


def _whole_values(question: Question, ids: Iterable[str] | None) -> set[str]:
    """Normalised ``point`` and ``accept`` values; a quote under 3 characters must be one."""
    values: set[str] = set()
    stack = [question]
    while stack:
        current = stack.pop()
        for point in current.answer_points:
            if ids is None or point.id in ids:
                values.update(_fold(s) for s in (point.point, *point.accept))
        stack.extend(current.parts)
    return values


def _valid(quote: str, text: str, whole: set[str]) -> bool:
    return any(
        v and ((len(v) >= _MIN_QUOTE_CHARS and v in text) or v in whole) for v in _variants(quote)
    )


def _distinct_assignment(fits: list[list[int]]) -> bool:
    """True when each target can take its own quote (``fits[t]`` = quote indices)."""
    owner: dict[int, int] = {}

    def place(target: int, seen: set[int]) -> bool:
        for quote in fits[target]:
            if quote in seen:
                continue
            seen.add(quote)
            if quote not in owner or place(owner[quote], seen):
                owner[quote] = target
                return True
        return False

    return all(place(t, set()) for t in range(len(fits)))


def uncited(question: Question, mark: AIMarkResponse) -> bool:
    """True when awarded marks lack valid quotes.

    A mark with ``awarded_marks > 0`` is uncited when any quote is not in the question's
    mark-scheme text, or when its matched points cannot each take a distinct quote from
    their own ``point``/``accept`` text. A mark naming no known point needs one quote
    from anywhere in the subtree. Quotes are compared after decoding JSON escapes, NFKC,
    mapping dashes and curly quotes to ASCII, collapsing whitespace and case-folding; one
    shorter than 3 characters must equal a whole ``point`` or ``accept`` value.
    """
    if mark.awarded_marks <= 0:
        return False
    quotes = list(getattr(mark, "evidence_quotes", None) or [])
    if not quotes:
        return True
    subtree = _fold(scheme_text(question))
    whole = _whole_values(question, None)
    if not all(_valid(q, subtree, whole) for q in quotes):
        return True
    by_id = _points(question)
    texts: list[tuple[str, set[str]]] = [
        (_fold("\n".join(by_id[i])), _whole_values(question, {i}))
        for i in sorted(set(mark.matched_point_ids))
        if i in by_id
    ]
    unknown = len(set(mark.matched_point_ids)) - len(texts)
    texts.extend([(subtree, whole)] * max(unknown, 0 if texts else 1))
    fits = [[n for n, q in enumerate(quotes) if _valid(q, text, w)] for text, w in texts]
    return not _distinct_assignment(fits)


def flag_uncited(cq: CorrectedQuestion) -> CorrectedQuestion:
    """``cq`` sent to a teacher, with ``uncited_mark`` added to its reason.

    The join duplicates ``lemely.io.correction_ai._join_reason``: ``core`` cannot import
    ``io``, so the two spellings of "a | b" are kept in step by hand.
    """
    reason = UNCITED_MARK if not cq.review_reason else f"{cq.review_reason} | {UNCITED_MARK}"
    return cq.model_copy(update={"needs_teacher_review": True, "review_reason": reason})
