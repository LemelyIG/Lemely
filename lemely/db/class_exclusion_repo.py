"""A class's per-paper unshare set (design §5, D9).

One narrow repository over :class:`~lemely.db.models.deletion.ClassPaperExclusion`:
the read Task 12's class-scoped history view needs, and the unshare/reshare
writes behind ``POST``/``DELETE /api/classes/{class_id}/papers/{attempt_id}/unshare``.

Called only from :mod:`lemely.web.routers.classes`. The read builds a
:class:`~lemely.db.class_history.ClassScopedHistoryStore` once per class
request rather than once per student; the writes are reached only after that
router's class-scope check has passed. The review queue reads the same table
directly (:meth:`lemely.db.review_repo.ReviewService.list_queue`, R3/R8), as a
filter — nothing here ever writes a review item.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.models.attempts import Attempt
from lemely.db.models.deletion import ClassPaperExclusion

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection

    from sqlalchemy.orm import Session, sessionmaker


class ExclusionTargetNotFoundError(Exception):
    """The attempt does not exist, is deleted, or is not a rostered student's (→ 404).

    One error for all three, so the route is not an oracle for attempt ids
    outside the class: a teacher learns nothing about a paper they could not
    already see.
    """


class ClassExclusionRepository:
    """Reads and writes which attempts a class's teacher has unshared from its view."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def excluded_attempt_ids(self, class_id: uuid.UUID) -> frozenset[str]:
        """The attempt ids unshared from ``class_id``, as strings (D9).

        Strings, not UUIDs: the only consumer,
        :class:`~lemely.db.class_history.ClassScopedHistoryStore`, compares
        against :attr:`~lemely.core.history.PaperRecord.attempt_id`, which is
        itself a string (or ``None`` for a file-store record) — matching that
        type here means the wrapper never converts on every ``load``.
        """
        stmt = select(ClassPaperExclusion.attempt_id).where(
            ClassPaperExclusion.class_id == class_id
        )
        with self._sessionmaker() as session:
            attempt_ids = session.scalars(stmt).all()
        return frozenset(str(attempt_id) for attempt_id in attempt_ids)

    def exclude(
        self,
        class_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        roster_student_ids: Collection[uuid.UUID],
        excluded_by: uuid.UUID,
    ) -> None:
        """Unshare ``attempt_id`` from ``class_id``. Idempotent.

        ``excluded_by`` is set on every insert: design §5 makes it the only
        trace that a teacher removed a (possibly flagged) paper from their own
        queue. A repeat unshare keeps the first row — and its ``excluded_by``
        and ``created_at`` — rather than rewriting who did it first.

        Raises:
            ExclusionTargetNotFoundError: See the class docstring. Checked
                before the insert, so an unknown id never reaches the FK.
        """
        with self._sessionmaker.begin() as session:
            _require_rostered_attempt(session, attempt_id, roster_student_ids)
            session.execute(
                pg_insert(ClassPaperExclusion)
                .values(class_id=class_id, attempt_id=attempt_id, excluded_by=excluded_by)
                .on_conflict_do_nothing(index_elements=["class_id", "attempt_id"])
            )

    def include(
        self,
        class_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        roster_student_ids: Collection[uuid.UUID],
    ) -> None:
        """Reshare ``attempt_id`` with ``class_id``. Idempotent.

        Validated exactly like :meth:`exclude`, so the two verbs answer the
        same question about the same ids identically.

        Raises:
            ExclusionTargetNotFoundError: See the class docstring.
        """
        with self._sessionmaker.begin() as session:
            _require_rostered_attempt(session, attempt_id, roster_student_ids)
            session.execute(
                delete(ClassPaperExclusion).where(
                    ClassPaperExclusion.class_id == class_id,
                    ClassPaperExclusion.attempt_id == attempt_id,
                )
            )


def _require_rostered_attempt(
    session: Session, attempt_id: uuid.UUID, roster_student_ids: Collection[uuid.UUID]
) -> None:
    """Raise unless ``attempt_id`` is a live attempt by one of ``roster_student_ids``.

    A soft-deleted attempt reads as absent here through the session's
    loader criterion (:mod:`lemely.db.session`), like everywhere else.
    """
    owner = session.scalar(select(Attempt.user_id).where(Attempt.id == attempt_id))
    if owner is None or owner not in roster_student_ids:
        raise ExclusionTargetNotFoundError(f"Unknown attempt: {attempt_id}")


__all__ = ["ClassExclusionRepository", "ExclusionTargetNotFoundError"]
