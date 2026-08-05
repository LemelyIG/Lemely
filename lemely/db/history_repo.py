"""Postgres-backed replacement for the JSON :class:`HistoryStore`.

``DbHistoryStore`` preserves the exact surface the JSON store exposed
(:meth:`load`, :meth:`append`, :meth:`list_students`) so every downstream
consumer of :class:`~lemely.core.history.StudentHistory` /
:class:`~lemely.core.history.PaperRecord` keeps working unchanged — only the
storage backend moves from ``{root}/{id}.json`` files to the relational
``attempts`` / ``weakness_records`` tables (decision D1.8).

A :class:`~lemely.core.history.PaperRecord` maps to a single
:class:`~lemely.db.models.attempts.Attempt` row plus one
:class:`~lemely.db.models.attempts.WeaknessRecord` per ``weak_area``.
:meth:`load` reconstructs the ``PaperRecord`` list from those rows. See D1.8 for
the field-by-field mapping and the resolved impedance mismatches (``student_id``
str → ``user_id`` UUID FK, month label ↔ enum, ISO string ↔ tz-aware datetime).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import SESSION_MONTH_LABELS, SessionMonth

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

# Inverse of SESSION_MONTH_LABELS: the display label carried by ExamMetadata
# ("May/June") back to its SessionMonth enum member.
_MONTH_TO_ENUM: dict[str, SessionMonth] = {
    label: member for member, label in SESSION_MONTH_LABELS.items()
}


class DbHistoryStore:
    """Relational store of student paper history (drop-in for ``HistoryStore``)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Bind the store to a ``sessionmaker`` (each op runs one transaction)."""
        self._sm = session_factory

    def append(self, student_id: str, record: PaperRecord) -> None:
        """Persist a :class:`PaperRecord` as one ``Attempt`` (+ weakness rows).

        Args:
            student_id: The owning user's id — must be a UUID string that already
                exists in ``users`` (the FK is enforced; see D1.8).
            record: The paper record to persist.

        Raises:
            ValueError: ``student_id`` is not a valid UUID, or ``session_month``
                is not a recognised CAIE label.
        """
        user_id = parse_user_id(student_id)
        attempt = self._to_attempt(user_id, record)
        with self._sm.begin() as session:
            session.add(attempt)

    def load(self, student_id: str) -> StudentHistory:
        """Return the student's history in ``recorded_at`` order.

        A user with no attempts yields an empty :class:`StudentHistory` — the same
        contract the JSON store gave a missing file.

        Raises:
            ValueError: ``student_id`` is not a valid UUID string.
        """
        user_id = parse_user_id(student_id)
        stmt = (
            select(Attempt)
            .where(Attempt.user_id == user_id)
            .order_by(Attempt.recorded_at, Attempt.created_at, Attempt.id)
        )
        with self._sm() as session:
            attempts = session.scalars(stmt).all()
            records = [_to_record(student_id, a) for a in attempts]
        return StudentHistory(student_id=student_id, records=records)

    def list_students(self) -> list[str]:
        """Return the distinct ids of all users that have any attempt on record."""
        stmt = select(Attempt.user_id).distinct()
        with self._sm() as session:
            return sorted(str(uid) for uid in session.scalars(stmt).all())

    def _to_attempt(self, user_id: uuid.UUID, record: PaperRecord) -> Attempt:
        meta = record.metadata
        attempt = Attempt(
            user_id=user_id,
            subject_code=meta.subject_code,
            session_month=month_to_enum(meta.session_month),
            session_year=meta.session_year,
            paper_number=meta.paper_number,
            paper_variant=meta.paper_variant,
            awarded_marks=record.awarded_marks,
            maximum_marks=record.maximum_marks,
            percentage=record.percentage,
            grade=record.grade,
            recorded_at=_parse_recorded_at(record.recorded_at),
        )
        attempt.weakness_records = [
            WeaknessRecord(
                user_id=user_id,
                topic=wa.topic,
                lost_marks=wa.lost_marks,
                maximum_marks=wa.maximum_marks,
                accuracy=wa.accuracy,
                question_ids=list(wa.question_ids),
            )
            for wa in record.weak_areas
        ]
        return attempt


def parse_user_id(student_id: str) -> uuid.UUID:
    """Parse a student/user id string into a UUID, or raise ``ValueError``.

    Public so the DB-backed persistence repos (history + attempt) share one
    canonical id-validation contract with an identical error message.
    """
    try:
        return uuid.UUID(student_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(
            f"student_id must be a UUID for the DB history store, got {student_id!r}"
        ) from exc


def month_to_enum(label: str) -> SessionMonth:
    """Map a CAIE display label ("May/June") to its :class:`SessionMonth` member.

    Public so the attempt repo can reuse the same label→enum mapping the history
    store uses; raises ``ValueError`` on an unrecognised label.
    """
    try:
        return _MONTH_TO_ENUM[label]
    except KeyError as exc:
        raise ValueError(f"Unknown CAIE session-month label: {label!r}") from exc


def _parse_recorded_at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _to_record(student_id: str, attempt: Attempt) -> PaperRecord:
    # weak_areas sorted by topic for a deterministic, backend-independent order
    # (the JSON store preserved append order, which is not semantically meaningful
    # for the aggregation code that consumes these; see D1.8).
    weak_areas = [
        WeakArea(
            topic=wr.topic,
            lost_marks=wr.lost_marks,
            maximum_marks=wr.maximum_marks,
            accuracy=wr.accuracy,
            question_ids=list(wr.question_ids),
        )
        for wr in sorted(attempt.weakness_records, key=lambda wr: wr.topic)
    ]
    return PaperRecord(
        student_id=student_id,
        metadata=ExamMetadata(
            subject_code=attempt.subject_code or "",
            paper_number=attempt.paper_number or 1,
            paper_variant=attempt.paper_variant or 1,
            session_month=SESSION_MONTH_LABELS[attempt.session_month]
            if attempt.session_month is not None
            else "Specimen",
            session_year=attempt.session_year,
        ),
        awarded_marks=attempt.awarded_marks,
        maximum_marks=attempt.maximum_marks,
        percentage=attempt.percentage,
        grade=attempt.grade or "",
        weak_areas=weak_areas,
        recorded_at=attempt.recorded_at.isoformat(),
    )


def migrate_json_history(
    json_store: object,
    db_store: DbHistoryStore,
) -> dict[str, str]:
    """Copy every JSON student history into the DB store.

    Walks ``json_store.list_students()`` and re-appends each ``PaperRecord``
    through ``db_store``. Returns a ``{student_id: outcome}`` map so
    unmigratable legacy keys (non-UUID ids, missing users) are surfaced rather
    than silently dropped (D1.8).

    ``json_store`` is typed ``object`` to avoid importing the ``io`` layer here;
    it must expose ``list_students()`` and ``load(id) -> StudentHistory``.
    """
    results: dict[str, str] = {}
    for student_id in json_store.list_students():  # type: ignore[attr-defined]
        history = json_store.load(student_id)  # type: ignore[attr-defined]
        try:
            for record in history.records:
                db_store.append(student_id, record)
        except Exception as exc:  # report per key, don't abort the whole batch
            results[student_id] = f"skipped: {exc}"
            log.warning("history_migration_skipped", student_id=student_id, error=str(exc))
            continue
        results[student_id] = f"migrated {len(history.records)} record(s)"
    return results


__all__ = [
    "DbHistoryStore",
    "migrate_json_history",
    "month_to_enum",
    "parse_user_id",
]
