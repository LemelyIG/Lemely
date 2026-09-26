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

``group_key`` / ``group_max_marks`` record the scheme's non-additive structure
— either/or alternatives and "any N from" pools — as data, at the one moment
the ``Question`` is in hand. ``AnswerPoint.is_alternative`` means only "an
alternative to the *previous* point", so a group exists in scheme order and
nowhere else; :func:`lemely.io.correction_ai._check_coherence` refuses,
rightly, to rebuild it at read time. Recording it here is what lets the
self-review write path (:mod:`lemely.db.self_review_repo`) cap a student's
granted marks at what the group is worth, and lets the panel render an
either/or group as one unit (self-review spec, D6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.point_groups import group_points as _group_points
from lemely.core.schemas import dedupe_point_verdicts

if TYPE_CHECKING:
    from lemely.core.loose_schemas import AnswerPoint, MarkScheme
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
        ``is_alternative``, ``is_optional``, ``rationale``, ``group_key``,
        ``group_max_marks``, ``verdict``, ``evidence_span`` and
        ``ecf_applied``. Empty when there is no scheme, no matching question,
        or the question has no answer points.
    """
    if mark_scheme is None:
        return []

    question = mark_scheme.get_question_by_id(cq.question_id)
    if question is None or not question.answer_points:
        return []

    matched = set(cq.matched_point_ids)
    notes = cq.point_notes or {}
    # First occurrence of a repeated point_id wins -- the SAME rule
    # ``lemely.io.correction_ai._awarded_from_verdicts`` applies to the same
    # list, via the one shared helper, so the two can no longer disagree
    # about a repeat (they used to: that function kept every awarded entry,
    # this dict comprehension kept the LAST one, so an awarded-then-withheld
    # pair for one id used to award marks for a point this function then
    # persisted as ``verdict='withheld'``). Dropped duplicates are not logged
    # here -- this module stays pure, no session, no I/O (module docstring)
    # -- ``lemely.db.attempt_repo`` logs on this function's behalf.
    kept_verdicts, _dropped_verdicts = dedupe_point_verdicts(cq.point_verdicts)
    verdicts = {pv.point_id: pv for pv in kept_verdicts}

    kept: list[AnswerPoint] = []
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
        kept.append(point)

    groups = _group_points(
        kept,
        # ``Question.marks == 0`` is the scheme's "container" convention; the
        # marker's maximum is the next-best statement of the question's worth.
        # When both are 0 this still yields 0, collapsing every cap to 0. That
        # is no longer advisory: ``_settle_groups`` enforces these caps against
        # a student's self-mark, so a 0/0 container silently makes every grant
        # on that question worth nothing. Under-crediting rather than
        # over-crediting, but it is a real answer a student sees, not a
        # bookkeeping detail.
        total=question.marks or cq.maximum_marks,
        select_count=question.select_count,
    )
    rows: list[dict[str, object]] = []
    for ordinal, (point, (group_key, group_max_marks)) in enumerate(zip(kept, groups, strict=True)):
        # US-045: when I6's verdict path scored this point, its `PointVerdict`
        # is the richer, code-computed record — `verdict` distinguishes
        # `withheld` from `unverifiable` where `awarded` alone collapses both
        # to False, and its `note` wins over `point_notes[point.id]` even when
        # empty, rather than falling back to it (PLAN-point-verdicts.md,
        # US-045 precedence rule). A point with no verdict entry (the legacy
        # path, or a verdict-path question this point simply wasn't scored
        # under) has no such record: `verdict` stays `None`, `evidence_span`/
        # `ecf_applied` stay at their column defaults, and `rationale` falls
        # back to `point_notes`.
        pv = verdicts.get(point.id)
        rationale = pv.note or None if pv is not None else notes.get(point.id)
        rows.append(
            {
                "mark_point_id": point.id,
                "ordinal": ordinal,
                "mark_type": point.math_mark_type.value if point.math_mark_type else None,
                "tariff": point.marks,
                "tariff_defaulted": point.marks_defaulted,
                "point_text": point.point,
                "awarded": point.id in matched,
                "is_alternative": point.is_alternative,
                "is_optional": point.is_optional,
                "rationale": rationale,
                "group_key": group_key,
                "group_max_marks": group_max_marks,
                "verdict": pv.verdict if pv is not None else None,
                "evidence_span": pv.evidence_span if pv is not None else "",
                "ecf_applied": pv.ecf_applied if pv is not None else False,
            }
        )
    return rows
