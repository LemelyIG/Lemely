"""Data grants and the tutor access audit (SPEC §a.2, §b.2 S8-S11, T19, T20; ADR-T02, ADR-T03).

A grant is a student's consent for one tutor to read their derived analytics.
This module is the single writer of ``tutor_data_grants`` and
``tutor_access_audit``, and the only place that decides whether a tutor may read
a student: ADR-T03 makes the grant a separate gate that never unions with the
class roster, so no function here reads ``classes`` to authorise anything (the
one roster read, :meth:`TutorGrantRepository.grants_for_student`'s
``also_teaches_classes``, is information for the student about their own classes).

**Validity is the SQL mirror of ``core.tutor_grants.grant_is_valid``**
(:func:`grant_valid_sql`): not revoked, not expired, the tutor ``listed`` or
``pending_review`` (paused is fine), and no active block between the pair in
either direction (``tutoring_predicates.active_block_between_sql``, keyed on
``users.id``). ``tests/test_grant_predicate_parity.py`` pins it to the core
function over generated inputs. S8, S9, S10 and PA6 show the student (and their
parents) the reason through ``core.tutor_grants.grant_status_for_student`` on the
same row: ``blocked`` only when the student's own block explains it, read from
the instant of their first block of the tutor
(``tutoring_predicates.student_block_of_tutor_created_at_sql``); a tutor's block,
a suspension and a close all read ``tutor_unavailable``, so a student never learns
that a tutor blocked them (SPEC §i.7, §i.8, SC-11). The list order (live first,
then newest first) reads neither the status nor the revoke reason, so a grant
keeps its place whichever tutor-side end revoked it.

**The gate (T20, O2, O3, O18).** :meth:`TutorGrantRepository.require_valid_grant`
takes the caller's own profile id, resolved by the route from ``auth.user_id``,
and nothing else that names a tutor. In one transaction it takes the tutor row
``FOR SHARE`` (SPEC §a.4b step 1), the student's ``users`` row ``FOR KEY SHARE``
(step 2, see "Lock order" below), then the pair's live grant row ``FOR SHARE``
(so a revoke that is still in flight is waited for, and once it has committed no
read succeeds: ``test_t20_waits_for_an_inflight_revoke_and_then_refuses``),
checks validity, and writes the ``detail`` audit row. Only then, still in that
transaction, is the student's label read; the route loads the history after the
commit. An ended grant raises :class:`AccessEnded` and no grant ever for the pair
raises :class:`NoGrant`; neither writes a row. A failure anywhere in that
transaction raises :class:`AuditUnavailable`, which the route turns into a 500
with no body (fail closed, SPEC §b.4 point 3).

**T19** writes one ``list`` row per student on the page before it reads their
names, in three statements whatever the page size (SPEC §e.3: validity and rows;
one audit insert; names and upcoming-session counts).

**Writes (S9, S10).** Create takes the tutor row ``FOR SHARE``, the student's
``users`` row ``FOR KEY SHARE``, then the pair lock
(``booking_repo.lock_pair_in_session``, the one implementation of SPEC §a.4b step
3), re-checks blocks after the locks, and returns the live grant when one exists
(``uq_tutor_data_grants_live`` maps to "return the existing grant", SPEC §a.4).
Every refusal (unknown, not listed, paused, blocked) is a :class:`TutorNotFound`,
which the route answers with SP2's own 404 (O11): a student is never told that a
tutor is hidden, or that a tutor blocked them. The linked parents' email is
queued in the same transaction (``email_outbox_repo.enqueue_in_session``); the
inbox notices are the router's, after commit. Revoke takes the tutor row and the
pair lock and is a compare-and-set on ``revoked_at IS NULL``, so a repeat changes
nothing; it inserts no row that references the student, so it needs no step 2.

**Lock order (SPEC §a.4b, §i.6).** A booking create holds the student's ``users``
row ``FOR UPDATE`` and then waits for the pair lock. S9's grant insert and T20's
audit insert reference that row, and their foreign-key checks take ``KEY SHARE``
on it; taken there, late, S9 would hold the pair lock while it waited for the
create (a two-way deadlock), and T20 would hold the live grant row that a revoke
holding the pair lock waits for (T20, revoke, create: a three-way one). Both
therefore take ``FOR KEY SHARE`` on the student right after the tutor row, before
anything a create or a revoke could wait for. ``KEY SHARE`` stays compatible with
the ``FOR NO KEY UPDATE`` an unlink takes on the same row (T09).

Every value reaches SQL as a bound parameter; the only text spliced into a
statement is a fragment built here or in ``tutoring_predicates`` from constants.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.tutor_directory import public_name, student_label
from lemely.core.tutor_grants import GrantFacts, grant_status_for_student
from lemely.db.booking_repo import lock_pair_in_session
from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models.enums import GrantRevokeReason
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_directory_repo import MODES, SubjectRef, TutorCard, subjects_by_tutor
from lemely.db.tutoring_predicates import (
    EFFECTIVE_STATE_SQL,
    active_block_between_sql,
    listed_and_not_paused_sql,
    student_block_of_tutor_created_at_sql,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.tutor_grants import StudentGrantStatus
    from lemely.db.tutor_directory_repo import Mode

log = structlog.get_logger(__name__)

#: SPEC §0 "Paging": ``limit`` 1..50.
MAX_PAGE_SIZE: Final = 50
#: SPEC §b.2 S8: at most this many grants are listed.
MAX_GRANTS_LISTED: Final = 200
#: The email the linked parents get when a grant is created (SPEC §b.4).
GRANT_EMAIL_TEMPLATE: Final = "tutor_access_granted"

_ALIAS: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_GRANT_COLUMNS: Final = (
    "g.id, g.student_id, g.tutor_profile_id, g.scope::text AS scope, g.created_at, "
    "g.expires_at, g.revoked_at, g.revoke_reason::text AS revoke_reason"
)
_CARD_COLUMNS: Final = (
    "tp.public_first_name, tp.public_last_initial, tp.headline, tp.offers_virtual, "
    "tp.offers_in_person, tp.offers_other, tp.area_code, tp.rating_sum, tp.rating_count"
)
_MODE_COLUMN: Final[Mapping[str, str]] = {
    "virtual": "offers_virtual",
    "in_person": "offers_in_person",
    "other": "offers_other",
}


# ---------------------------------------------------------------------------
# Errors (each carries the API code the router sends)
# ---------------------------------------------------------------------------


class GrantError(Exception):
    """Base class: ``code`` is the stable API code, ``message`` plain English."""

    code: str = "grant_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NoGrant(GrantError):
    """T20: no grant ever existed between the caller's profile and this id (404)."""

    code = "not_found"


class AccessEnded(GrantError):
    """T20: a grant existed for this pair but is not valid now, whatever the reason (403)."""

    code = "access_ended"


class GrantNotFound(GrantError):
    """S10: not one of the caller's grants (unknown and someone else's alike)."""

    code = "not_found"


class TutorNotFound(GrantError):
    """S9: no tutor this student may see has this id (O11: one 404, SP2's).

    The subclasses name the reason for logs and tests only; they share this code,
    so the answer never tells a student which reason applied.
    """

    code = "not_found"


class TutorNotListed(TutorNotFound):
    """S9: the tutor is not listed, or is paused."""


class TutorBlocked(TutorNotFound):
    """S9: an active block between the student and the tutor, in either direction."""


class AuditUnavailable(GrantError):
    """The audit row could not be written, so the read must not happen (fail closed)."""

    code = "audit_unavailable"


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GrantRow:
    """One ``tutor_data_grants`` row."""

    id: uuid.UUID
    student_id: uuid.UUID
    tutor_profile_id: uuid.UUID
    scope: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: GrantRevokeReason | None


@dataclass(frozen=True, slots=True)
class GrantNoticeFacts:
    """What the router needs for the after-commit notices, read inside the change.

    ``linked_parent_ids`` is read in the grant's transaction, so the inbox notices
    name the same parents as the outbox rows (empty on a revoke: SPEC §b.4 tells
    no parent when a grant ends).
    """

    tutor_user_id: uuid.UUID
    tutor_name: str
    student_label: str
    linked_parent_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class GrantCreated:
    """S9's outcome: the live grant and whether this call created it."""

    grant: GrantRow
    created: bool
    notice: GrantNoticeFacts


@dataclass(frozen=True, slots=True)
class GrantRevoked:
    """S10's outcome: ``revoked_now`` is false for a repeat (or a grant already ended)."""

    grant: GrantRow
    revoked_now: bool
    notice: GrantNoticeFacts


@dataclass(frozen=True, slots=True)
class GrantView:
    """A grant as S8/PA6 show it: the tutor's public card and the status.

    ``status`` is what the student and their parents may read
    (``core.tutor_grants.grant_status_for_student``: a tutor's block, a suspension
    and a close read ``tutor_unavailable``). ``also_teaches_classes`` names the
    student's own classes whose teacher is the tutor's user (SC-2e); empty when not
    asked for.
    """

    grant: GrantRow
    tutor: TutorCard
    status: StudentGrantStatus
    also_teaches_classes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GrantAccess:
    """T20: a valid grant whose read was recorded at ``accessed_at`` (already committed)."""

    grant: GrantRow
    accessed_at: datetime
    student_label: str


@dataclass(frozen=True, slots=True)
class TutorStudentKey:
    """T19's keyset position: ``grantedAt DESC, grantId``."""

    granted_at: datetime
    grant_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class TutorStudentItem:
    """One T19 row: the label a tutor may see (F12), never analytics."""

    student_id: uuid.UUID
    display_name: str
    grant_id: uuid.UUID
    granted_at: datetime
    upcoming_sessions: int


@dataclass(frozen=True, slots=True)
class TutorStudentsPage:
    items: tuple[TutorStudentItem, ...]
    next_key: TutorStudentKey | None


@dataclass(frozen=True, slots=True)
class AccessLogKey:
    """S11/PA7's keyset position: ``accessed_at DESC, id DESC``.

    The entry id is a random UUID (SPEC §0, ID-5): it reveals no count and no time,
    and no DTO carries it.
    """

    accessed_at: datetime
    entry_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AccessLogEntry:
    """One tutor read, with the tutor's public name as it was then."""

    tutor_profile_id: uuid.UUID | None
    tutor_name: str
    action: Literal["list", "detail"]
    accessed_at: datetime


@dataclass(frozen=True, slots=True)
class AccessLogPage:
    items: tuple[AccessLogEntry, ...]
    next_key: AccessLogKey | None


# ---------------------------------------------------------------------------
# Cursors (SPEC §0 "Paging", O21): the endpoint tag is the router's
# ---------------------------------------------------------------------------


def tutor_students_cursor(endpoint: str, key: TutorStudentKey) -> str:
    """The cursor for the page after ``key``: the grant's instant and id (both shown on T19)."""
    return encode_cursor(endpoint, [key.granted_at, key.grant_id])


def parse_tutor_students_cursor(token: str, endpoint: str) -> TutorStudentKey:
    """Decode a T19 cursor; :class:`CursorError` unless minted for ``endpoint``."""
    granted_at, grant_id = decode_cursor(token, endpoint=endpoint, types=(datetime, uuid.UUID))
    if not isinstance(granted_at, datetime) or not isinstance(grant_id, uuid.UUID):
        raise CursorError("cursor has the wrong value types")  # pragma: no cover - decoder-typed
    return TutorStudentKey(granted_at=granted_at, grant_id=grant_id)


def access_log_cursor(endpoint: str, key: AccessLogKey) -> str:
    """The cursor for the page after ``key`` in an access log."""
    return encode_cursor(endpoint, [key.accessed_at, key.entry_id])


def parse_access_log_cursor(token: str, endpoint: str) -> AccessLogKey:
    """Decode an access-log cursor; :class:`CursorError` unless minted for ``endpoint``."""
    accessed_at, entry_id = decode_cursor(token, endpoint=endpoint, types=(datetime, uuid.UUID))
    if not isinstance(accessed_at, datetime) or not isinstance(entry_id, uuid.UUID):
        raise CursorError("cursor has the wrong value types")  # pragma: no cover - decoder-typed
    return AccessLogKey(accessed_at=accessed_at, entry_id=entry_id)


# ---------------------------------------------------------------------------
# The validity mirror and session-level steps (the caller owns the transaction)
# ---------------------------------------------------------------------------


def grant_valid_sql(grant_alias: str, profile_alias: str) -> str:
    """SQL mirror of ``core.tutor_grants.grant_is_valid`` (SPEC §e.1, SC-3).

    ``grant_alias`` names a ``tutor_data_grants`` row and ``profile_alias`` its
    tutor's ``tutor_profiles`` row (joined on ``id = tutor_profile_id``); both must
    be plain SQL aliases. Time is the database ``now()``.
    """
    for alias in (grant_alias, profile_alias):
        if not _ALIAS.fullmatch(alias):
            raise ValueError(f"expected a plain SQL alias, got {alias!r}")
    g, p = grant_alias, profile_alias
    block = active_block_between_sql(f"{g}.student_id", f"{p}.user_id")
    return (
        f"({g}.revoked_at IS NULL "
        f"AND ({g}.expires_at IS NULL OR {g}.expires_at > now()) "
        f"AND {p}.listing_state IN ('listed', 'pending_review') "
        f"AND NOT {block})"
    )


def _key_share_student(session: Session, student_id: uuid.UUID) -> None:
    """SPEC §a.4b step 2 for a write that inserts a row referencing the student.

    ``FOR KEY SHARE`` is what the insert's foreign-key check would take anyway;
    taking it here, before the pair lock or the grant row, keeps the global order
    (module docstring, "Lock order"). A missing row locks nothing; the caller's own
    checks decide what that means.
    """
    session.execute(
        sa.text("SELECT 1 FROM users WHERE id = :student_id FOR KEY SHARE"),
        {"student_id": student_id},
    )


def student_shared_in_session(
    session: Session, tutor_profile_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """The students in ``student_ids`` with a valid grant to this tutor; no audit row (F13).

    ``BookingDTO.studentShared`` for a tutor viewer: one statement for a whole page.
    """
    if not student_ids:
        return set()
    rows = session.execute(
        sa.text(
            "SELECT g.student_id FROM tutor_data_grants g "  # noqa: S608 - constant fragments
            "JOIN tutor_profiles tp ON tp.id = g.tutor_profile_id "
            "WHERE g.tutor_profile_id = :tutor_profile_id "
            "AND g.student_id = ANY(CAST(:student_ids AS uuid[])) "
            f"AND {grant_valid_sql('g', 'tp')}"
        ),
        {"tutor_profile_id": tutor_profile_id, "student_ids": list(student_ids)},
    ).scalars()
    return {_as_uuid(value) for value in rows}


def revoke_live_in_session(
    session: Session,
    *,
    tutor_profile_id: uuid.UUID,
    student_id: uuid.UUID | None,
    reason: GrantRevokeReason,
    at: datetime | None = None,
) -> list[uuid.UUID]:
    """End the tutor's live grants (one student's, or all) for a sweep; return their ids.

    For the block, suspension and close sweeps (SPEC §a.2, §a.3, SC-3), which hold
    the §a.4b locks themselves. A student's own revoke goes through
    :meth:`TutorGrantRepository.revoke`, so ``reason`` may not be ``student``.

    ``at`` is the sweep's instant, the clock read once the tutor row was held
    ``FOR UPDATE`` (SPEC §a.4b): every grant it ends was committed before that, so
    ``revoked_at = at`` never precedes ``created_at`` (the 0049 CHECK). The
    transaction's ``now()`` can: an S9 that began after the sweep's transaction may
    commit before the lock is granted. Without ``at`` the revoke reads ``now()``.
    """
    if reason is GrantRevokeReason.student:
        raise ValueError("a student revokes through TutorGrantRepository.revoke, not a sweep")
    params: dict[str, object] = {
        "tutor_profile_id": tutor_profile_id,
        "reason": reason.value,
        "at": at,
    }
    only_student = ""
    if student_id is not None:
        only_student = " AND student_id = :student_id"
        params["student_id"] = student_id
    rows = session.execute(
        sa.text(
            "UPDATE tutor_data_grants "  # noqa: S608 - constant fragments
            "SET revoked_at = COALESCE(CAST(:at AS timestamptz), now()), "
            "revoke_reason = CAST(:reason AS grantrevokereason), "
            "updated_at = COALESCE(CAST(:at AS timestamptz), now()) "
            f"WHERE tutor_profile_id = :tutor_profile_id{only_student} AND revoked_at IS NULL "
            "RETURNING id"
        ),
        params,
    ).scalars()
    return sorted(_as_uuid(value) for value in rows)


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected a datetime, got {value!r}")
    return value


def _optional_instant(value: object) -> datetime | None:
    return None if value is None else _instant(value)


def _grant_row(row: Row[tuple[object, ...]]) -> GrantRow:
    mapping = row._mapping
    reason = mapping["revoke_reason"]
    return GrantRow(
        id=_as_uuid(mapping["id"]),
        student_id=_as_uuid(mapping["student_id"]),
        tutor_profile_id=_as_uuid(mapping["tutor_profile_id"]),
        scope=str(mapping["scope"]),
        created_at=_instant(mapping["created_at"]),
        expires_at=_optional_instant(mapping["expires_at"]),
        revoked_at=_optional_instant(mapping["revoked_at"]),
        revoke_reason=GrantRevokeReason(reason) if reason is not None else None,
    )


def _card(row: Row[tuple[object, ...]], subjects: tuple[SubjectRef, ...]) -> TutorCard:
    mapping = row._mapping
    modes: list[Mode] = [mode for mode in MODES if mapping[_MODE_COLUMN[mode]]]
    last_initial = mapping["public_last_initial"]
    return TutorCard(
        tutor_id=_as_uuid(mapping["tutor_profile_id"]),
        public_first_name=str(mapping["public_first_name"]),
        public_last_initial=None if last_initial is None else str(last_initial),
        headline=str(mapping["headline"]),
        subjects=subjects,
        modes=tuple(modes),
        area_code=str(mapping["area_code"]),
        rating_sum=int(mapping["rating_sum"]),
        rating_count=int(mapping["rating_count"]),
    )


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be 1 to {MAX_PAGE_SIZE}, got {limit}")


def _student_label(session: Session, student_id: uuid.UUID) -> str:
    display_name = session.execute(
        sa.text("SELECT display_name FROM users WHERE id = :student_id"),
        {"student_id": student_id},
    ).scalar_one_or_none()
    return student_label(None if display_name is None else str(display_name), student_id)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TutorGrantRepository:
    """Grants and the tutor access audit over a ``sessionmaker``; one transaction per call."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker
        self._parents = ParentLinkService(sessionmaker)

    revoke_live_in_session = staticmethod(revoke_live_in_session)
    student_shared_in_session = staticmethod(student_shared_in_session)

    # -- S9, S10 -----------------------------------------------------------------

    def create(self, student_id: uuid.UUID, tutor_profile_id: uuid.UUID) -> GrantCreated:
        """S9: grant the tutor access, or return the live grant (``created`` false).

        Raises (all :class:`TutorNotFound`, one ``not_found`` code, O11):
            TutorNotFound: no profile has this id.
            TutorNotListed: the tutor is not listed, or is paused.
            TutorBlocked: an active block exists between the pair.
        """
        with self._sessionmaker.begin() as session:
            tutor = session.execute(
                sa.text(
                    "SELECT tp.user_id, tp.public_first_name, tp.public_last_initial, "  # noqa: S608
                    f"{listed_and_not_paused_sql('tp')} AS visible "
                    "FROM tutor_profiles tp WHERE tp.id = :tutor_profile_id FOR SHARE OF tp"
                ),
                {"tutor_profile_id": tutor_profile_id},
            ).first()
            if tutor is None:
                raise TutorNotFound("No tutor has this id.")
            if not tutor._mapping["visible"]:
                raise TutorNotListed("This tutor is not taking new students.")
            tutor_user_id = _as_uuid(tutor._mapping["user_id"])
            # §a.4b step 2 before step 3: the grant insert references the student.
            _key_share_student(session, student_id)
            lock_pair_in_session(session, student_id=student_id, tutor_profile_id=tutor_profile_id)
            # After the locks: a block committed before them is visible to this statement.
            blocked = session.execute(
                sa.text(f"SELECT {active_block_between_sql(':student_id', ':tutor_user_id')}"),
                {"student_id": student_id, "tutor_user_id": tutor_user_id},
            ).scalar_one()
            if blocked:
                raise TutorBlocked("An active block exists between the student and the tutor.")
            existing = self._live_grant(session, student_id, tutor_profile_id)
            created = existing is None
            grant = (
                existing
                if existing is not None
                else self._insert(session, student_id, tutor_profile_id)
            )
            if grant is None:  # the unique index answered first: return the live grant
                created = False
                grant = self._live_grant(session, student_id, tutor_profile_id)
            if grant is None:  # pragma: no cover - the index guarantees a live row here
                raise RuntimeError("no live grant after a unique violation on the live index")
            first_name = str(tutor._mapping["public_first_name"])
            initial = tutor._mapping["public_last_initial"]
            last_initial = None if initial is None else str(initial)
            parents = tuple(self._parents.linked_parent_ids_in_session(session, student_id))
            if created:
                for parent_id in parents:
                    enqueue_in_session(
                        session,
                        recipient_user_id=parent_id,
                        template=GRANT_EMAIL_TEMPLATE,
                        context={
                            "tutor_first_name": first_name,
                            "tutor_last_initial": last_initial,
                            "grant_id": str(grant.id),
                            "child_id": str(student_id),
                        },
                        dedupe_key=f"grant:{grant.id}:created:{parent_id}",
                    )
            notice = GrantNoticeFacts(
                tutor_user_id=tutor_user_id,
                tutor_name=public_name(first_name, last_initial),
                student_label=_student_label(session, student_id),
                linked_parent_ids=parents,
            )
        if created:
            log.info("tutor_grant_created", grant_id=str(grant.id))
        return GrantCreated(grant=grant, created=created, notice=notice)

    def revoke(self, student_id: uuid.UUID, grant_id: uuid.UUID) -> GrantRevoked:
        """S10: end the caller's own grant; a repeat returns it unchanged.

        Raises:
            GrantNotFound: the grant is not this student's (or does not exist).
        """
        with self._sessionmaker.begin() as session:
            owner = session.execute(
                sa.text(
                    "SELECT tutor_profile_id FROM tutor_data_grants "
                    "WHERE id = :grant_id AND student_id = :student_id"
                ),
                {"grant_id": grant_id, "student_id": student_id},
            ).scalar_one_or_none()
            if owner is None:
                raise GrantNotFound("No such grant.")
            tutor_profile_id = _as_uuid(owner)
            tutor = session.execute(
                sa.text(
                    "SELECT user_id, public_first_name, public_last_initial "
                    "FROM tutor_profiles WHERE id = :tutor_profile_id FOR SHARE"
                ),
                {"tutor_profile_id": tutor_profile_id},
            ).one()
            lock_pair_in_session(session, student_id=student_id, tutor_profile_id=tutor_profile_id)
            updated = session.execute(
                sa.text(
                    "UPDATE tutor_data_grants g SET revoked_at = now(), "  # noqa: S608 - constants
                    "revoke_reason = 'student', updated_at = now() "
                    "WHERE g.id = :grant_id AND g.student_id = :student_id "
                    f"AND g.revoked_at IS NULL RETURNING {_GRANT_COLUMNS}"
                ),
                {"grant_id": grant_id, "student_id": student_id},
            ).first()
            revoked_now = updated is not None
            grant = _grant_row(updated) if updated is not None else self._grant(session, grant_id)
            last_initial = tutor._mapping["public_last_initial"]
            notice = GrantNoticeFacts(
                tutor_user_id=_as_uuid(tutor._mapping["user_id"]),
                tutor_name=public_name(
                    str(tutor._mapping["public_first_name"]),
                    None if last_initial is None else str(last_initial),
                ),
                student_label=_student_label(session, student_id),
                linked_parent_ids=(),
            )
        if revoked_now:
            log.info("tutor_grant_revoked", grant_id=str(grant_id))
        return GrantRevoked(grant=grant, revoked_now=revoked_now, notice=notice)

    # -- T20, T19: the gate and the audit ------------------------------------------

    def require_valid_grant(
        self, caller_profile_id: uuid.UUID, student_id: uuid.UUID
    ) -> GrantAccess:
        """T20's gate: check the caller's grant and record the read, before any data loads.

        ``caller_profile_id`` must be the caller's own profile, resolved from
        ``auth.user_id`` (O18). Returns once the ``detail`` audit row has committed.

        Raises:
            NoGrant: no grant ever existed for this profile and this id (404).
            AccessEnded: one existed and is not valid now (403, one code, SC-11).
            AuditUnavailable: the transaction failed; nothing may be read (500).
        """
        try:
            with self._sessionmaker.begin() as session:
                tutor = session.execute(
                    sa.text(
                        "SELECT public_first_name, public_last_initial FROM tutor_profiles "
                        "WHERE id = :caller FOR SHARE"
                    ),
                    {"caller": caller_profile_id},
                ).first()
                if tutor is None:
                    raise NoGrant("No grant for this student.")
                # §a.4b step 2, before the grant row: the audit insert references the student.
                _key_share_student(session, student_id)
                # Waits for a revoke still in flight on the live row; after it commits the
                # row no longer matches ``revoked_at IS NULL`` and nothing is locked.
                live = session.execute(
                    sa.text(
                        "SELECT id FROM tutor_data_grants WHERE tutor_profile_id = :caller "
                        "AND student_id = :student_id AND revoked_at IS NULL FOR SHARE"
                    ),
                    {"caller": caller_profile_id, "student_id": student_id},
                ).scalar_one_or_none()
                if live is None:
                    self._raise_without_live_grant(session, caller_profile_id, student_id)
                checked = session.execute(
                    sa.text(
                        f"SELECT {_GRANT_COLUMNS}, {grant_valid_sql('g', 'tp')} AS valid "  # noqa: S608
                        "FROM tutor_data_grants g JOIN tutor_profiles tp "
                        "ON tp.id = g.tutor_profile_id WHERE g.id = :grant_id"
                    ),
                    {"grant_id": live},
                ).one()
                if not checked._mapping["valid"]:
                    raise AccessEnded("This grant is no longer valid.")
                grant = _grant_row(checked)
                last_initial = tutor._mapping["public_last_initial"]
                accessed_at = session.execute(
                    sa.text(
                        "INSERT INTO tutor_access_audit "
                        "(grant_id, student_id, tutor_profile_id, tutor_public_name, action) "
                        "VALUES (:grant_id, :student_id, :caller, :tutor_name, "
                        "CAST('detail' AS tutoraccessaction)) RETURNING accessed_at"
                    ),
                    {
                        "grant_id": grant.id,
                        "student_id": student_id,
                        "caller": caller_profile_id,
                        "tutor_name": public_name(
                            str(tutor._mapping["public_first_name"]),
                            None if last_initial is None else str(last_initial),
                        ),
                    },
                ).scalar_one()
                label = _student_label(session, student_id)
        except SQLAlchemyError as exc:
            raise AuditUnavailable("The access log could not record this read.") from exc
        return GrantAccess(grant=grant, accessed_at=_instant(accessed_at), student_label=label)

    def students_page(
        self, caller_profile_id: uuid.UUID, cursor: TutorStudentKey | None, limit: int
    ) -> TutorStudentsPage:
        """T19: one page of the caller's students with a valid grant, newest grant first.

        Writes one ``list`` audit row per student on the page, then reads their
        labels and upcoming-session counts: three statements whatever the page size
        (one when the page is empty).

        Raises:
            AuditUnavailable: the transaction failed; nothing may be shown (500).
        """
        _check_limit(limit)
        params: dict[str, object] = {"caller": caller_profile_id, "limit": limit + 1}
        after = ""
        if cursor is not None:
            after = (
                " AND (g.created_at < :after_at OR (g.created_at = :after_at AND g.id > :after_id))"
            )
            params["after_at"] = cursor.granted_at
            params["after_id"] = cursor.grant_id
        try:
            with self._sessionmaker.begin() as session:
                rows = session.execute(
                    sa.text(
                        "SELECT g.id, g.student_id, g.created_at, tp.public_first_name, "  # noqa: S608
                        "tp.public_last_initial FROM tutor_data_grants g "
                        "JOIN tutor_profiles tp ON tp.id = g.tutor_profile_id "
                        "WHERE g.tutor_profile_id = :caller "
                        f"AND {grant_valid_sql('g', 'tp')}{after} "
                        "ORDER BY g.created_at DESC, g.id ASC LIMIT :limit"
                    ),
                    params,
                ).all()
                page = rows[:limit]
                if not page:
                    return TutorStudentsPage(items=(), next_key=None)
                grant_ids = [_as_uuid(row._mapping["id"]) for row in page]
                student_ids = [_as_uuid(row._mapping["student_id"]) for row in page]
                initial = page[0]._mapping["public_last_initial"]
                session.execute(
                    sa.text(
                        "INSERT INTO tutor_access_audit "
                        "(grant_id, student_id, tutor_profile_id, tutor_public_name, action) "
                        "SELECT u.grant_id, u.student_id, :caller, :tutor_name, "
                        "CAST('list' AS tutoraccessaction) "
                        "FROM unnest(CAST(:grant_ids AS uuid[]), CAST(:student_ids AS uuid[])) "
                        "AS u(grant_id, student_id)"
                    ),
                    {
                        "caller": caller_profile_id,
                        "tutor_name": public_name(
                            str(page[0]._mapping["public_first_name"]),
                            None if initial is None else str(initial),
                        ),
                        "grant_ids": grant_ids,
                        "student_ids": student_ids,
                    },
                )
                # Only after the audit rows: the names and the session counts.
                details = {
                    _as_uuid(row._mapping["id"]): row._mapping
                    for row in session.execute(
                        sa.text(
                            "SELECT u.id, u.display_name, (SELECT count(*) FROM tutor_bookings b "  # noqa: S608
                            "WHERE b.tutor_profile_id = :caller AND b.student_id = u.id "
                            f"AND {EFFECTIVE_STATE_SQL['accepted']}) AS upcoming "
                            "FROM users u WHERE u.id = ANY(CAST(:student_ids AS uuid[]))"
                        ),
                        {"caller": caller_profile_id, "student_ids": student_ids},
                    )
                }
        except SQLAlchemyError as exc:
            raise AuditUnavailable("The access log could not record this read.") from exc
        items = tuple(
            TutorStudentItem(
                student_id=student,
                display_name=student_label(
                    _optional_text(details[student]["display_name"]), student
                ),
                grant_id=grant_id,
                granted_at=_instant(row._mapping["created_at"]),
                upcoming_sessions=int(details[student]["upcoming"]),
            )
            for row, grant_id, student in zip(page, grant_ids, student_ids, strict=True)
        )
        next_key = (
            TutorStudentKey(granted_at=items[-1].granted_at, grant_id=items[-1].grant_id)
            if len(rows) > limit
            else None
        )
        return TutorStudentsPage(items=items, next_key=next_key)

    # -- S8, PA6, S11, PA7, studentShared ------------------------------------------

    def grants_for_student(
        self, student_id: uuid.UUID, *, include_classes: bool = True
    ) -> list[GrantView]:
        """S8/PA6: the student's grants, live first, then ended, newest first (at most 200).

        ``include_classes`` adds the student's classes each tutor also teaches (S8
        only: PA6 shows a parent none, SPEC §b.3).
        """
        with self._sessionmaker() as session:
            return self._views(session, student_id, None, include_classes=include_classes)

    def grant_view(self, student_id: uuid.UUID, grant_id: uuid.UUID) -> GrantView | None:
        """One of the student's grants as S8 shows it, or ``None`` if it is not theirs."""
        with self._sessionmaker() as session:
            views = self._views(session, student_id, grant_id, include_classes=True)
        return views[0] if views else None

    def access_log_page(
        self,
        student_id: uuid.UUID,
        *,
        tutor_id: uuid.UUID | None,
        cursor: AccessLogKey | None,
        limit: int,
    ) -> AccessLogPage:
        """S11/PA7: the student's access log, newest first; one statement."""
        _check_limit(limit)
        params: dict[str, object] = {"student_id": student_id, "limit": limit + 1}
        filters = ""
        if tutor_id is not None:
            filters += " AND a.tutor_profile_id = :tutor_id"
            params["tutor_id"] = tutor_id
        if cursor is not None:
            filters += (
                " AND (a.accessed_at < :after_at "
                "OR (a.accessed_at = :after_at AND a.id < :after_id))"
            )
            params["after_at"] = cursor.accessed_at
            params["after_id"] = cursor.entry_id
        with self._sessionmaker() as session:
            rows = session.execute(
                sa.text(
                    "SELECT a.id, a.tutor_profile_id, a.tutor_public_name, "  # noqa: S608
                    "a.action::text AS action, a.accessed_at FROM tutor_access_audit a "
                    f"WHERE a.student_id = :student_id{filters} "
                    "ORDER BY a.accessed_at DESC, a.id DESC LIMIT :limit"
                ),
                params,
            ).all()
        page = rows[:limit]
        items = tuple(
            AccessLogEntry(
                tutor_profile_id=(
                    None
                    if row._mapping["tutor_profile_id"] is None
                    else _as_uuid(row._mapping["tutor_profile_id"])
                ),
                tutor_name=str(row._mapping["tutor_public_name"]),
                action="list" if row._mapping["action"] == "list" else "detail",
                accessed_at=_instant(row._mapping["accessed_at"]),
            )
            for row in page
        )
        next_key = (
            AccessLogKey(
                accessed_at=_instant(page[-1]._mapping["accessed_at"]),
                entry_id=_as_uuid(page[-1]._mapping["id"]),
            )
            if len(rows) > limit
            else None
        )
        return AccessLogPage(items=items, next_key=next_key)

    def student_shared(
        self, tutor_profile_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
    ) -> set[uuid.UUID]:
        """``studentShared`` for a page of bookings: the grant predicate, no audit row (F13)."""
        if not student_ids:
            return set()
        with self._sessionmaker() as session:
            return student_shared_in_session(session, tutor_profile_id, student_ids)

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _live_grant(
        session: Session, student_id: uuid.UUID, tutor_profile_id: uuid.UUID
    ) -> GrantRow | None:
        row = session.execute(
            sa.text(
                f"SELECT {_GRANT_COLUMNS} FROM tutor_data_grants g "  # noqa: S608 - constants
                "WHERE g.student_id = :student_id AND g.tutor_profile_id = :tutor_profile_id "
                "AND g.revoked_at IS NULL"
            ),
            {"student_id": student_id, "tutor_profile_id": tutor_profile_id},
        ).first()
        return _grant_row(row) if row is not None else None

    @staticmethod
    def _grant(session: Session, grant_id: uuid.UUID) -> GrantRow:
        row = session.execute(
            sa.text(f"SELECT {_GRANT_COLUMNS} FROM tutor_data_grants g WHERE g.id = :grant_id"),  # noqa: S608
            {"grant_id": grant_id},
        ).one()
        return _grant_row(row)

    @staticmethod
    def _insert(
        session: Session, student_id: uuid.UUID, tutor_profile_id: uuid.UUID
    ) -> GrantRow | None:
        """Insert the grant; ``None`` when ``uq_tutor_data_grants_live`` already holds one."""
        try:
            with session.begin_nested():
                row = session.execute(
                    sa.text(
                        "INSERT INTO tutor_data_grants AS g (student_id, tutor_profile_id) "  # noqa: S608
                        f"VALUES (:student_id, :tutor_profile_id) RETURNING {_GRANT_COLUMNS}"
                    ),
                    {"student_id": student_id, "tutor_profile_id": tutor_profile_id},
                ).one()
        except IntegrityError as exc:
            if _constraint(exc) != "uq_tutor_data_grants_live":
                raise
            return None
        return _grant_row(row)

    @staticmethod
    def _raise_without_live_grant(
        session: Session, caller_profile_id: uuid.UUID, student_id: uuid.UUID
    ) -> None:
        """No live grant: 403 if this profile ever had one for this student, else 404."""
        existed = session.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM tutor_data_grants "
                "WHERE tutor_profile_id = :caller AND student_id = :student_id)"
            ),
            {"caller": caller_profile_id, "student_id": student_id},
        ).scalar_one()
        if existed:
            raise AccessEnded("This grant is no longer valid.")
        raise NoGrant("No grant for this student.")

    @staticmethod
    def _views(
        session: Session,
        student_id: uuid.UUID,
        grant_id: uuid.UUID | None,
        *,
        include_classes: bool,
    ) -> list[GrantView]:
        params: dict[str, object] = {"student_id": student_id, "limit": MAX_GRANTS_LISTED}
        only = ""
        if grant_id is not None:
            only = " AND g.id = :grant_id"
            params["grant_id"] = grant_id
        rows = session.execute(
            sa.text(
                f"SELECT {_GRANT_COLUMNS}, {_CARD_COLUMNS}, tp.user_id AS tutor_user_id, "  # noqa: S608
                "tp.listing_state::text AS listing_state, "
                f"{active_block_between_sql('g.student_id', 'tp.user_id')} AS blocked, "
                f"{student_block_of_tutor_created_at_sql('g.student_id', 'tp.user_id')} "
                "AS student_blocked_at, now() AS db_now FROM tutor_data_grants g "
                "JOIN tutor_profiles tp ON tp.id = g.tutor_profile_id "
                f"WHERE g.student_id = :student_id{only} "
                "ORDER BY (g.revoked_at IS NULL) DESC, g.created_at DESC, g.id DESC LIMIT :limit"
            ),
            params,
        ).all()
        if not rows:
            return []
        tutor_ids = list(dict.fromkeys(_as_uuid(row._mapping["tutor_profile_id"]) for row in rows))
        subjects = subjects_by_tutor(session, tutor_ids)
        classes: dict[uuid.UUID, list[str]] = {}
        if include_classes:
            tutor_users = list({_as_uuid(row._mapping["tutor_user_id"]) for row in rows})
            for teacher_id, name in session.execute(
                sa.text(
                    "SELECT c.teacher_id, c.name FROM class_enrollments e "
                    "JOIN classes c ON c.id = e.class_id WHERE e.student_id = :student_id "
                    "AND c.teacher_id = ANY(CAST(:teachers AS uuid[])) ORDER BY c.name, c.id"
                ),
                {"student_id": student_id, "teachers": tutor_users},
            ).all():
                classes.setdefault(_as_uuid(teacher_id), []).append(str(name))
        views: list[GrantView] = []
        for row in rows:
            grant = _grant_row(row)
            mapping = row._mapping
            facts = GrantFacts(
                created_at=grant.created_at,
                revoked_at=grant.revoked_at,
                revoke_reason=grant.revoke_reason.value if grant.revoke_reason else None,
                expires_at=grant.expires_at,
                tutor_listing_state=str(mapping["listing_state"]),
                blocked=bool(mapping["blocked"]),
            )
            views.append(
                GrantView(
                    grant=grant,
                    tutor=_card(row, subjects.get(grant.tutor_profile_id, ())),
                    status=grant_status_for_student(
                        facts,
                        now=_instant(mapping["db_now"]),
                        student_blocked_at=_optional_instant(mapping["student_blocked_at"]),
                    ),
                    also_teaches_classes=tuple(classes.get(_as_uuid(mapping["tutor_user_id"]), ())),
                )
            )
        return views


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else None


__all__ = [
    "GRANT_EMAIL_TEMPLATE",
    "MAX_GRANTS_LISTED",
    "MAX_PAGE_SIZE",
    "AccessEnded",
    "AccessLogEntry",
    "AccessLogKey",
    "AccessLogPage",
    "AuditUnavailable",
    "GrantAccess",
    "GrantCreated",
    "GrantError",
    "GrantNotFound",
    "GrantNoticeFacts",
    "GrantRevoked",
    "GrantRow",
    "GrantView",
    "NoGrant",
    "TutorBlocked",
    "TutorGrantRepository",
    "TutorNotFound",
    "TutorNotListed",
    "TutorStudentItem",
    "TutorStudentKey",
    "TutorStudentsPage",
    "access_log_cursor",
    "grant_valid_sql",
    "parse_access_log_cursor",
    "parse_tutor_students_cursor",
    "revoke_live_in_session",
    "student_shared_in_session",
    "tutor_students_cursor",
]
