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

**Fan-out is all-or-nothing (D3.14 §3).** ``create`` validates *every*
targeted class id (and, for a school-wide post, the target school) before
writing a single row. A teacher who owns nine of the ten classes they
targeted gets a 403 and **none** of the nine legitimate rows are written —
partial fan-out on an authorization failure would silently under-deliver an
announcement the caller believes went out in full. The actual inserts then
happen in one transaction: one row per class id (``class_id`` set,
``school_id`` NULL), plus, for a school-wide post, one further row
(``school_id`` set, ``class_id`` NULL) — the existing nullable-FK shape
:class:`~lemely.db.models.ops.Announcement` already has (no join table, no
schema change, per D1.2/D1.3's additive-only rule).

**School-wide is restricted to** ``school_admin`` **(D3.14 §3).** Enforced
here, not only at the router: a caller whose role is not ``school_admin``
requesting ``school_wide=True`` is an :class:`AnnouncementOwnershipError`,
and the target ``school_id`` must be one the caller actually administers
(:meth:`~lemely.db.class_repo.ClassService.member_school_ids`) — a teacher
belonging to a school as a plain member still cannot post school-wide.

**No injected clock, unlike several sibling services** (e.g.
:class:`~lemely.db.quiz_taking_repo.QuizTakingService`). Nothing in this
module computes anything from "now": ``list_for_author`` orders by the
DB-populated ``created_at`` column (:class:`~lemely.db.models.enums.TimestampMixin`,
a server default), and ``publish_at`` is stored exactly as given, never
compared against the current time. There is nothing time-dependent to make
injectable.

**Scheduling is inert.** ``publish_at`` is persisted verbatim — a caller's
optional "schedule this for later" — but **nothing in this codebase reads it
back to decide when to actually deliver anything**. There is no student-facing
announcement surface and no delivery/notification path at all yet; both are
Phase 5's (MISSION §4). A ``publish_at`` in the past is not an error (it
means "already published"); ``None`` means "publish immediately" — neither
distinction has any behavioural effect today, because nothing consumes this
column. A future session adding delivery must not assume a scheduler already
exists here — it does not.

**No attachment field, deliberately (D3.14 §2).** ``announcements`` has no
attachment column and no storage wiring for anything but student paper
uploads; the composer omits the control entirely rather than shipping a
disabled one. Do not add one, not even nullable — see D3.14 for the full
rationale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from lemely.db.class_repo import ClassNotFoundError, ClassOwnershipError
from lemely.db.models import Announcement
from lemely.db.models.enums import Role

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.class_repo import ClassService


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


class AnnouncementService:
    """Announcement compose/list/delete (T-12, D3.14).

    Constructed with a ``sessionmaker`` and the same
    :class:`~lemely.db.class_repo.ClassService` singleton every other
    class-scoped teacher service composes, so class/school tenancy can never
    diverge from what the rest of the teacher portal already enforces (D3.1).
    """

    def __init__(self, sessionmaker: sessionmaker[Session], class_service: ClassService) -> None:
        """Wire the service to its collaborators."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service

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
                ``school_wide`` was given (422), or ``school_wide`` was given
                without a ``school_id`` (422).
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
    "AnnouncementError",
    "AnnouncementNotFoundError",
    "AnnouncementOwnershipError",
    "AnnouncementRow",
    "AnnouncementService",
    "AnnouncementValidationError",
]
