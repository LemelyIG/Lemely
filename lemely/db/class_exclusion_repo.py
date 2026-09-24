"""Read side of a class's per-paper unshare set (design §5, D9).

One narrow repository over :class:`~lemely.db.models.deletion.ClassPaperExclusion`
— read-only, as Task 12 only builds the class-scoped history *view*. Task 13
adds the unshare/reshare writes onto this same table.

Read by exactly one caller,
:mod:`lemely.web.routers.classes`, which uses the returned set to build a
:class:`~lemely.db.class_history.ClassScopedHistoryStore` once per class
request rather than once per student.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.models.deletion import ClassPaperExclusion

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session, sessionmaker


class ClassExclusionRepository:
    """Reads which attempts a class's teacher has unshared from its view."""

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


__all__ = ["ClassExclusionRepository"]
