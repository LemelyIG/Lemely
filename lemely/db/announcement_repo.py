"""Announcement compose/list/delete service — the T-12 backend (P3.8 chunk a, D3.14).

Mirrors :mod:`lemely.db.class_repo`'s shape: pure ownership/mutation logic
over a ``sessionmaker``, domain errors mapped to HTTP status codes by a thin
router layer (:mod:`lemely.web.routers.announcements`), testable against
Postgres with no GoTrue dependency.

**Tenancy is entirely delegated to** :class:`~lemely.db.class_repo.ClassService`
**— this module runs no ``classes``/``school_memberships`` query of its own.**
Every class id in a create call is validated with
:meth:`~lemely.db.class_repo.ClassService.get_class` (the same ownership rule
every other class-scoped route already enforces, D3.1: a teacher owns only
their own classes, a school_admin administers only schools they hold a
``school_admin`` membership for, ``platform_admin`` sees none); a school-wide
post is validated with
:meth:`~lemely.db.class_repo.ClassService.member_school_ids`. Reusing these
seams rather than re-querying ``classes``/``school_memberships`` here is what
keeps "may this caller touch this class/school" defined in exactly one place.

**The audience is exclusive: specific classes OR the whole school, never
both** (UI-spec T-12 offers them as alternatives: "class, several classes, or
whole school"). Requesting both is a 422, not a union. This is enforced here
rather than left to the composer UI because the two overlap: a student
enrolled in class X of school S is in *both* audiences, so a combined request
would hand Phase 5 — which owns delivery and has not been written yet — two
rows resolving to one recipient, i.e. a duplicate notification whose cause
would be invisible from the delivery side. Cheaper to make unrepresentable
now than to detect there.

**Fan-out is all-or-nothing (D3.14 §3).** ``create`` validates *every*
targeted class id (and, for a school-wide post, the target school) before
writing a single row. A teacher who owns nine of the ten classes they
targeted gets a 403 and **none** of the nine legitimate rows are written —
partial fan-out on an authorization failure would silently under-deliver an
announcement the caller believes went out in full. The actual inserts then
happen in one transaction: one row per class id (``class_id`` set,
``school_id`` NULL), or, for a school-wide post, a single row
(``school_id`` set, ``class_id`` NULL) — the existing nullable-FK shape
:class:`~lemely.db.models.ops.Announcement` already has (no join table, no
schema change, per D1.2/D1.3's additive-only rule).

**School-wide is restricted to** ``school_admin`` **(D3.14 §3).** Enforced
here, not only at the router: a caller whose role is not ``school_admin``
requesting ``school_wide=True`` is an :class:`AnnouncementOwnershipError`,
and the target ``school_id`` must be one the caller actually administers
(:meth:`~lemely.db.class_repo.ClassService.member_school_ids`) — a teacher
belonging to a school as a plain member still cannot post school-wide.

**The clock is injected** (``now=``), following
:class:`~lemely.db.quiz_taking_repo.QuizTakingService` and every sibling
service. This module did **not** have one until P5.5, and its docstring
correctly said so at the time: the write path computes nothing from "now"
(``list_for_author`` orders by the DB-populated ``created_at``, and
``publish_at`` was stored exactly as given). The student read path added in
P5.5 is what made a clock necessary — see below.

**Scheduling is live as of P5.5, and this is a behaviour change worth
reading.** Until P5.5, ``publish_at`` was persisted verbatim and **nothing in
the codebase read it back**: there was no student-facing surface, so the
teacher's "schedule this for later" control had no effect on anyone.
:meth:`AnnouncementService.list_for_student` is its first consumer, and it
honours the column — a row whose ``publish_at`` is in the future is invisible
to students until that moment passes. That is not a refinement; without it the
composer's scheduling control would be an outright lie, promising a teacher
that a post they wrote today goes out next Monday while every student in the
class could already read it.

``None`` means "publish immediately" and is the overwhelmingly common case; a
``publish_at`` in the past means "already published" and is not an error.
**The author's own view is deliberately unfiltered** — ``list_for_author``
still returns scheduled rows, because a teacher must be able to see and delete
what they have queued. Filtering is a property of the *student* view only.

**No attachment field, deliberately (D3.14 §2).** ``announcements`` has no
attachment column and no storage wiring for anything but student paper
uploads; the composer omits the control entirely rather than shipping a
disabled one. Do not add one, not even nullable — see D3.14 for the full
rationale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from lemely.db.class_repo import ClassNotFoundError, ClassOwnershipError
from lemely.db.models import Announcement, AnnouncementRead
from lemely.db.models.enums import Role, SeatStatus
from lemely.db.models.orgs import ClassEnrollment, Seat

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.class_repo import ClassService


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


#: Default page size for the student announcement list. S-28 does not fix a
#: number; this is a generous but still-bounded default.
DEFAULT_STUDENT_LIMIT = 50


class AnnouncementError(Exception):
    """Base class for announcement-service failures."""


class AnnouncementNotFoundError(AnnouncementError):
    """No announcement, or no targeted class, exists for the supplied id (→ 404)."""


class AnnouncementOwnershipError(AnnouncementError):
    """The caller may not target this class/school, or does not own this row (→ 403)."""


class AnnouncementValidationError(AnnouncementError):
    """The request names no audience at all, or is otherwise malformed (→ 422)."""


@dataclass(frozen=True, slots=True)
class AnnouncementRow:
    """One announcement row, detached from its ORM session."""

    announcement_id: uuid.UUID
    author_id: uuid.UUID
    school_id: uuid.UUID | None
    class_id: uuid.UUID | None
    title: str
    body: str
    publish_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StudentAnnouncementRow:
    """One announcement as a student sees it: the row plus *their* read state.

    ``read_at`` is ``None`` when this student has no receipt — unread is an
    absence, not a flag (migration ``0016``). It is per-viewer and can never
    be folded into :class:`AnnouncementRow`, which is shared with the author
    view where "read" has no meaning.
    """

    announcement: AnnouncementRow
    read_at: datetime | None


class AnnouncementService:
    """Announcement compose/list/delete (T-12, D3.14).

    Constructed with a ``sessionmaker`` and the same
    :class:`~lemely.db.class_repo.ClassService` singleton every other
    class-scoped teacher service composes, so class/school tenancy can never
    diverge from what the rest of the teacher portal already enforces (D3.1).
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        class_service: ClassService,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to its collaborators."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service
        self._now = now

    # -- Create -----------------------------------------------------------------

    def create(
        self,
        author_id: uuid.UUID | str,
        author_role: Role | str,
        *,
        title: str,
        body: str,
        class_ids: Sequence[uuid.UUID | str] = (),
        school_wide: bool = False,
        school_id: uuid.UUID | str | None = None,
        publish_at: datetime | None = None,
    ) -> list[AnnouncementRow]:
        """Create one row per class id, plus one school-wide row if requested.

        Validates every target **before writing anything** (see module
        docstring) — a rejection on any one target leaves the table
        completely unchanged, never a partial fan-out.

        Raises:
            AnnouncementValidationError: Neither ``class_ids`` nor
                ``school_wide`` was given (422); **both** were given (422 —
                see module docstring); or ``school_wide`` was given without a
                ``school_id`` (422).
            AnnouncementOwnershipError: The caller does not own one of the
                targeted classes (403); or ``school_wide`` was requested by a
                caller whose role is not ``school_admin``, or for a school
                the caller does not administer (403).
            AnnouncementNotFoundError: One of ``class_ids`` matches no class
                anywhere (404).
        """
        author_uuid = _as_uuid(author_id)
        role = _normalize_role(author_role)
        class_uuids = [_as_uuid(cid) for cid in class_ids]

        if not class_uuids and not school_wide:
            raise AnnouncementValidationError(
                "An announcement must target at least one class or the whole school"
            )
        if class_uuids and school_wide:
            raise AnnouncementValidationError(
                "An announcement targets either specific classes or the whole school, not both"
            )

        school_uuid: uuid.UUID | None = None
        if school_wide:
            if role != Role.school_admin:
                raise AnnouncementOwnershipError(
                    "Only school_admin may post a school-wide announcement"
                )
            if school_id is None:
                raise AnnouncementValidationError(
                    "school_id is required for a school-wide announcement"
                )
            school_uuid = _as_uuid(school_id)
            if school_uuid not in self._class_service.member_school_ids(author_uuid):
                raise AnnouncementOwnershipError(f"Caller does not administer school {school_uuid}")

        # Validate every class id before any row is written — see module docstring.
        for class_uuid in class_uuids:
            try:
                self._class_service.get_class(author_uuid, role, class_uuid)
            except ClassNotFoundError as exc:
                raise AnnouncementNotFoundError(str(exc)) from exc
            except ClassOwnershipError as exc:
                raise AnnouncementOwnershipError(str(exc)) from exc

        with self._sessionmaker() as session, session.begin():
            created: list[Announcement] = []
            for class_uuid in class_uuids:
                row = Announcement(
                    author_id=author_uuid,
                    class_id=class_uuid,
                    title=title,
                    body=body,
                    publish_at=publish_at,
                )
                session.add(row)
                created.append(row)
            if school_wide:
                row = Announcement(
                    author_id=author_uuid,
                    school_id=school_uuid,
                    title=title,
                    body=body,
                    publish_at=publish_at,
                )
                session.add(row)
                created.append(row)
            session.flush()
            return [_to_row(row) for row in created]

    # -- Read ---------------------------------------------------------------

    def list_for_author(self, author_id: uuid.UUID | str) -> list[AnnouncementRow]:
        """Return every announcement ``author_id`` created, newest first."""
        author_uuid = _as_uuid(author_id)
        with self._sessionmaker() as session:
            stmt = (
                select(Announcement)
                .where(Announcement.author_id == author_uuid)
                .order_by(Announcement.created_at.desc())
            )
            return [_to_row(row) for row in session.scalars(stmt).all()]

    # -- Student read path (P5.5) ------------------------------------------

    def list_for_student(
        self,
        student_id: uuid.UUID | str,
        *,
        limit: int = DEFAULT_STUDENT_LIMIT,
    ) -> list[StudentAnnouncementRow]:
        """Return the published announcements this student may see, newest first.

        Visibility is the union of the two audiences ``create`` can write:

        * a ``class_id`` row, when the student has a ``class_enrollments``
          row for that class;
        * a ``school_id`` row, when the student holds a non-revoked
          :class:`~lemely.db.models.orgs.Seat` in that school.

        **The school arm keys on ``Seat``, not ``SchoolMembership``.**
        ``school_memberships`` is staff-only — its role vocabulary is exactly
        ``teacher``/``school_admin`` — so no student ever has a row there and
        keying on it would make every school-wide announcement permanently
        invisible to precisely the people it was written for. That failure
        reads as "the school never posts anything", not as a bug, which is
        what makes it worth stating rather than merely doing. D5.4 cost P5.3
        a chunk to exactly this; :mod:`lemely.db.leaderboard_repo` resolves
        school membership the same way.

        Future-dated rows are excluded (see the module docstring on
        scheduling); ``publish_at IS NULL`` means published immediately.
        Ordering is by effective publication time — ``publish_at`` when set,
        otherwise ``created_at`` — so a back-dated post sorts where its author
        meant it to, not at the top because it was typed last.
        """
        student_uuid = _as_uuid(student_id)
        now = self._now()
        effective_at = sa.func.coalesce(Announcement.publish_at, Announcement.created_at)

        enrolled_classes = select(ClassEnrollment.class_id).where(
            ClassEnrollment.student_id == student_uuid
        )
        seated_schools = select(Seat.school_id).where(
            Seat.assigned_user_id == student_uuid,
            Seat.status != SeatStatus.revoked,
        )

        with self._sessionmaker() as session:
            stmt = (
                select(Announcement, AnnouncementRead.read_at)
                .outerjoin(
                    AnnouncementRead,
                    sa.and_(
                        AnnouncementRead.announcement_id == Announcement.id,
                        AnnouncementRead.user_id == student_uuid,
                    ),
                )
                .where(
                    sa.or_(
                        Announcement.class_id.in_(enrolled_classes),
                        Announcement.school_id.in_(seated_schools),
                    ),
                    sa.or_(
                        Announcement.publish_at.is_(None),
                        Announcement.publish_at <= now,
                    ),
                )
                .order_by(effective_at.desc(), Announcement.id)
                .limit(limit)
            )
            return [
                StudentAnnouncementRow(announcement=_to_row(row), read_at=read_at)
                for row, read_at in session.execute(stmt).all()
            ]

    def unread_count_for_student(self, student_id: uuid.UUID | str) -> int:
        """Count the published announcements in this student's scope with no receipt.

        Unread is an **absence** of an ``announcement_reads`` row, never a
        flag — see migration ``0016``. Deliberately not derived from
        ``len(list_for_student(...))``: that call is ``LIMIT``-ed, so a
        student with more unread announcements than the page size would be
        told they have exactly a page's worth.
        """
        student_uuid = _as_uuid(student_id)
        now = self._now()

        enrolled_classes = select(ClassEnrollment.class_id).where(
            ClassEnrollment.student_id == student_uuid
        )
        seated_schools = select(Seat.school_id).where(
            Seat.assigned_user_id == student_uuid,
            Seat.status != SeatStatus.revoked,
        )

        with self._sessionmaker() as session:
            stmt = (
                select(sa.func.count())
                .select_from(Announcement)
                .outerjoin(
                    AnnouncementRead,
                    sa.and_(
                        AnnouncementRead.announcement_id == Announcement.id,
                        AnnouncementRead.user_id == student_uuid,
                    ),
                )
                .where(
                    sa.or_(
                        Announcement.class_id.in_(enrolled_classes),
                        Announcement.school_id.in_(seated_schools),
                    ),
                    sa.or_(
                        Announcement.publish_at.is_(None),
                        Announcement.publish_at <= now,
                    ),
                    AnnouncementRead.id.is_(None),
                )
            )
            return int(session.scalar(stmt) or 0)

    def mark_read(
        self,
        student_id: uuid.UUID | str,
        announcement_id: uuid.UUID | str,
    ) -> datetime:
        """Record that this student read this announcement. Idempotent.

        Returns the ``read_at`` of record — on a re-open, the **original**
        first-read time, not the current one. A "last opened" timestamp is a
        different feature and moving ``read_at`` would quietly destroy the
        only number this table holds.

        Idempotency is the database's job: two tabs firing this concurrently
        both pass any Python existence check, but only one can win
        ``uq_announcement_reads_pair``. The loser catches
        :class:`~sqlalchemy.exc.IntegrityError` inside a **savepoint** and
        re-reads the winner's row. The savepoint is what makes the error
        recoverable rather than merely catchable — a failed ``flush`` poisons
        the enclosing transaction, leaving nothing to re-read with (D5.7,
        learned the hard way on ``FriendService.request``).

        Raises:
            AnnouncementNotFoundError: The announcement does not exist, is not
                in this student's scope, or is not published yet (404). These
                are deliberately **indistinguishable**: a student who could
                tell "exists but not yours" from "does not exist" could
                enumerate other classes' announcement ids.
        """
        student_uuid = _as_uuid(student_id)
        announcement_uuid = _as_uuid(announcement_id)
        now = self._now()

        with self._sessionmaker() as session, session.begin():
            if not self._is_visible(session, student_uuid, announcement_uuid, now):
                raise AnnouncementNotFoundError(f"Unknown announcement: {announcement_uuid}")

            existing = session.scalar(
                select(AnnouncementRead.read_at).where(
                    AnnouncementRead.announcement_id == announcement_uuid,
                    AnnouncementRead.user_id == student_uuid,
                )
            )
            if existing is not None:
                return existing

            try:
                with session.begin_nested():
                    session.add(
                        AnnouncementRead(
                            announcement_id=announcement_uuid,
                            user_id=student_uuid,
                            read_at=now,
                        )
                    )
                    session.flush()
            except IntegrityError:
                # Lost the race for uq_announcement_reads_pair. The winner's
                # row is the row of record; re-read it rather than reporting
                # a conflict the caller cannot act on — both tabs did read it.
                won = session.scalar(
                    select(AnnouncementRead.read_at).where(
                        AnnouncementRead.announcement_id == announcement_uuid,
                        AnnouncementRead.user_id == student_uuid,
                    )
                )
                if won is None:  # pragma: no cover - defensive
                    raise
                return won
            return now

    def _is_visible(
        self,
        session: Session,
        student_uuid: uuid.UUID,
        announcement_uuid: uuid.UUID,
        now: datetime,
    ) -> bool:
        """Whether this published announcement is in this student's audience.

        Shares the scope definition with :meth:`list_for_student` by
        construction rather than by convention — if the two drifted, a
        student could mark-as-read something they cannot see listed.
        """
        enrolled_classes = select(ClassEnrollment.class_id).where(
            ClassEnrollment.student_id == student_uuid
        )
        seated_schools = select(Seat.school_id).where(
            Seat.assigned_user_id == student_uuid,
            Seat.status != SeatStatus.revoked,
        )
        stmt = select(Announcement.id).where(
            Announcement.id == announcement_uuid,
            sa.or_(
                Announcement.class_id.in_(enrolled_classes),
                Announcement.school_id.in_(seated_schools),
            ),
            sa.or_(
                Announcement.publish_at.is_(None),
                Announcement.publish_at <= now,
            ),
        )
        return session.scalar(stmt) is not None

    # -- Delete ---------------------------------------------------------------

    def delete(self, author_id: uuid.UUID | str, announcement_id: uuid.UUID | str) -> None:
        """Delete one announcement. Author-scoped.

        Raises:
            AnnouncementNotFoundError: No announcement exists with this id (404).
            AnnouncementOwnershipError: The announcement exists but was not
                authored by ``author_id`` (403) — deleting someone else's
                announcement is never a silent no-op.
        """
        author_uuid = _as_uuid(author_id)
        announcement_uuid = _as_uuid(announcement_id)
        with self._sessionmaker() as session, session.begin():
            row = session.get(Announcement, announcement_uuid)
            if row is None:
                raise AnnouncementNotFoundError(f"Unknown announcement: {announcement_uuid}")
            if row.author_id != author_uuid:
                raise AnnouncementOwnershipError(
                    f"Caller does not own announcement {announcement_uuid}"
                )
            session.execute(delete(Announcement).where(Announcement.id == announcement_uuid))


def _to_row(row: Announcement) -> AnnouncementRow:
    return AnnouncementRow(
        announcement_id=row.id,
        author_id=row.author_id,
        school_id=row.school_id,
        class_id=row.class_id,
        title=row.title,
        body=row.body,
        publish_at=row.publish_at,
        created_at=row.created_at,
    )


def _normalize_role(role: Role | str) -> Role:
    """Coerce a str/Role to :class:`Role`, raising ``ValueError`` if unknown."""
    if isinstance(role, Role):
        return role
    try:
        return Role(role)
    except ValueError as exc:
        raise ValueError(f"Unknown role: {role!r}") from exc


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "DEFAULT_STUDENT_LIMIT",
    "AnnouncementError",
    "AnnouncementNotFoundError",
    "AnnouncementOwnershipError",
    "AnnouncementRow",
    "AnnouncementService",
    "AnnouncementValidationError",
    "StudentAnnouncementRow",
]
