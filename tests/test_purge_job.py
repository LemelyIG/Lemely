"""The purge job (design 2026-09-22 §7, §13; Task 10).

Purge is the only code in the deletion feature that destroys data for good, so
every test here reads back through a **fresh** session with
``INCLUDE_DELETED`` — a warm identity map, or the loader criterion hiding the
very rows under test, would let a test pass on a purge that removed nothing.

The fully-populated fixture carries every child table a purged attempt owns
(question results, points, revisions, weakness rows, a review item pointing at
a question result), because ``review_queue.question_result_id`` has no
``ondelete`` and only a fixture that fills it asks the FK-ordering question.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog.testing
from sqlalchemy import select

from lemely.core.deletion import PURGE_GRACE, RETENTION_DAYS
from lemely.db.models import User
from lemely.db.models.academic import MarkScheme, Paper, Subject
from lemely.db.models.attempts import (
    Attempt,
    QuestionResult,
    QuestionResultPoint,
    QuestionResultRevision,
    Upload,
    WeaknessRecord,
)
from lemely.db.models.enums import (
    AttemptOrigin,
    ConfidenceBand,
    MarkerSource,
    ReviewReason,
    RevisionSource,
    Role,
    SessionMonth,
)
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.session import INCLUDE_DELETED
from lemely.runtime.errors import ExternalServiceError
from lemely.web import purge as purge_module
from lemely.web.purge import purge_expired_papers
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

BUCKET = "lemely-uploads-test"

#: Comfortably past the purge cutoff (retention + grace).
_EXPIRED = timedelta(days=RETENTION_DAYS + 2)


class RecordingStorage(FakeStorageBackend):
    """The shared fake, recording every delete and optionally running a hook first.

    ``on_delete`` runs *before* the object is removed, so a test can observe
    the database at the instant purge touches storage.
    """

    def __init__(self, on_delete: Callable[[str, str], None] | None = None) -> None:
        super().__init__()
        self.deleted: list[tuple[str, str]] = []
        self._on_delete = on_delete

    def delete(self, bucket: str, object_path: str) -> None:
        if self._on_delete is not None:
            self._on_delete(bucket, object_path)
        self.deleted.append((bucket, object_path))
        super().delete(bucket, object_path)

    def holds(self, object_path: str) -> bool:
        try:
            self.download(BUCKET, object_path)
        except KeyError:
            return False
        return True


class FailingStorage(RecordingStorage):
    """Every delete is a real backend failure, as GCS raises it."""

    def delete(self, bucket: str, object_path: str) -> None:
        raise ExternalServiceError(f"GCS unavailable deleting {bucket}/{object_path}")


@dataclass(frozen=True)
class SeededPaper:
    """One seeded deleted paper: an upload and its attempts."""

    upload_id: uuid.UUID
    attempt_ids: tuple[uuid.UUID, ...]
    storage_path: str

    @property
    def attempt_id(self) -> uuid.UUID:
        return self.attempt_ids[0]

    @property
    def scheme_path(self) -> str:
        return self.storage_path.rsplit("/", 1)[0] + "/mark_scheme.pdf"


# ── seeding ─────────────────────────────────────────────────────────────────


def _seed_user(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return uid


def _seed_upload(
    sm: sessionmaker[Session], owner: uuid.UUID, *, deleted_at: datetime | None
) -> tuple[uuid.UUID, str]:
    upload_id = uuid.uuid4()
    path = f"uploads/{owner}/{uuid.uuid4()}/scan.pdf"
    with sm.begin() as session:
        session.add(
            Upload(
                id=upload_id,
                user_id=owner,
                storage_path=path,
                deleted_at=deleted_at,
                idempotency_key=None if deleted_at else f"scan-{upload_id}",
            )
        )
    return upload_id, path


def _seed_attempt(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    upload_id: uuid.UUID | None,
    *,
    deleted_at: datetime | None,
    paper_id: uuid.UUID | None = None,
) -> uuid.UUID:
    attempt_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Attempt(
                id=attempt_id,
                user_id=owner,
                upload_id=upload_id,
                paper_id=paper_id,
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2024,
                paper_number=4,
                paper_variant=2,
                awarded_marks=30,
                maximum_marks=40,
                percentage=75.0,
                recorded_at=datetime.now(UTC) - timedelta(days=90),
                origin=AttemptOrigin.past_paper,
                deleted_at=deleted_at,
            )
        )
    return attempt_id


def _seed_paper(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    *,
    ago: timedelta = _EXPIRED,
    attempts: int = 1,
    paper_id: uuid.UUID | None = None,
) -> SeededPaper:
    """A paper deleted ``ago``: the upload and every attempt share one instant."""
    instant = datetime.now(UTC) - ago
    upload_id, path = _seed_upload(sm, owner, deleted_at=instant)
    ids = tuple(
        _seed_attempt(sm, owner, upload_id, deleted_at=instant, paper_id=paper_id)
        for _ in range(attempts)
    )
    return SeededPaper(upload_id=upload_id, attempt_ids=ids, storage_path=path)


def _populate(sm: sessionmaker[Session], owner: uuid.UUID, attempt_id: uuid.UUID) -> None:
    """Every child row an attempt can own, including a review item on a question."""
    qr_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionResult(
                id=qr_id,
                attempt_id=attempt_id,
                question_id="1",
                awarded_marks=2,
                maximum_marks=4,
                confidence_band=ConfidenceBand.low,
                confidence_score=0.4,
                marker_source=MarkerSource.ai,
            )
        )
        session.flush()
        session.add(
            QuestionResultPoint(
                question_result_id=qr_id,
                mark_point_id="M1",
                ordinal=0,
                tariff=1,
                point_text="States the law",
                awarded=True,
            )
        )
        session.add(
            QuestionResultRevision(
                question_result_id=qr_id,
                revision=1,
                source=RevisionSource.ai,
                awarded_marks=2,
                points_snapshot=[],
            )
        )
        session.add(
            WeaknessRecord(
                user_id=owner,
                attempt_id=attempt_id,
                topic="Forces",
                lost_marks=2,
                maximum_marks=4,
                accuracy=0.5,
                question_ids=["1"],
            )
        )
        session.add(
            ReviewQueueItem(
                attempt_id=attempt_id,
                question_result_id=qr_id,
                reason=ReviewReason.low_confidence,
            )
        )


def _store_objects(storage: FakeStorageBackend, paper: SeededPaper) -> None:
    storage.upload(BUCKET, paper.storage_path, b"%PDF scan", "application/pdf")
    storage.upload(BUCKET, paper.scheme_path, b"%PDF scheme", "application/pdf")


def _set_deleted_at(sm: sessionmaker[Session], paper: SeededPaper, value: datetime | None) -> None:
    with sm.begin() as session:
        # Called from inside a storage hook: if purge ever held its row locks
        # across the storage call, this would wait forever. Fail cleanly instead.
        session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
        session.execute(
            sa.update(Attempt)
            .where(Attempt.id.in_(paper.attempt_ids))
            .values(deleted_at=value)
            .execution_options(**{INCLUDE_DELETED: True})
        )
        session.execute(
            sa.update(Upload)
            .where(Upload.id == paper.upload_id)
            .values(deleted_at=value)
            .execution_options(**{INCLUDE_DELETED: True})
        )


def _attempt_exists(sm: sessionmaker[Session], attempt_id: uuid.UUID) -> bool:
    with sm() as session:
        return (
            session.scalars(
                select(Attempt.id)
                .where(Attempt.id == attempt_id)
                .execution_options(**{INCLUDE_DELETED: True})
            ).one_or_none()
            is not None
        )


def _upload_exists(sm: sessionmaker[Session], upload_id: uuid.UUID) -> bool:
    with sm() as session:
        return (
            session.scalars(
                select(Upload.id)
                .where(Upload.id == upload_id)
                .execution_options(**{INCLUDE_DELETED: True})
            ).one_or_none()
            is not None
        )


def _count(sm: sessionmaker[Session], stmt: sa.Select[tuple[int]]) -> int:
    with sm() as session:
        return session.scalar(stmt) or 0


def _children(sm: sessionmaker[Session], attempt_id: uuid.UUID) -> dict[str, int]:
    qr_ids = select(QuestionResult.id).where(QuestionResult.attempt_id == attempt_id)
    return {
        "question_results": _count(
            sm,
            select(sa.func.count())
            .select_from(QuestionResult)
            .where(QuestionResult.attempt_id == attempt_id),
        ),
        "points": _count(
            sm,
            select(sa.func.count())
            .select_from(QuestionResultPoint)
            .where(QuestionResultPoint.question_result_id.in_(qr_ids)),
        ),
        "revisions": _count(
            sm,
            select(sa.func.count())
            .select_from(QuestionResultRevision)
            .where(QuestionResultRevision.question_result_id.in_(qr_ids)),
        ),
        "weaknesses": _count(
            sm,
            select(sa.func.count())
            .select_from(WeaknessRecord)
            .where(WeaknessRecord.attempt_id == attempt_id),
        ),
        "review_items": _count(
            sm,
            select(sa.func.count())
            .select_from(ReviewQueueItem)
            .where(ReviewQueueItem.attempt_id == attempt_id),
        ),
    }


_ALL_ONE = {"question_results": 1, "points": 1, "revisions": 1, "weaknesses": 1, "review_items": 1}
_ALL_ZERO = dict.fromkeys(_ALL_ONE, 0)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sessionmaker_(migrated_sessionmaker: sessionmaker[Session]) -> sessionmaker[Session]:
    return migrated_sessionmaker


@pytest.fixture
def owner(sessionmaker_: sessionmaker[Session]) -> uuid.UUID:
    return _seed_user(sessionmaker_)


@pytest.fixture
def fake_storage() -> RecordingStorage:
    return RecordingStorage()


@pytest.fixture
def mark_scheme_row(sessionmaker_: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """Shared reference data (D2): a paper and its parsed scheme. Returns both ids."""
    with sessionmaker_.begin() as session:
        if session.scalars(select(Subject).where(Subject.code == "0625")).first() is None:
            session.add(Subject(code="0625", name="Physics"))
            session.flush()
        paper = Paper(
            subject_code="0625",
            session_month=SessionMonth.oct_nov,
            session_year=2019,
            paper_number=4,
            paper_variant=3,
        )
        session.add(paper)
        session.flush()
        scheme = MarkScheme(paper_id=paper.id, maximum_mark=80, parsed_payload={})
        session.add(scheme)
        session.flush()
        return paper.id, scheme.id


@pytest.fixture
def fully_populated_deleted_attempt(
    sessionmaker_: sessionmaker[Session],
    owner: uuid.UUID,
    fake_storage: RecordingStorage,
    mark_scheme_row: tuple[uuid.UUID, uuid.UUID],
) -> SeededPaper:
    """Deleted long past the cutoff, pointing at a real paper, every child row filled."""
    paper = _seed_paper(sessionmaker_, owner, paper_id=mark_scheme_row[0])
    _populate(sessionmaker_, owner, paper.attempt_id)
    assert _children(sessionmaker_, paper.attempt_id) == _ALL_ONE
    _store_objects(fake_storage, paper)
    return paper


# ── the purge ───────────────────────────────────────────────────────────────


def test_purge_deletes_the_object_then_every_row(
    sessionmaker_: sessionmaker[Session], fully_populated_deleted_attempt: SeededPaper
) -> None:
    paper = fully_populated_deleted_attempt
    rows_at_delete: list[bool] = []

    def record(_bucket: str, _path: str) -> None:
        rows_at_delete.append(_attempt_exists(sessionmaker_, paper.attempt_id))

    storage = RecordingStorage(on_delete=record)
    _store_objects(storage, paper)

    assert purge_expired_papers(sessionmaker_, storage, BUCKET) == 1

    assert storage.deleted == [(BUCKET, paper.storage_path), (BUCKET, paper.scheme_path)]
    assert not storage.holds(paper.storage_path)
    # Object first: the row was still there, as the record of intent, when
    # storage was touched.
    assert rows_at_delete == [True, True]
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)
    assert not _upload_exists(sessionmaker_, paper.upload_id)
    assert _children(sessionmaker_, paper.attempt_id) == _ALL_ZERO


def test_a_row_inside_the_window_is_untouched(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    paper = _seed_paper(sessionmaker_, owner, ago=timedelta(days=3))
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0
    assert fake_storage.deleted == []
    assert _attempt_exists(sessionmaker_, paper.attempt_id)
    assert _upload_exists(sessionmaker_, paper.upload_id)


def test_a_row_inside_the_grace_gap_is_untouched(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    """Past RETENTION_DAYS: no longer restorable, and not yet purgeable."""
    paper = _seed_paper(sessionmaker_, owner, ago=timedelta(days=RETENTION_DAYS, minutes=1))
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0
    assert fake_storage.deleted == []
    assert _attempt_exists(sessionmaker_, paper.attempt_id)


def test_a_row_just_past_the_grace_gap_is_purged(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    """The boundary from the other side, so the gap test cannot pass on a purge that never runs."""
    paper = _seed_paper(
        sessionmaker_, owner, ago=timedelta(days=RETENTION_DAYS, minutes=1) + PURGE_GRACE
    )
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)


def test_a_live_paper_is_untouched(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    upload_id, _ = _seed_upload(sessionmaker_, owner, deleted_at=None)
    attempt_id = _seed_attempt(sessionmaker_, owner, upload_id, deleted_at=None)
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0
    assert _attempt_exists(sessionmaker_, attempt_id)
    assert _upload_exists(sessionmaker_, upload_id)


def test_a_storage_failure_leaves_every_row_for_the_next_pass(
    sessionmaker_: sessionmaker[Session], fully_populated_deleted_attempt: SeededPaper
) -> None:
    paper = fully_populated_deleted_attempt
    with structlog.testing.capture_logs() as captured:
        assert purge_expired_papers(sessionmaker_, FailingStorage(), BUCKET) == 0

    assert _attempt_exists(sessionmaker_, paper.attempt_id)
    assert _upload_exists(sessionmaker_, paper.upload_id)
    assert _children(sessionmaker_, paper.attempt_id) == _ALL_ONE
    assert [e["event"] for e in captured if e["log_level"] == "warning"] == [
        "purge_object_delete_failed"
    ]
    # ...and the next pass, with storage back, finishes the job.
    assert purge_expired_papers(sessionmaker_, RecordingStorage(), BUCKET) == 1
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)


def test_a_missing_object_is_not_a_failure(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """Nothing was ever stored: the idempotent delete answers, and the rows go."""
    paper = _seed_paper(sessionmaker_, owner)
    _populate(sessionmaker_, owner, paper.attempt_id)
    assert purge_expired_papers(sessionmaker_, RecordingStorage(), BUCKET) == 1
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)


def test_the_sibling_mark_scheme_scan_goes_too(
    sessionmaker_: sessionmaker[Session],
    fake_storage: RecordingStorage,
    fully_populated_deleted_attempt: SeededPaper,
) -> None:
    paper = fully_populated_deleted_attempt
    purge_expired_papers(sessionmaker_, fake_storage, BUCKET)
    assert (BUCKET, paper.scheme_path) in fake_storage.deleted
    assert not fake_storage.holds(paper.scheme_path)


def test_mark_scheme_reference_rows_are_never_touched(
    sessionmaker_: sessionmaker[Session],
    fake_storage: RecordingStorage,
    fully_populated_deleted_attempt: SeededPaper,
    mark_scheme_row: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """D2: mark schemes are shared reference data, not the student's upload."""
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1
    with sessionmaker_() as session:
        assert session.get(Paper, mark_scheme_row[0]) is not None
        assert session.get(MarkScheme, mark_scheme_row[1]) is not None


def test_purging_twice_is_a_no_op(
    sessionmaker_: sessionmaker[Session],
    fake_storage: RecordingStorage,
    fully_populated_deleted_attempt: SeededPaper,
) -> None:
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 0
    assert len(fake_storage.deleted) == 2


# ── the unit is the upload (R7) ─────────────────────────────────────────────


def test_every_attempt_on_one_upload_goes_with_one_object_delete(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    paper = _seed_paper(sessionmaker_, owner, attempts=2)
    for attempt_id in paper.attempt_ids:
        _populate(sessionmaker_, owner, attempt_id)

    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 2

    assert fake_storage.deleted == [(BUCKET, paper.storage_path), (BUCKET, paper.scheme_path)]
    for attempt_id in paper.attempt_ids:
        assert not _attempt_exists(sessionmaker_, attempt_id)
        assert _children(sessionmaker_, attempt_id) == _ALL_ZERO
    assert not _upload_exists(sessionmaker_, paper.upload_id)


def test_the_object_stays_while_a_sibling_is_inside_the_window(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    """A sibling deleted at a later instant keeps the scan; only the expired row goes.

    Leaving the expired row too would park it at the head of the
    ``(deleted_at, id)`` order for up to thirty days, taking a batch slot on
    every pass.
    """
    paper = _seed_paper(sessionmaker_, owner)
    recent = _seed_attempt(
        sessionmaker_,
        owner,
        paper.upload_id,
        deleted_at=datetime.now(UTC) - timedelta(days=2),
    )
    _populate(sessionmaker_, owner, paper.attempt_id)

    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1

    assert fake_storage.deleted == []
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)
    assert _children(sessionmaker_, paper.attempt_id) == _ALL_ZERO
    assert _attempt_exists(sessionmaker_, recent)
    assert _upload_exists(sessionmaker_, paper.upload_id)


def test_the_object_stays_while_the_upload_itself_is_live(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    """A live upload can still be re-marked, so its scan is not purge's to take."""
    upload_id, _ = _seed_upload(sessionmaker_, owner, deleted_at=None)
    expired = _seed_attempt(
        sessionmaker_, owner, upload_id, deleted_at=datetime.now(UTC) - _EXPIRED
    )
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1
    assert fake_storage.deleted == []
    assert not _attempt_exists(sessionmaker_, expired)
    assert _upload_exists(sessionmaker_, upload_id)


def test_a_live_attempt_on_a_deleted_upload_is_logged_and_skipped(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    """The Task 5a invariant, broken: never cascade, and never stop the pass."""
    broken = _seed_paper(sessionmaker_, owner)
    live = _seed_attempt(sessionmaker_, owner, broken.upload_id, deleted_at=None)
    healthy = _seed_paper(sessionmaker_, owner)

    with structlog.testing.capture_logs() as captured:
        assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1

    assert [e["event"] for e in captured if e["log_level"] == "error"] == [
        "purge_live_attempt_on_deleted_upload"
    ]
    assert _attempt_exists(sessionmaker_, broken.attempt_id)
    assert _attempt_exists(sessionmaker_, live)
    assert _upload_exists(sessionmaker_, broken.upload_id)
    assert (BUCKET, broken.storage_path) not in fake_storage.deleted
    assert not _attempt_exists(sessionmaker_, healthy.attempt_id)


def test_an_expired_attempt_with_no_upload_is_purged_without_storage(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    attempt_id = _seed_attempt(sessionmaker_, owner, None, deleted_at=datetime.now(UTC) - _EXPIRED)
    _populate(sessionmaker_, owner, attempt_id)
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1
    assert fake_storage.deleted == []
    assert not _attempt_exists(sessionmaker_, attempt_id)
    assert _children(sessionmaker_, attempt_id) == _ALL_ZERO


# ── batching and order ──────────────────────────────────────────────────────


def test_the_oldest_deletion_goes_first_and_the_limit_holds(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    newer = _seed_paper(sessionmaker_, owner, ago=_EXPIRED)
    older = _seed_paper(sessionmaker_, owner, ago=_EXPIRED + timedelta(days=5))

    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET, limit=1) == 1
    assert not _attempt_exists(sessionmaker_, older.attempt_id)
    assert _attempt_exists(sessionmaker_, newer.attempt_id)

    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET, limit=1) == 1
    assert not _attempt_exists(sessionmaker_, newer.attempt_id)


def test_one_papers_storage_failure_does_not_stop_the_others(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID
) -> None:
    stuck = _seed_paper(sessionmaker_, owner, ago=_EXPIRED + timedelta(days=5))
    fine = _seed_paper(sessionmaker_, owner)

    def fail_on_stuck(_bucket: str, path: str) -> None:
        if path == stuck.storage_path:
            raise ExternalServiceError("GCS unavailable")

    assert purge_expired_papers(sessionmaker_, RecordingStorage(fail_on_stuck), BUCKET) == 1
    assert _attempt_exists(sessionmaker_, stuck.attempt_id)
    assert not _attempt_exists(sessionmaker_, fine.attempt_id)


def test_one_papers_database_failure_does_not_stop_the_others(
    sessionmaker_: sessionmaker[Session],
    owner: uuid.UUID,
    fake_storage: RecordingStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stuck = _seed_paper(sessionmaker_, owner, ago=_EXPIRED + timedelta(days=5))
    fine = _seed_paper(sessionmaker_, owner)
    real_lock = purge_module._lock

    def lock(session: Session, upload_id: uuid.UUID) -> object:
        if upload_id == stuck.upload_id:
            raise sa.exc.OperationalError("SELECT ... FOR UPDATE", {}, Exception("boom"))
        return real_lock(session, upload_id)

    monkeypatch.setattr(purge_module, "_lock", lock)
    with structlog.testing.capture_logs() as captured:
        assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET) == 1

    failures = [e["upload_id"] for e in captured if e["event"] == "purge_paper_failed"]
    assert failures == [str(stuck.upload_id)]
    assert _attempt_exists(sessionmaker_, stuck.attempt_id)
    assert not _attempt_exists(sessionmaker_, fine.attempt_id)


def test_now_is_injectable(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    paper = _seed_paper(sessionmaker_, owner, ago=timedelta(days=3))
    later = datetime.now(UTC) + timedelta(days=RETENTION_DAYS)
    assert purge_expired_papers(sessionmaker_, fake_storage, BUCKET, now=later) == 1
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)


# ── the decision is re-taken under lock ─────────────────────────────────────


def test_the_row_deletes_re_check_the_cutoff_after_the_object_call(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """A row that left the purgeable set during the storage call keeps its rows.

    Restore cannot do this past the cutoff (the time gap is the guarantee);
    the test forces it anyway to prove the second transaction re-decides on
    the locked copies rather than acting on the first one's answer.
    """
    paper = _seed_paper(sessionmaker_, owner)
    storage = RecordingStorage(on_delete=lambda _b, _p: _set_deleted_at(sessionmaker_, paper, None))

    with structlog.testing.capture_logs() as captured:
        assert purge_expired_papers(sessionmaker_, storage, BUCKET) == 0

    assert _attempt_exists(sessionmaker_, paper.attempt_id)
    assert _upload_exists(sessionmaker_, paper.upload_id)
    assert "purge_paper_changed_after_object_delete" in [e["event"] for e in captured]


def test_purge_locks_the_upload_before_any_attempt(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID, fake_storage: RecordingStorage
) -> None:
    """Upload → attempts, the order delete, restore and persist all take.

    Another transaction holds the upload. Purge must queue on it without
    having taken any attempt lock, so the attempt is still free to a NOWAIT
    lock; an attempts-first purge would already hold it, and the NOWAIT fails.
    """
    paper = _seed_paper(sessionmaker_, owner)
    holder = sessionmaker_()
    try:
        holder.execute(
            sa.text("SELECT id FROM uploads WHERE id = :id FOR UPDATE"), {"id": paper.upload_id}
        )
        worker = _Paused(lambda: purge_expired_papers(sessionmaker_, fake_storage, BUCKET))
        _wait_until_a_backend_waits_on_a_lock(sessionmaker_)

        holder.execute(
            sa.text("SELECT id FROM attempts WHERE id = :id FOR UPDATE NOWAIT"),
            {"id": paper.attempt_id},
        )
        holder.rollback()
    finally:
        holder.close()

    worker.join()
    assert worker.error is None
    assert worker.result == 1
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)


# ── the sweeper wiring ──────────────────────────────────────────────────────


def test_get_sweeper_wires_storage_and_the_uploads_bucket() -> None:
    from lemely.web import deps

    deps.get_sweeper.cache_clear()
    try:
        sweeper = deps.get_sweeper()
        assert sweeper.storage is deps.get_storage_backend()
        assert sweeper.bucket == deps.get_settings().storage.bucket
    finally:
        deps.get_sweeper.cache_clear()


# ── two replicas on one upload ──────────────────────────────────────────────


def _racing_replica(sm: sessionmaker[Session], counts: list[int]) -> RecordingStorage:
    """Storage whose first delete runs a whole second purge pass, as another replica would.

    The outer pass has taken its decision and committed by then, so both
    replicas hold the same decision, which is the interleaving under test.
    """

    def run_the_other_replica(_bucket: str, _path: str) -> None:
        if not counts:
            counts.append(purge_expired_papers(sm, RecordingStorage(), BUCKET))

    return RecordingStorage(on_delete=run_the_other_replica)


def test_a_replica_that_finds_the_work_done_is_not_an_error(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID
) -> None:
    paper = _seed_paper(sessionmaker_, owner)
    _populate(sessionmaker_, owner, paper.attempt_id)
    inner: list[int] = []

    with structlog.testing.capture_logs() as captured:
        outer = purge_expired_papers(sessionmaker_, _racing_replica(sessionmaker_, inner), BUCKET)

    assert inner, "the second replica never ran"
    assert outer + inner[0] == 1
    assert [e["event"] for e in captured if e["log_level"] == "error"] == []
    assert "purge_already_done" in [e["event"] for e in captured]
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)
    assert not _upload_exists(sessionmaker_, paper.upload_id)
    assert _children(sessionmaker_, paper.attempt_id) == _ALL_ZERO


def test_a_replica_that_finds_the_partial_work_done_is_not_an_error(
    sessionmaker_: sessionmaker[Session], owner: uuid.UUID
) -> None:
    """The partial path touches no storage, so the race is staged between its two transactions."""
    paper = _seed_paper(sessionmaker_, owner)
    recent = _seed_attempt(
        sessionmaker_, owner, paper.upload_id, deleted_at=datetime.now(UTC) - timedelta(days=2)
    )
    inner: list[int] = []
    real_lock = purge_module._lock
    calls: list[uuid.UUID] = []

    def lock(session: Session, upload_id: uuid.UUID) -> object:
        calls.append(upload_id)
        if len(calls) == 2 and not inner:
            # Between the outer pass's two transactions: the other replica.
            inner.append(purge_expired_papers(sessionmaker_, RecordingStorage(), BUCKET))
        return real_lock(session, upload_id)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(purge_module, "_lock", lock)
        with structlog.testing.capture_logs() as captured:
            outer = purge_expired_papers(sessionmaker_, RecordingStorage(), BUCKET)

    assert inner, "the second replica never ran"
    assert outer + inner[0] == 1
    assert [e["event"] for e in captured if e["log_level"] == "error"] == []
    assert "purge_already_done" in [e["event"] for e in captured]
    assert not _attempt_exists(sessionmaker_, paper.attempt_id)
    assert _attempt_exists(sessionmaker_, recent)
    assert _upload_exists(sessionmaker_, paper.upload_id)
