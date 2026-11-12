"""The class-scoped history store that hides an unshared paper (D9).

Layered strictly on top of :class:`~lemely.db.history_repo.DbHistoryStore`'s
already-soft-delete-filtered view (Task 3's loader criterion) — this module
never re-applies deletion filtering, it only adds one more, per-class layer
on top: papers the student's teacher has unshared from *this* class's view.

A wrapper rather than a parameter on
:class:`~lemely.core.history.HistoryStoreProtocol`: that protocol is also
satisfied by the JSON file store, where a class id is meaningless. Constructed
**only** in :mod:`lemely.web.routers.classes`, which is what keeps the
student's own surfaces (self-review, progress, at-risk) structurally unable
to see a class's exclusions — they depend on the unwrapped store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.history import PaperRecord, StudentHistory

if TYPE_CHECKING:
    from lemely.core.history import HistoryStoreProtocol
    from lemely.db.class_repo import RosterEntry


class ClassScopedHistoryStore:
    """A history store that hides papers unshared from one class (D9).

    The exclusion set is fetched once per class request (by the caller, via
    :class:`~lemely.db.class_exclusion_repo.ClassExclusionRepository`) and
    handed in whole — never re-fetched per student.
    """

    def __init__(
        self,
        inner: HistoryStoreProtocol,
        excluded_attempt_ids: frozenset[str],
    ) -> None:
        self._inner = inner
        self._excluded = excluded_attempt_ids

    def load(self, student_id: str) -> StudentHistory:
        """The student's history minus anything unshared from this class."""
        history = self._inner.load(student_id)
        if not self._excluded:
            return history
        kept = [
            record
            for record in history.records
            # A record with no attempt_id came from the file store and cannot
            # be addressed by an exclusion; pass it through rather than guess.
            if record.attempt_id is None or record.attempt_id not in self._excluded
        ]
        return StudentHistory(student_id=history.student_id, records=kept)

    def append(self, student_id: str, record: PaperRecord) -> None:
        """Delegate; a class view never writes, but the protocol requires it."""
        self._inner.append(student_id, record)

    def list_students(self) -> list[str]:
        """Delegate unchanged — exclusions hide papers, never students."""
        return self._inner.list_students()


def load_roster_histories(
    store: HistoryStoreProtocol, roster: list[RosterEntry]
) -> list[tuple[RosterEntry, StudentHistory]]:
    """Load each roster entry's history, paired with the entry it came from.

    The single helper that replaces the three duplicated roster-history
    comprehensions in :mod:`lemely.web.routers.classes` — one load per
    student, in roster order, whatever ``store`` is (the raw store, or a
    :class:`ClassScopedHistoryStore` built for one class).
    """
    return [(entry, store.load(str(entry.student_id))) for entry in roster]


__all__ = ["ClassScopedHistoryStore", "load_roster_histories"]
