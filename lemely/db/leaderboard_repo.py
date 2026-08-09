"""The weekly leaderboard query engine (P5.3 chunk A, D5.1 §6/§7/§9/§10).

Read-only — this module never writes an ``xp_events`` row (that is
:mod:`lemely.db.xp_repo`); it only ranks students by XP already awarded.

**The constraint that outranks everything else in this module (D5.1 §0):**
XP answers "did you do the work", never "were you good at it". The queries
here therefore must never join to a marking table — ``attempts``,
``question_results``, ``papers``, ``weakness_records`` — because doing so
would let a mark leak onto a public surface the product promises stays
private. That rule is pinned by
``tests/test_leaderboard_repo.py::TestSqlGuard``, which compiles the actual
``SELECT`` this module emits and asserts none of those four table names
appear, for every scope x basis combination. A comment is not a control; a
failing test is (D5.1 §0's own words).

**No denormalized weekly-XP column (D5.1 §6).** Every board sums
``xp_events`` live, every call. This build has been burned four times by a
hand-written mirror nothing regenerates; a ``weekly_xp`` column would be a
fifth.

**Scopes.** Exactly three: ``class``, ``school``, ``global`` — see
:class:`LeaderboardScope`. **The ``friends`` scope is deliberately absent.**
It depends on P5.4's not-yet-existing friendship table; this module does not
stub a fake branch for it, per the brief. Add it in P5.4 by adding a fourth
:class:`LeaderboardScope` member and a fourth membership-subquery branch in
:func:`_membership_subquery` — the ranking/opt-out/window machinery below is
already scope-agnostic and needs no other change.

**Opt-out is enforced in the query's WHERE clause (D5.1 §9), never in
Python.** :func:`_ranked_subquery` left-outer-joins ``student_profiles`` (a
student with no profile row at all has never opted out and must still
appear — an inner join here would silently erase every student who never
onboarded, which is exactly the trap D5.1 names) and filters on
``coalesce(leaderboard_opt_out, false) = false`` in the same ``SELECT`` that
does the ranking. No later layer re-checks the flag, and none should have
to: a row that never leaves Postgres cannot leak through a serialization bug.

**Ranking.** Standard competition ranking (``1,2,2,4``), computed by Postgres
via ``RANK() OVER (ORDER BY xp DESC)``. The rank itself is computed on XP
alone — ``user_id`` is deliberately NOT part of that ``ORDER BY``, because
``RANK()`` ties are decided over the whole ``ORDER BY`` tuple: adding a
tiebreak column there would silently turn every real XP tie into two
adjacent ranks, defeating "equal XP -> equal rank" by construction. The
``user_id`` tiebreak instead lives only in the *display* ordering
(:meth:`LeaderboardService.board`'s ``.order_by(rank, user_id)``), which
makes row order deterministic across runs without touching a single rank
value. Only students with at least one
matching ``xp_events`` row this week are ranked at all: the inner join from
the ranking subquery to ``xp_events`` (rather than an outer join) means a
student with zero XP simply never appears in the ranked set, and
:meth:`LeaderboardService.board` never invents a rank for them (UI spec
§1.4: never invent precision).

**Own-row pinning.** :meth:`LeaderboardService.board` always resolves the
viewer's true rank via a second, narrower query against the same ranked set
— even when the viewer falls outside the returned top-N, or is absent from
the ranked set altogether (zero XP this week, or opted out). The viewer's
own XP total is computed separately, with none of the scope/opt-out
filtering applied, because a student always sees their own real total
(D5.1 §9: "they keep earning XP... and still see their own totals") even on
a week they are unranked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, cast

import sqlalchemy as sa
from sqlalchemy import func, select

from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import Role, SeatStatus
from lemely.db.models.orgs import ClassEnrollment, Seat
from lemely.db.models.profiles import StudentProfile
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE, civil_date_in_zone

if TYPE_CHECKING:
    from collections.abc import Callable
    from zoneinfo import ZoneInfo

    from sqlalchemy import Select
    from sqlalchemy.orm import Session, sessionmaker

#: Default number of ranked rows a board returns (S-29 does not fix a number;
#: this is a generous, still-bounded default — callers may pass their own).
DEFAULT_TOP_N = 50


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


class LeaderboardScope(StrEnum):
    """The three ranking scopes this module implements (D5.1; ``friends`` is P5.4's)."""

    class_ = "class"
    school = "school"
    global_ = "global"


class LeaderboardUnavailableReason(StrEnum):
    """Why :meth:`LeaderboardService.board` returned a tri-state "unavailable" result."""

    no_school = "no_school"
    """The viewer holds no non-revoked seat at any school — the ``school``
    scope has nothing to rank them against. Modelled honestly as an
    unavailable outcome (mirroring P4.5's practice-generator refusal shape),
    never as an empty board pretending to be a real empty board."""


class LeaderboardError(Exception):
    """Base class for leaderboard-service failures."""


class LeaderboardUserNotFoundError(LeaderboardError):
    """No user exists for the supplied viewer id (→ 404)."""


class LeaderboardIneligibleViewerError(LeaderboardError):
    """The viewer exists but is not a student (→ 403-shaped; D5.1 §10)."""


class LeaderboardClassAccessError(LeaderboardError):
    """The viewer is not enrolled in the requested ``class_id`` (→ 403-shaped).

    Enforced here, in the service, not only at the router — a class-scope
    board is only ever reachable for a class the viewer is themselves
    enrolled in.
    """


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    """One ranked entry. Only students with at least one XP event this week appear here."""

    user_id: uuid.UUID
    xp: int
    rank: int
    """Standard competition ranking (equal XP -> equal rank; ties skip the next rank)."""


@dataclass(frozen=True, slots=True)
class LeaderboardViewerRow:
    """The viewer's own row, always present, even when unranked or outside the top-N."""

    user_id: uuid.UUID
    xp: int
    rank: int | None
    """``None`` when the viewer has no XP this week, or is opted out — never a
    fabricated last place (UI spec §1.4)."""


@dataclass(frozen=True, slots=True)
class LeaderboardResult:
    """Outcome of :meth:`LeaderboardService.board`."""

    status: str
    """``"ok"`` or ``"unavailable"``."""
    unavailable_reason: LeaderboardUnavailableReason | None
    week_start: date
    week_end: date
    rows: list[LeaderboardRow]
    """The top-N ranked rows. Empty when ``status="unavailable"``."""
    viewer: LeaderboardViewerRow | None
    """``None`` iff ``status="unavailable"``."""
    viewer_opted_out: bool
    """The explicit "viewer opted out" fact D5.1 §9 requires the route be
    able to surface honestly, independent of whether the viewer happens to
    have XP this week."""


def _week_bounds(today: date) -> tuple[date, date]:
    """Monday..Sunday (inclusive) of the ISO week containing ``today`` (D5.1 §6)."""
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _membership_subquery(
    scope: LeaderboardScope, *, class_id: uuid.UUID | None, school_id: uuid.UUID | None
) -> Select[tuple[uuid.UUID]] | None:
    """The set of user ids eligible for ``scope``, or ``None`` for no restriction (``global``)."""
    if scope is LeaderboardScope.class_:
        return select(ClassEnrollment.student_id).where(ClassEnrollment.class_id == class_id)
    if scope is LeaderboardScope.school:
        # Seat.assigned_user_id is nullable at the column level (an
        # unassigned seat), but the ``is_not(None)`` filter guarantees every
        # row this yields is non-null — cast makes that guarantee explicit
        # to mypy rather than widening the return type for every caller.
        return cast(
            "Select[tuple[uuid.UUID]]",
            select(Seat.assigned_user_id).where(
                Seat.school_id == school_id,
                Seat.status != SeatStatus.revoked,
                Seat.assigned_user_id.is_not(None),
            ),
        )
    return None


def _ranked_subquery(
    *,
    window_start: date,
    window_end: date,
    subject_code: str | None,
    membership: Select[tuple[uuid.UUID]] | None,
) -> Select[tuple[uuid.UUID, int, int]]:
    """Build the ranked-students SELECT (user_id, xp, rank) for one board.

    This is the statement the SQL guard test compiles and inspects — it must
    never grow a join to ``attempts``, ``question_results``, ``papers`` or
    ``weakness_records`` (D5.1 §0). It touches exactly ``xp_events``,
    ``users`` and ``student_profiles``, plus whichever membership table the
    caller's ``membership`` subquery contributes.
    """
    xp_sum = func.sum(XpEvent.amount)
    conditions = [
        XpEvent.awarded_on >= window_start,
        XpEvent.awarded_on <= window_end,
        User.role == Role.student,
        sa.or_(
            StudentProfile.leaderboard_opt_out.is_(None),
            StudentProfile.leaderboard_opt_out.is_(False),
        ),
    ]
    if subject_code is not None:
        conditions.append(XpEvent.subject_code == subject_code)
    if membership is not None:
        conditions.append(XpEvent.user_id.in_(membership))

    inner = (
        select(
            XpEvent.user_id.label("user_id"),
            xp_sum.label("xp"),
            # Rank is computed on xp alone — standard competition ranking
            # requires equal xp to produce equal rank. user_id is NOT part of
            # this ORDER BY: RANK() ties are decided over the *entire*
            # ORDER BY tuple, so adding user_id here would silently turn
            # every tie into two distinct ranks. The user_id tiebreak lives
            # only in the caller's *display* ordering (LeaderboardService
            # .board's .order_by(rank, user_id)), which is free to break ties
            # for a stable row order without touching the rank values.
            func.rank().over(order_by=xp_sum.desc()).label("rank"),
        )
        .select_from(XpEvent)
        .join(User, User.id == XpEvent.user_id)
        .outerjoin(StudentProfile, StudentProfile.user_id == XpEvent.user_id)
        .where(*conditions)
        .group_by(XpEvent.user_id)
    )
    ranked = inner.subquery("ranked")
    return select(ranked.c.user_id, ranked.c.xp, ranked.c.rank)


class LeaderboardService:
    """Rank students by weekly XP against ``xp_events`` (D5.1).

    Constructed with a ``sessionmaker``, an injectable clock, and the
    civil-date zone the weekly window is derived in — mirrors
    :class:`~lemely.db.xp_repo.XpService`'s shape exactly.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        now: Callable[[], datetime] = _utcnow,
        zone: ZoneInfo = DEFAULT_ZONE,
    ) -> None:
        """Wire the service to a session factory, a clock, and the week's civil-date zone."""
        self._sessionmaker = sessionmaker
        self._now = now
        self._zone = zone

    def board(
        self,
        viewer_id: uuid.UUID | str,
        scope: LeaderboardScope,
        *,
        subject_code: str | None = None,
        class_id: uuid.UUID | str | None = None,
        top_n: int = DEFAULT_TOP_N,
        now: datetime | None = None,
    ) -> LeaderboardResult:
        """Resolve one weekly board for ``viewer_id``.

        Args:
            viewer_id: The student viewing the board. Must resolve to a
                ``users`` row with ``role=Role.student`` (D5.1 §10).
            scope: ``class``, ``school`` or ``global`` (``friends`` is P5.4's
                — see the module docstring).
            subject_code: ``None`` for a total-XP board (all subjects); a
                syllabus code to filter to a per-subject board. Total boards
                ignore this entirely; per-subject boards filter
                ``xp_events.subject_code`` on it (D5.1 §7 as amended by
                D5.2).
            class_id: Required when ``scope=class``. The service verifies the
                viewer is themselves enrolled in this class before building
                any board (:class:`LeaderboardClassAccessError` otherwise) —
                this scope is only ever reachable for a class the viewer
                belongs to.
            top_n: How many ranked rows to return. Does not affect the
                viewer's own pinned row, which is always resolved regardless
                of whether it falls inside this cut.
            now: Injected clock override for tests; defaults to this
                service's constructor-supplied clock.

        Raises:
            ValueError: ``scope=class`` without a ``class_id``.
            LeaderboardUserNotFoundError: no user exists for ``viewer_id``.
            LeaderboardIneligibleViewerError: the viewer exists but is not a
                student.
            LeaderboardClassAccessError: ``scope=class`` and the viewer is
                not enrolled in ``class_id``.
        """
        viewer_uuid = _as_uuid(viewer_id)
        if scope is LeaderboardScope.class_ and class_id is None:
            raise ValueError("class_id is required for scope=class")
        class_uuid = _as_uuid(class_id) if class_id is not None else None

        moment = now if now is not None else self._now()
        today = civil_date_in_zone(moment, zone=self._zone)
        week_start, week_end = _week_bounds(today)

        with self._sessionmaker() as session:
            viewer = session.get(User, viewer_uuid)
            if viewer is None:
                raise LeaderboardUserNotFoundError(f"Unknown user: {viewer_uuid}")
            if viewer.role != Role.student:
                raise LeaderboardIneligibleViewerError(
                    f"User {viewer_uuid} has role={viewer.role!r}; "
                    "leaderboards are student-only (D5.1 §10)"
                )

            profile = session.scalar(
                select(StudentProfile).where(StudentProfile.user_id == viewer_uuid)
            )
            viewer_opted_out = bool(profile.leaderboard_opt_out) if profile is not None else False

            school_uuid: uuid.UUID | None = None
            if scope is LeaderboardScope.class_:
                enrolled = session.scalar(
                    select(ClassEnrollment.id).where(
                        ClassEnrollment.class_id == class_uuid,
                        ClassEnrollment.student_id == viewer_uuid,
                    )
                )
                if enrolled is None:
                    raise LeaderboardClassAccessError(
                        f"Viewer {viewer_uuid} is not enrolled in class {class_uuid}"
                    )
            elif scope is LeaderboardScope.school:
                school_uuid = session.scalar(
                    select(Seat.school_id).where(
                        Seat.assigned_user_id == viewer_uuid,
                        Seat.status != SeatStatus.revoked,
                    )
                )
                if school_uuid is None:
                    return LeaderboardResult(
                        status="unavailable",
                        unavailable_reason=LeaderboardUnavailableReason.no_school,
                        week_start=week_start,
                        week_end=week_end,
                        rows=[],
                        viewer=None,
                        viewer_opted_out=viewer_opted_out,
                    )

            membership = _membership_subquery(scope, class_id=class_uuid, school_id=school_uuid)
            ranked = _ranked_subquery(
                window_start=week_start,
                window_end=week_end,
                subject_code=subject_code,
                membership=membership,
            )
            ranked_sub = ranked.subquery("board")

            top_rows = session.execute(
                select(ranked_sub.c.user_id, ranked_sub.c.xp, ranked_sub.c.rank)
                .order_by(ranked_sub.c.rank, ranked_sub.c.user_id)
                .limit(top_n)
            ).all()
            rows = [
                LeaderboardRow(user_id=r.user_id, xp=int(r.xp), rank=int(r.rank)) for r in top_rows
            ]

            viewer_conditions = [
                XpEvent.user_id == viewer_uuid,
                XpEvent.awarded_on >= week_start,
                XpEvent.awarded_on <= week_end,
            ]
            if subject_code is not None:
                viewer_conditions.append(XpEvent.subject_code == subject_code)
            viewer_xp = (
                session.scalar(
                    select(func.coalesce(func.sum(XpEvent.amount), 0)).where(*viewer_conditions)
                )
                or 0
            )

            viewer_rank_sub = ranked.subquery("board_viewer")
            viewer_rank = session.scalar(
                select(viewer_rank_sub.c.rank).where(viewer_rank_sub.c.user_id == viewer_uuid)
            )

            viewer_row = LeaderboardViewerRow(
                user_id=viewer_uuid,
                xp=int(viewer_xp),
                rank=int(viewer_rank) if viewer_rank is not None else None,
            )

            return LeaderboardResult(
                status="ok",
                unavailable_reason=None,
                week_start=week_start,
                week_end=week_end,
                rows=rows,
                viewer=viewer_row,
                viewer_opted_out=viewer_opted_out,
            )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "DEFAULT_TOP_N",
    "LeaderboardClassAccessError",
    "LeaderboardError",
    "LeaderboardIneligibleViewerError",
    "LeaderboardResult",
    "LeaderboardRow",
    "LeaderboardScope",
    "LeaderboardService",
    "LeaderboardUnavailableReason",
    "LeaderboardUserNotFoundError",
    "LeaderboardViewerRow",
]
