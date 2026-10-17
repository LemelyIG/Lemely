"""Tests for :class:`~lemely.db.class_history.ClassScopedHistoryStore` (T12, D9).

Pure unit tests against a fake in-memory inner store — no DB, no network.
``ClassExclusionRepository`` (the real source of the exclusion set) is a thin,
read-only SQL wrapper proven adequately by the class-route tests
(``tests/test_web_classes.py``) that exercise it through a real Postgres
database; this file proves the wrapper's filtering behaviour in isolation,
per the review-amended brief (``.superpowers/sdd-deletion/task-12-brief.md``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from lemely.core.history import HistoryStoreProtocol, PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db.class_history import ClassScopedHistoryStore, load_roster_histories
from lemely.db.class_repo import RosterEntry

STUDENT = "11111111-1111-1111-1111-111111111111"


def _record(attempt_id: str | None, grade: str = "B") -> PaperRecord:
    return PaperRecord(
        student_id=STUDENT,
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=65,
        maximum_marks=80,
        percentage=81.25,
        grade=grade,
        weak_areas=[
            WeakArea(
                topic="Waves", lost_marks=5, maximum_marks=10, accuracy=0.5, question_ids=["3a"]
            )
        ],
        recorded_at=datetime.now(UTC).isoformat(),
        attempt_id=attempt_id,
    )


class FakeHistoryStore:
    """A minimal :class:`HistoryStoreProtocol` double over an in-memory dict."""

    def __init__(self, histories: dict[str, StudentHistory]) -> None:
        self._histories = histories

    def load(self, student_id: str) -> StudentHistory:
        return self._histories.get(student_id, StudentHistory(student_id=student_id, records=[]))

    def append(self, student_id: str, record: PaperRecord) -> None:
        history = self.load(student_id)
        self._histories[student_id] = StudentHistory(
            student_id=student_id, records=[*history.records, record]
        )

    def list_students(self) -> list[str]:
        return list(self._histories)


@pytest.fixture
def inner_store() -> FakeHistoryStore:
    return FakeHistoryStore(
        {
            STUDENT: StudentHistory(
                student_id=STUDENT,
                records=[_record("attempt-1"), _record("attempt-2")],
            )
        }
    )


@pytest.fixture
def excluded_attempt() -> frozenset[str]:
    return frozenset({"attempt-1"})


@pytest.fixture
def scoped_store(
    inner_store: FakeHistoryStore, excluded_attempt: frozenset[str]
) -> ClassScopedHistoryStore:
    return ClassScopedHistoryStore(inner_store, excluded_attempt)


def test_an_excluded_attempt_is_dropped_from_the_class_view(
    scoped_store: ClassScopedHistoryStore, inner_store: FakeHistoryStore
) -> None:
    assert len(inner_store.load(STUDENT).records) == 2  # present in the raw store
    assert len(scoped_store.load(STUDENT).records) == 1  # absent in the class's view
    assert scoped_store.load(STUDENT).records[0].attempt_id == "attempt-2"


def test_exclusion_is_scoped_to_one_class(inner_store: FakeHistoryStore) -> None:
    scoped_store_a = ClassScopedHistoryStore(inner_store, frozenset({"attempt-1"}))
    scoped_store_b = ClassScopedHistoryStore(inner_store, frozenset())
    assert len(scoped_store_a.load(STUDENT).records) == 1
    assert len(scoped_store_b.load(STUDENT).records) == 2


def test_the_scoped_store_satisfies_the_protocol(inner_store: FakeHistoryStore) -> None:
    """No ``isinstance`` — ``HistoryStoreProtocol`` is not ``runtime_checkable``
    (owner ruling R7, review amendments). This typed assignment is what mypy
    checks structurally in CI; the call below is the runtime half of the proof.
    """
    store: HistoryStoreProtocol = ClassScopedHistoryStore(inner_store, frozenset())
    assert store.load(STUDENT).student_id == STUDENT
    assert store.list_students() == [STUDENT]


def test_a_record_with_no_attempt_id_is_never_dropped() -> None:
    """The JSON store carries attempt_id=None; it cannot be excluded and must pass through."""
    store = FakeHistoryStore({STUDENT: StudentHistory(student_id=STUDENT, records=[_record(None)])})
    scoped_store = ClassScopedHistoryStore(store, frozenset({"attempt-1", "attempt-2"}))
    assert len(scoped_store.load(STUDENT).records) == 1


def test_scoped_store_append_and_list_students_delegate_unchanged(
    inner_store: FakeHistoryStore,
) -> None:
    """A class view never writes, but the protocol requires ``append``/``list_students``."""
    scoped_store = ClassScopedHistoryStore(inner_store, frozenset({"attempt-1"}))
    scoped_store.append(STUDENT, _record("attempt-3"))
    assert len(inner_store.load(STUDENT).records) == 3
    assert scoped_store.list_students() == inner_store.list_students()


def test_load_roster_histories_pairs_each_entry_with_its_history(
    inner_store: FakeHistoryStore,
) -> None:
    other_student = "22222222-2222-2222-2222-222222222222"
    inner_store.append(other_student, _record("attempt-9"))
    roster = [
        RosterEntry(student_id=uuid.UUID(STUDENT), display_name="Amelia"),
        RosterEntry(student_id=uuid.UUID(other_student), display_name="Jonas"),
    ]
    pairs = load_roster_histories(inner_store, roster)
    assert [entry.display_name for entry, _ in pairs] == ["Amelia", "Jonas"]
    assert [history.student_id for _, history in pairs] == [STUDENT, other_student]


def test_load_roster_histories_over_empty_roster_is_empty(inner_store: FakeHistoryStore) -> None:
    assert load_roster_histories(inner_store, []) == []
