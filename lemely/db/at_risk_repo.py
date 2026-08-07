"""At-risk flag acknowledgement persistence (D3.5, T-06's "dismiss/acknowledge").

At-risk flags are derived, not stored — :func:`lemely.core.at_risk.assess_at_risk`
recomputes them from a student's history on every request (D3.3), so there is
no flag *row* an acknowledgement could reference by id. This module owns the
one durable fact the acknowledge-with-a-note action needs: which
``(teacher, student, reason)`` triples have been acked, against which
evidence identity (:func:`lemely.core.at_risk.flag_fingerprint`), with an
optional teacher-facing note.

**A standalone module (mirroring** :mod:`lemely.db.review_repo` **'s shape),
not a method bolted onto** :class:`~lemely.db.class_repo.ClassService` **or**
:class:`~lemely.db.review_repo.ReviewService`. Acknowledgement is its own
coherent read/write surface — its own table, its own tenancy composition
over :class:`ClassService`, its own error hierarchy — and has nothing to do
with class roster CRUD or the review queue's grading-correction concerns;
folding it into either would make an unrelated service responsible for a
third domain concept.

**Tenancy** is the identical roster-union rule every other student-scoped
teacher mutation in this codebase already enforces (D3.1): every write
composes the same two :class:`~lemely.db.class_repo.ClassService` calls
(``list_classes`` + ``roster``) :class:`~lemely.db.review_repo.ReviewService`
composes, so "which students may this caller touch" can never be defined
twice, differently. Acknowledging or un-acknowledging a flag for a student
outside that union is an :class:`AtRiskAckOwnershipError` (403), matching
``ReviewOwnershipError``/``ClassOwnershipError`` to the letter.

**What this module deliberately does NOT do: decide whether a reason is
*currently firing* for a student.** That question needs the core rules
engine (``assess_at_risk``) run over the student's real history, which needs
a ``HistoryStoreProtocol`` — a dependency this module does not carry (unlike
``ReviewService``, which genuinely owns ``Attempt``/``QuestionResult`` writes
and a ``GradeBoundaryStore``). ``lemely.web.routers.teacher`` already
assembles ``HistoryStoreProtocol`` + ``ClassService`` + ``assess_at_risk``
for every other at-risk route (the overview, student detail, the at-risk
list); the "is this evidence still live, and what is its fingerprint"
judgement belongs there, and this module only ever persists the fingerprint
string it is handed. Keeping that judgement out of this module is also what
keeps :func:`~lemely.core.at_risk.flag_fingerprint` single-sourced — this
layer never re-derives or second-guesses it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from lemely.db.models.ops import AtRiskAcknowledgement

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.at_risk import AtRiskReason
    from lemely.db.class_repo import ClassService
    from lemely.db.models.enums import Role


class AtRiskAckError(Exception):
    """Base class for at-risk-acknowledgement failures."""


class AtRiskAckOwnershipError(AtRiskAckError):
    """The caller may not acknowledge/un-acknowledge flags for this student (-> 403)."""


@dataclass(frozen=True, slots=True)
class AtRiskAcknowledgementRow:
    """One stored acknowledgement, detached from its ORM session.

    ``acknowledged_by`` is always the row's own ``teacher_id`` — acks are
    per-teacher by construction (D3.5), so "who" never needs resolving
    against a different identity. ``acknowledged_at`` is the row's
    ``updated_at`` (from :class:`~lemely.db.models.enums.TimestampMixin`):
    since a re-acknowledgement upserts the same row (see
    :meth:`AtRiskAckService.acknowledge`), ``updated_at`` is always the most
    recent time this exact ``(teacher, student, reason)`` triple was acked,
    which is what "when" means to the teacher reading it back.
    """

    student_id: uuid.UUID
    reason: AtRiskReason
    evidence_fingerprint: str
    note: str | None
    acknowledged_by: uuid.UUID
    acknowledged_at: datetime


class AtRiskAckService:
    """Acknowledge / un-acknowledge / bulk-read at-risk flag acks (D3.5).

    Constructed with a ``sessionmaker`` and the same
    :class:`~lemely.db.class_repo.ClassService` instance the caller's other
    student-scoped services use, so tenancy composes identically everywhere
    (D3.1) — there is no super-role bypass (``platform_admin`` sees no
    classes via ``ClassService``, so every write is always out-of-scope for
    them too).
    """

    def __init__(self, sessionmaker: sessionmaker[Session], class_service: ClassService) -> None:
        """Wire the service to its collaborators (mirrors ``ReviewService``)."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service

    # -- Mutations --------------------------------------------------------------

    def acknowledge(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        student_id: uuid.UUID | str,
        reason: AtRiskReason,
        evidence_fingerprint: str,
        note: str | None = None,
    ) -> AtRiskAcknowledgementRow:
        """Upsert an acknowledgement for ``(caller, student, reason)``.

        A second call for the same triple **overwrites** ``evidence_fingerprint``
        and ``note`` in place rather than creating a second row — the unique
        constraint on ``(teacher_id, student_id, reason)`` is exactly this
        upsert key. The caller (``lemely.web.routers.teacher``) is
        responsible for having already confirmed ``reason`` is a rule
        currently firing for this student and for supplying that flag's
        *current* ``evidence_fingerprint`` — see the module docstring for why
        that judgement does not live here.

        Raises:
            AtRiskAckOwnershipError: ``student_id`` is not enrolled in any
                class the caller owns/administers (403) — checked before any
                write, identically to every other student-scoped mutation in
                this codebase (D3.1).
        """
        teacher_uuid = _as_uuid(caller_id)
        student_uuid = _as_uuid(student_id)
        self._assert_visible(caller_id, caller_role, student_uuid)
        with self._sessionmaker() as session, session.begin():
            existing = session.scalars(
                select(AtRiskAcknowledgement).where(
                    AtRiskAcknowledgement.teacher_id == teacher_uuid,
                    AtRiskAcknowledgement.student_id == student_uuid,
                    AtRiskAcknowledgement.reason == reason,
                )
            ).one_or_none()
            if existing is None:
                existing = AtRiskAcknowledgement(
                    teacher_id=teacher_uuid,
                    student_id=student_uuid,
                    reason=reason,
                )
                session.add(existing)
            existing.evidence_fingerprint = evidence_fingerprint
            existing.note = note
            session.flush()
            return _to_row(existing)

    def unacknowledge(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        student_id: uuid.UUID | str,
        reason: AtRiskReason,
    ) -> None:
        """Remove an acknowledgement, if one exists. Idempotent.

        Mirrors :meth:`~lemely.db.class_repo.ClassService.remove_student`:
        un-acknowledging a reason that was never acked is a no-op, not a 404
        — there is nothing wrong with a caller un-acking a flag they never
        acked (e.g. a stale UI retry).

        Raises:
            AtRiskAckOwnershipError: ``student_id`` is outside the caller's
                scope (403).
        """
        teacher_uuid = _as_uuid(caller_id)
        student_uuid = _as_uuid(student_id)
        self._assert_visible(caller_id, caller_role, student_uuid)
        with self._sessionmaker() as session, session.begin():
            session.execute(
                delete(AtRiskAcknowledgement).where(
                    AtRiskAcknowledgement.teacher_id == teacher_uuid,
                    AtRiskAcknowledgement.student_id == student_uuid,
                    AtRiskAcknowledgement.reason == reason,
                )
            )

    # -- Reads --------------------------------------------------------------

    def load_for_teacher(
        self,
        teacher_id: uuid.UUID | str,
        *,
        student_ids: Sequence[uuid.UUID | str] | None = None,
    ) -> dict[tuple[uuid.UUID, AtRiskReason], AtRiskAcknowledgementRow]:
        """Return every ack this teacher has recorded, in one query.

        **No ownership check here.** Reading only ever returns rows keyed on
        the *caller's own* ``teacher_id`` — the write path
        (:meth:`acknowledge`) is what enforces who may create one — so there
        is no cross-tenant read to guard against: a row for a student who has
        since left the caller's classes is simply never looked up by a
        caller whose roster no longer includes that id (D3.5's per-teacher
        scoping means the row would not exist for any *other* teacher of that
        student anyway).

        ``student_ids`` narrows the query for a single-student read (T-05's
        student detail); omit it for the class-wide reads (T-01's overview,
        T-06's at-risk list) that need every ack in **one** round trip rather
        than one query per flag — the N+1 this signature exists to avoid.

        Returned keyed by ``(student_id, reason)`` so a caller can look up a
        specific flag's ack directly while converting every flag in a list.
        """
        teacher_uuid = _as_uuid(teacher_id)
        with self._sessionmaker() as session:
            stmt = select(AtRiskAcknowledgement).where(
                AtRiskAcknowledgement.teacher_id == teacher_uuid
            )
            if student_ids is not None:
                stmt = stmt.where(
                    AtRiskAcknowledgement.student_id.in_([_as_uuid(s) for s in student_ids])
                )
            rows = session.scalars(stmt).all()
            return {(row.student_id, row.reason): _to_row(row) for row in rows}

    # -- Internals --------------------------------------------------------------

    def _assert_visible(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        student_uuid: uuid.UUID,
    ) -> None:
        """Raise :class:`AtRiskAckOwnershipError` unless ``student_uuid`` is enrolled.

        Enrolled in a class the caller owns/administers, that is. Composes
        ``ClassService.list_classes``/``roster`` directly (the same
        two calls ``ReviewService._visible_class_map`` and
        ``lemely.web.routers.teacher._visible_students`` each compose) rather
        than importing either — this module has no dependency on the web
        layer, and duplicating the two-call composition here (instead of
        factoring a shared helper) matches ``ReviewService``'s own precedent
        of not reaching across services for it.
        """
        for row in self._class_service.list_classes(caller_id, caller_role):
            for entry in self._class_service.roster(caller_id, caller_role, row.class_id):
                if entry.student_id == student_uuid:
                    return
        raise AtRiskAckOwnershipError(
            f"Caller may not acknowledge flags for student {student_uuid}"
        )


def _to_row(ack: AtRiskAcknowledgement) -> AtRiskAcknowledgementRow:
    return AtRiskAcknowledgementRow(
        student_id=ack.student_id,
        reason=ack.reason,
        evidence_fingerprint=ack.evidence_fingerprint,
        note=ack.note,
        acknowledged_by=ack.teacher_id,
        acknowledged_at=ack.updated_at,
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
    "AtRiskAckError",
    "AtRiskAckOwnershipError",
    "AtRiskAckService",
    "AtRiskAcknowledgementRow",
]
