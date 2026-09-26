"""Non-additive mark-point structure, derived from a scheme's flags.

``AnswerPoint.is_alternative`` means only "an alternative to the *previous*
point", and ``is_optional`` means "a member of an 'any N from' pool", so a
group exists in scheme order and nowhere else. This module turns those flags
into ``(group_key, group_max_marks)`` per point, at the one moment a
``Question`` is in hand. It is pure: no session, no I/O, ``core`` only.

Two consumers read it: :func:`lemely.db.question_points.derive_point_rows`
(persisting ``group_key``/``group_max_marks`` on every ledger row) and
:func:`lemely.io.correction_ai._awarded_from_verdicts` (capping a marker's
verdict total at what each group is worth), so the two can never disagree
about what an either/or pair or a pool may contribute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.core.loose_schemas import AnswerPoint


def group_points(
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
    either/or group — a pool can never claim more room than the question
    actually has once its siblings are paid for; a pool without a
    ``select_count`` is worth that leftover, the tightest cap the scheme
    supports when N is unstated. Several pools in one question **share** that
    leftover, consuming it in scheme order: it is the room the question has
    for all of them together, so a later pool can end capped at 0.
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
    # The leftover is the room *the question has* for all its pools together,
    # so pools consume it in scheme order rather than each receiving the whole
    # figure. Two "any N from" pools used to be capped at the full leftover
    # each: measured on a 4-mark question (one independent point plus an
    # "any 1 from" pool of three), a student claiming all three pool points
    # gained 3 where the scheme allows 1, and the question-level clamp never
    # fired because 3 sits under maximum_marks. A later pool can end capped at
    # 0 when an earlier one takes the room; that under-credits rather than
    # over-credits, which is the only safe direction for a cap whose whole
    # purpose is to bound a grant.
    pool_room = leftover
    for kind, members in real:
        counters[kind] += 1
        if kind == "alt":
            group_max = alt_cap(members)
        elif select_count is not None:
            tariffs = sorted((points[index].marks for index in members), reverse=True)
            group_max = max(0, min(pool_room, sum(tariffs[:select_count])))
            pool_room -= group_max
        else:
            group_max = pool_room
            pool_room -= group_max
        key = f"{kind}:{counters[kind]}"
        for index in members:
            result[index] = (key, group_max)
    return result
