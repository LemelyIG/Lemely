"""Derive a per-mark-point ledger from a marked question and its mark scheme.

Pure: no session, no I/O. Returns plain dicts, which
:mod:`lemely.db.attempt_repo` turns into ``QuestionResultPoint`` rows — keeping
this module free of the model layer and its tests free of a database.

The rule that matters: one row per point **in the mark scheme**, not per id in
``matched_point_ids``. A ledger of only the matched points has nothing to say
about the marks a student did not get, which is the entire reason to have one
(spec 2026-09-17, "Write path").

Nothing here is invented. ``tariff``, ``point_text`` and ``mark_type`` are
copied from the scheme; ``rationale`` is copied from the marker's
``point_notes`` when present and left ``None`` otherwise (D2). An id the marker
claimed but the scheme does not define produces no row at all — never a row
with a null tariff pretending to be a mark point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import CorrectedQuestion


def derive_point_rows(
    cq: CorrectedQuestion,
    mark_scheme: MarkScheme | None,
) -> list[dict[str, object]]:
    """One dict per mark point in ``cq``'s question, in scheme order.

    Args:
        cq: The marked question. ``matched_point_ids`` decides ``awarded``;
            ``point_notes`` supplies ``rationale`` where the marker wrote one.
        mark_scheme: The parsed scheme this question was marked against, or
            ``None`` when the caller has none (a quiz).

    Returns:
        A list of dicts carrying ``mark_point_id``, ``ordinal``, ``mark_type``,
        ``tariff``, ``tariff_defaulted``, ``point_text``, ``awarded``,
        ``is_alternative``, ``is_optional`` and ``rationale``. Empty when
        there is no scheme, no matching question, or the question has no
        answer points.
    """
    if mark_scheme is None:
        return []

    question = mark_scheme.get_question_by_id(cq.question_id)
    if question is None or not question.answer_points:
        return []

    matched = set(cq.matched_point_ids)
    notes = cq.point_notes or {}

    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for point in question.answer_points:
        # A malformed scheme carrying two points with the same id must still
        # degrade to a partial-but-writable ledger, never to a lost paper: the
        # unique constraint on (question_result_id, mark_point_id) would abort
        # the whole attempt at commit otherwise. First occurrence wins — it is
        # the one the scheme's own reading order and this row's ``ordinal``
        # refer to.
        if point.id in seen_ids:
            continue
        seen_ids.add(point.id)
        rows.append(
            {
                "mark_point_id": point.id,
                "ordinal": len(rows),
                "mark_type": point.math_mark_type.value if point.math_mark_type else None,
                "tariff": point.marks,
                "tariff_defaulted": point.marks_defaulted,
                "point_text": point.point,
                "awarded": point.id in matched,
                "is_alternative": point.is_alternative,
                "is_optional": point.is_optional,
                "rationale": notes.get(point.id),
            }
        )
    return rows
