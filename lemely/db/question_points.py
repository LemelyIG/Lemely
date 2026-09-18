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

if TYPE_CHECKING:
    from collections.abc import Sequence

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
        ``is_alternative``, ``is_optional``, ``rationale``, ``group_key`` and
        ``group_max_marks``. Empty when there is no scheme, no matching
        question, or the question has no answer points.
    """
    if mark_scheme is None:
        return []

    question = mark_scheme.get_question_by_id(cq.question_id)
    if question is None or not question.answer_points:
        return []

    matched = set(cq.matched_point_ids)
    notes = cq.point_notes or {}

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
        # When both are 0 this still yields 0, collapsing every cap to 0 —
        # harmless while group_max_marks is advisory-only, but load-bearing
        # once a future task enforces it against a student's grant.
        total=question.marks or cq.maximum_marks,
        select_count=question.select_count,
    )
    return [
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
            "rationale": notes.get(point.id),
            "group_key": group_key,
            "group_max_marks": group_max_marks,
        }
        for ordinal, (point, (group_key, group_max_marks)) in enumerate(
            zip(kept, groups, strict=True)
        )
    ]


def _group_points(
    points: Sequence[AnswerPoint], *, total: int, select_count: int | None
) -> list[tuple[str | None, int | None]]:
    """``(group_key, group_max_marks)`` per point, from the scheme's flags.

    Grouping is by run in scheme order — all the flags can express:

    * an ``is_alternative`` point joins the group of the point before it,
      forming a new either/or group with that point when it had none, or
      standing alone when there is no previous point;
    * an ``is_optional`` point joins the pool the previous point is in, else
      starts a new pool;
    * anything else is independent.

    A one-member group is not a group (``(None, None)``). Keys are ``alt:n``
    / ``pool:n``, numbered per kind in scheme order after that pruning, so
    they are gapless and stable for a given scheme.

    ``group_max_marks`` is the most the group can contribute, never above
    ``total``: an either/or group is worth its best member; a pool with a
    ``select_count`` is worth its N largest tariffs, further capped by
    whatever ``total`` has left after every independent point and every
    either/or group (the same leftover a select_count-less pool is worth in
    full) — a pool can never claim more room than the question actually has
    once its siblings are paid for; a pool without a ``select_count`` is
    worth exactly that leftover — the tightest cap the scheme supports when N
    is unstated.
    """
    groups: list[tuple[str, list[int]]] = []
    member_of: dict[int, int] = {}

    def start(kind: str, *indexes: int) -> None:
        groups.append((kind, list(indexes)))
        for index in indexes:
            member_of[index] = len(groups) - 1

    def join(group: int, index: int) -> None:
        groups[group][1].append(index)
        member_of[index] = group

    for index, point in enumerate(points):
        previous = index - 1
        if point.is_alternative:
            if previous in member_of:
                join(member_of[previous], index)
            elif previous >= 0:
                start("alt", previous, index)
            else:
                start("alt", index)
        elif point.is_optional:
            if previous in member_of and groups[member_of[previous]][0] == "pool":
                join(member_of[previous], index)
            else:
                start("pool", index)

    real = [(kind, members) for kind, members in groups if len(members) > 1]
    grouped = {index for _kind, members in real for index in members}

    def alt_cap(members: list[int]) -> int:
        return min(total, max(points[index].marks for index in members))

    independent_total = sum(p.marks for index, p in enumerate(points) if index not in grouped)
    alt_cap_total = sum(alt_cap(members) for kind, members in real if kind == "alt")
    leftover = max(0, total - independent_total - alt_cap_total)

    result: list[tuple[str | None, int | None]] = [(None, None)] * len(points)
    counters = {"alt": 0, "pool": 0}
    for kind, members in real:
        counters[kind] += 1
        if kind == "alt":
            group_max = alt_cap(members)
        elif select_count is not None:
            tariffs = sorted((points[index].marks for index in members), reverse=True)
            group_max = max(
                0,
                min(total - independent_total - alt_cap_total, sum(tariffs[:select_count])),
            )
        else:
            group_max = leftover
        key = f"{kind}:{counters[kind]}"
        for index in members:
            result[index] = (key, group_max)
    return result
