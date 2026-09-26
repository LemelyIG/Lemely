"""A teacher's own grading-console paper: delete, restore, list and purge (R2, Task 16).

Mirrors the student flow (``test_deletion_repo.py``, ``test_purge_job.py``) with
the four differences design §2.2 names: no ``Attempt`` and no cascade, review
items hang off ``teacher_paper_id``, **no integrity hold**, and the owner is
``uploaded_by``.

Every post-change assertion reads through a **fresh** session with
``INCLUDE_DELETED``: a warm identity map, or the loader criterion hiding the row
under test, would let a test pass on a write that never happened. Every
absence assertion is preceded by a presence assertion on the same row.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog.testing
from sqlalchemy import select

from lemely.core.deletion import RETENTION_DAYS, purge_cutoff, restore_deadline
from lemely.db.class_repo import ClassService
from lemely.db.deletion_repo import (
    DeletedTeacherPaper,
    PaperNotFoundError,
    PaperNotRestorableError,
    TeacherPaperDeletionService,
)
from lemely.db.models import School, SchoolMembership, TeacherPaper, User
from lemely.db.models.enums import MembershipRole, ReviewReason, ReviewStatus, Role, UploadStatus
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import (
    BulkApproveResult,
    BulkApproveSkip,
    ReviewAlreadyClosedError,
    ReviewNotFoundError,
    ReviewOwnershipError,
    ReviewService,
)
from lemely.db.session import INCLUDE_DELETED
from lemely.db.teacher_paper_repo import TeacherPaperDeletedError, TeacherPaperRepository
from lemely.web import purge as purge_module
from lemely.web.purge import purge_expired_teacher_papers
from lemely.web.routers.teacher import _paper_summary
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.test_purge_job import FailingStorage, RecordingStorage
from tests.test_teacher_paper_repo import _mark_scheme, _metadata, _report

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

BUCKET = "lemely-uploads-test"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


# ── seeding and fresh reads ─────────────────────────────────────────────────


def _user(sm: sessionmaker[Session], role: Role = Role.teacher) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _paper(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    *,
    scheme: bool = False,
    status: UploadStatus = UploadStatus.complete,
    report: bool = False,
    deleted_at: datetime | None = None,
) -> uuid.UUID:
    pid = uuid.uuid4()
    prefix = f"teacher/{owner}/{pid.hex}"
    with sm.begin() as session:
        session.add(
            TeacherPaper(
                id=pid,
                uploaded_by=owner,
                storage_path=f"{prefix}/scan.pdf",
                scheme_storage_path=f"{prefix}/mark_scheme.pdf" if scheme else None,
                original_filename="scan.pdf",
                status=status,
                report_json=_report().model_dump(mode="json") if report else None,
                deleted_at=deleted_at,
            )
        )
    return pid


def _item(
    sm: sessionmaker[Session],
    paper_id: uuid.UUID,
    *,
    reason: ReviewReason = ReviewReason.low_confidence,
    status: ReviewStatus = ReviewStatus.open,
    withdrawn_at: datetime | None = None,
) -> uuid.UUID:
    iid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            ReviewQueueItem(
                id=iid,
                teacher_paper_id=paper_id,
                question_id="1",
                reason=reason,
                status=status,
                withdrawn_at=withdrawn_at,
            )
        )
    return iid


def _school_with(sm: sessionmaker[Session], *, admin: uuid.UUID, teacher: uuid.UUID) -> uuid.UUID:
    """Mirrors ``test_teacher_paper_repo.py``'s builder of the same name (DS11)."""
    sid = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=sid, name=f"School {sid.hex[:6]}"))
        session.flush()
        session.add(
            SchoolMembership(
                school_id=sid, user_id=admin, membership_role=MembershipRole.school_admin
            )
        )
        session.add(
            SchoolMembership(school_id=sid, user_id=teacher, membership_role=MembershipRole.teacher)
        )
    return sid


def _paper_row(sm: sessionmaker[Session], paper_id: uuid.UUID) -> TeacherPaper | None:
    with sm() as session:
        return session.scalars(
            select(TeacherPaper)
            .where(TeacherPaper.id == paper_id)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one_or_none()


def _item_row(sm: sessionmaker[Session], item_id: uuid.UUID) -> ReviewQueueItem | None:
    with sm() as session:
        return session.get(ReviewQueueItem, item_id)


def _items_of(sm: sessionmaker[Session], paper_id: uuid.UUID) -> list[ReviewQueueItem]:
    with sm() as session:
        return list(
            session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.teacher_paper_id == paper_id)
            )
        )


def _backdate(sm: sessionmaker[Session], paper_id: uuid.UUID, by: timedelta) -> None:
    """Shift a deletion into the past: the paper's instant and the items it withdrew."""
    with sm.begin() as session:
        paper = session.scalars(
            select(TeacherPaper)
            .where(TeacherPaper.id == paper_id)
            .execution_options(**{INCLUDE_DELETED: True})
        ).one()
        assert paper.deleted_at is not None
        instant = paper.deleted_at
        paper.deleted_at = instant - by
        session.execute(
            sa.update(ReviewQueueItem)
            .where(
                ReviewQueueItem.teacher_paper_id == paper_id,
                ReviewQueueItem.withdrawn_at == instant,
            )
            .values(withdrawn_at=instant - by)
        )


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sessionmaker_(migrated_sessionmaker: sessionmaker[Session]) -> sessionmaker[Session]:
    return migrated_sessionmaker


@pytest.fixture
def teacher(sessionmaker_: sessionmaker[Session]) -> uuid.UUID:
    return _user(sessionmaker_)


@pytest.fixture
def other_teacher(sessionmaker_: sessionmaker[Session]) -> uuid.UUID:
    return _user(sessionmaker_)


@pytest.fixture
def service(sessionmaker_: sessionmaker[Session]) -> TeacherPaperDeletionService:
    return TeacherPaperDeletionService(sessionmaker_)


@pytest.fixture
def repo(sessionmaker_: sessionmaker[Session]) -> TeacherPaperRepository:
    return TeacherPaperRepository(sessionmaker_, stale_after=timedelta(minutes=15))


@pytest.fixture
def console_paper(sessionmaker_: sessionmaker[Session], teacher: uuid.UUID) -> uuid.UUID:
    return _paper(sessionmaker_, teacher, report=True)


@pytest.fixture
def console_item(sessionmaker_: sessionmaker[Session], console_paper: uuid.UUID) -> uuid.UUID:
    return _item(sessionmaker_, console_paper)


@pytest.fixture
def fake_storage() -> RecordingStorage:
    return RecordingStorage()


# ── delete ──────────────────────────────────────────────────────────────────


def test_a_teacher_deletes_their_own_console_paper(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    before = _paper_row(sessionmaker_, console_paper)
    assert before is not None
    assert before.deleted_at is None

    result = service.delete(str(teacher), str(console_paper))

    assert isinstance(result, DeletedTeacherPaper)
    assert result.paper_id == console_paper
    # The console card's own name for it, from the stored report's metadata.
    assert result.label == f"Paper 3 V1 May/June 2020 - {before.created_at.date().isoformat()}"
    assert result.restore_deadline == restore_deadline(result.deleted_at)
    after = _paper_row(sessionmaker_, console_paper)
    assert after is not None
    assert after.deleted_at == result.deleted_at
    assert service.list_deleted(str(teacher))[0].paper_id == console_paper


def test_the_console_reads_hide_a_deleted_paper(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    assert repo.get_visible(console_paper, viewer_id=teacher, viewer_role=Role.teacher) is not None
    assert console_paper in {
        r.id for r in repo.list_visible(viewer_id=teacher, viewer_role=Role.teacher)
    }

    service.delete(str(teacher), str(console_paper))

    assert repo.get_visible(console_paper, viewer_id=teacher, viewer_role=Role.teacher) is None
    assert console_paper not in {
        r.id for r in repo.list_visible(viewer_id=teacher, viewer_role=Role.teacher)
    }


def test_the_uploaders_listing_shows_canDelete_true(
    repo: TeacherPaperRepository,
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    """PR #258: the DELETE route is uploader-only, so the card the uploader sees
    must say so — this is the console list's own view of the paper it owns.
    """
    rows = repo.list_visible(viewer_id=teacher, viewer_role=Role.teacher)
    row = next(r for r in rows if r.id == console_paper)

    summary = _paper_summary(row, teacher)

    assert summary.canDelete is True


def test_a_school_admin_who_can_see_the_paper_still_cannot_delete_it(
    sessionmaker_: sessionmaker[Session],
    repo: TeacherPaperRepository,
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    """A school admin sees their school's teachers' papers (DS11) but the delete
    route is uploader-only (:meth:`TeacherPaperDeletionService.delete`), so the
    admin's copy of the same card must not claim it can be deleted.
    """
    admin = _user(sessionmaker_, Role.school_admin)
    _school_with(sessionmaker_, admin=admin, teacher=teacher)
    rows = repo.list_visible(viewer_id=admin, viewer_role=Role.school_admin)
    row = next(r for r in rows if r.id == console_paper)

    summary = _paper_summary(row, admin)

    assert summary.canDelete is False
    # The positive control: the same row, viewed by its uploader, is deletable.
    assert _paper_summary(row, teacher).canDelete is True


def test_a_platform_admin_who_can_see_every_paper_still_cannot_delete_it(
    sessionmaker_: sessionmaker[Session],
    repo: TeacherPaperRepository,
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    platform_admin = _user(sessionmaker_, Role.platform_admin)
    rows = repo.list_visible(viewer_id=platform_admin, viewer_role=Role.platform_admin)
    row = next(r for r in rows if r.id == console_paper)

    summary = _paper_summary(row, platform_admin)

    assert summary.canDelete is False


def test_another_teacher_cannot_delete_it(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    other_teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(str(other_teacher), str(console_paper))
    row = _paper_row(sessionmaker_, console_paper)
    assert row is not None
    assert row.deleted_at is None


@pytest.mark.parametrize("paper_id", ["not-a-uuid", str(uuid.uuid4())])
def test_a_malformed_or_unknown_id_is_a_404(
    service: TeacherPaperDeletionService, teacher: uuid.UUID, paper_id: str
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.delete(str(teacher), paper_id)


def test_deleting_twice_is_a_404_and_keeps_the_first_instant(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    first = service.delete(str(teacher), str(console_paper))
    with pytest.raises(PaperNotFoundError):
        service.delete(str(teacher), str(console_paper))
    row = _paper_row(sessionmaker_, console_paper)
    assert row is not None
    assert row.deleted_at == first.deleted_at


@pytest.mark.parametrize("reason", [ReviewReason.plagiarism_flag, ReviewReason.ai_detection_flag])
def test_an_integrity_flag_does_not_block_a_console_paper(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    reason: ReviewReason,
) -> None:
    """No attributed student, so D8's evidence argument does not apply."""
    flagged = _item(sessionmaker_, console_paper, reason=reason)

    result = service.delete(str(teacher), str(console_paper))

    item = _item_row(sessionmaker_, flagged)
    assert item is not None
    assert item.status is ReviewStatus.withdrawn
    assert item.withdrawn_at == result.deleted_at


def test_deletion_withdraws_its_queue_items_through_teacher_paper_id(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    console_item: uuid.UUID,
) -> None:
    resolved = _item(sessionmaker_, console_paper, status=ReviewStatus.resolved)
    elsewhere = _paper(sessionmaker_, teacher)
    other_item = _item(sessionmaker_, elsewhere)
    before = _item_row(sessionmaker_, console_item)
    assert before is not None
    assert before.status is ReviewStatus.open

    result = service.delete(str(teacher), str(console_paper))

    item = _item_row(sessionmaker_, console_item)
    assert item is not None
    assert item.status is ReviewStatus.withdrawn
    assert item.withdrawn_at == result.deleted_at
    kept = _item_row(sessionmaker_, resolved)
    assert kept is not None
    assert kept.status is ReviewStatus.resolved
    assert kept.withdrawn_at is None
    untouched = _item_row(sessionmaker_, other_item)
    assert untouched is not None
    assert untouched.status is ReviewStatus.open


def _mid_run(sm: sessionmaker[Session], paper_id: uuid.UUID) -> None:
    """Give a paper the stage and counter a run in flight leaves on it."""
    with sm.begin() as session:
        session.execute(
            sa.update(TeacherPaper)
            .where(TeacherPaper.id == paper_id)
            .values(stage="mark", progress_index=2, progress_total=5)
        )


def test_delete_ends_a_processing_run_without_a_report_as_failed(
    service: TeacherPaperDeletionService, sessionmaker_: sessionmaker[Session], teacher: uuid.UUID
) -> None:
    """A run deleted mid-flight can no longer finish; restored, it must be re-runnable."""
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing)
    _mid_run(sessionmaker_, pid)
    service.delete(str(teacher), str(pid))
    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.status is UploadStatus.failed
    assert row.error is not None
    assert (row.stage, row.progress_index, row.progress_total) == (None, None, None)


def test_delete_ends_a_processing_regrade_with_a_report_as_complete(
    service: TeacherPaperDeletionService, sessionmaker_: sessionmaker[Session], teacher: uuid.UUID
) -> None:
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing, report=True)
    _mid_run(sessionmaker_, pid)
    service.delete(str(teacher), str(pid))
    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.status is UploadStatus.complete
    assert (row.stage, row.progress_index, row.progress_total) == (None, None, None)
    assert row.error is None


@pytest.mark.parametrize(
    "status", [UploadStatus.complete, UploadStatus.failed, UploadStatus.pending]
)
def test_delete_leaves_a_non_processing_status_alone(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    status: UploadStatus,
) -> None:
    pid = _paper(sessionmaker_, teacher, status=status)
    service.delete(str(teacher), str(pid))
    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.status is status


# ── restore ─────────────────────────────────────────────────────────────────


def test_restore_reopens_them(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    console_item: uuid.UUID,
) -> None:
    service.delete(str(teacher), str(console_paper))
    withdrawn = _item_row(sessionmaker_, console_item)
    assert withdrawn is not None
    assert withdrawn.status is ReviewStatus.withdrawn

    service.restore(str(teacher), str(console_paper))

    item = _item_row(sessionmaker_, console_item)
    assert item is not None
    assert item.status is ReviewStatus.open
    assert item.withdrawn_at is None
    assert item.created_at == withdrawn.created_at
    row = _paper_row(sessionmaker_, console_paper)
    assert row is not None
    assert row.deleted_at is None


def test_restore_reopens_exactly_the_items_this_deletion_withdrew(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    console_item: uuid.UUID,
) -> None:
    dismissed = _item(
        sessionmaker_,
        console_paper,
        reason=ReviewReason.plagiarism_flag,
        status=ReviewStatus.dismissed,
    )
    earlier = datetime.now(UTC) - timedelta(days=2)
    stale_withdrawal = _item(
        sessionmaker_, console_paper, status=ReviewStatus.withdrawn, withdrawn_at=earlier
    )

    service.delete(str(teacher), str(console_paper))
    service.restore(str(teacher), str(console_paper))

    reopened = _item_row(sessionmaker_, console_item)
    assert reopened is not None
    assert reopened.status is ReviewStatus.open
    still_dismissed = _item_row(sessionmaker_, dismissed)
    assert still_dismissed is not None
    assert still_dismissed.status is ReviewStatus.dismissed
    still_withdrawn = _item_row(sessionmaker_, stale_withdrawal)
    assert still_withdrawn is not None
    assert still_withdrawn.status is ReviewStatus.withdrawn
    assert still_withdrawn.withdrawn_at == earlier


def test_restore_after_the_window_is_refused(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    console_item: uuid.UUID,
) -> None:
    service.delete(str(teacher), str(console_paper))
    _backdate(sessionmaker_, console_paper, timedelta(days=RETENTION_DAYS, minutes=1))

    with pytest.raises(PaperNotRestorableError):
        service.restore(str(teacher), str(console_paper))

    row = _paper_row(sessionmaker_, console_paper)
    assert row is not None
    assert row.deleted_at is not None
    item = _item_row(sessionmaker_, console_item)
    assert item is not None
    assert item.status is ReviewStatus.withdrawn


def test_restore_just_inside_the_window_succeeds(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    console_item: uuid.UUID,
) -> None:
    """The positive control for :func:`_backdate`: it moves the instant, not the match."""
    service.delete(str(teacher), str(console_paper))
    _backdate(sessionmaker_, console_paper, timedelta(days=RETENTION_DAYS, minutes=-5))

    service.restore(str(teacher), str(console_paper))

    item = _item_row(sessionmaker_, console_item)
    assert item is not None
    assert item.status is ReviewStatus.open


def test_restoring_a_live_paper_is_a_404(
    service: TeacherPaperDeletionService, teacher: uuid.UUID, console_paper: uuid.UUID
) -> None:
    with pytest.raises(PaperNotFoundError):
        service.restore(str(teacher), str(console_paper))


def test_another_teacher_cannot_restore(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    other_teacher: uuid.UUID,
    console_paper: uuid.UUID,
) -> None:
    service.delete(str(teacher), str(console_paper))
    with pytest.raises(PaperNotFoundError):
        service.restore(str(other_teacher), str(console_paper))
    row = _paper_row(sessionmaker_, console_paper)
    assert row is not None
    assert row.deleted_at is not None


def test_restoring_twice_is_a_404(
    service: TeacherPaperDeletionService, teacher: uuid.UUID, console_paper: uuid.UUID
) -> None:
    service.delete(str(teacher), str(console_paper))
    service.restore(str(teacher), str(console_paper))
    with pytest.raises(PaperNotFoundError):
        service.restore(str(teacher), str(console_paper))


def test_a_restored_paper_can_be_regraded(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
) -> None:
    """Delete ended the in-flight run, so the restored row is claimable at once."""
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing)
    service.delete(str(teacher), str(pid))
    service.restore(str(teacher), str(pid))
    assert repo.claim_run(pid) is True


# ── list_deleted ────────────────────────────────────────────────────────────


def test_list_deleted_is_the_owners_restorable_papers_newest_first(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    other_teacher: uuid.UUID,
) -> None:
    older = _paper(sessionmaker_, teacher)
    newer = _paper(sessionmaker_, teacher)
    expired = _paper(sessionmaker_, teacher)
    live = _paper(sessionmaker_, teacher)
    foreign = _paper(sessionmaker_, other_teacher)
    service.delete(str(teacher), str(older))
    service.delete(str(teacher), str(expired))
    service.delete(str(teacher), str(newer))
    service.delete(str(other_teacher), str(foreign))
    _backdate(sessionmaker_, older, timedelta(hours=1))
    _backdate(sessionmaker_, expired, timedelta(days=RETENTION_DAYS, minutes=1))

    rows = service.list_deleted(str(teacher))

    assert [r.paper_id for r in rows] == [newer, older]
    # No metadata and no report: the teacher's own filename, as on the card.
    assert {r.label for r in rows} == {"scan.pdf"}
    assert live not in {r.paper_id for r in rows}
    assert all(r.restore_deadline == restore_deadline(r.deleted_at) for r in rows)
    assert [r.paper_id for r in service.list_deleted(str(other_teacher))] == [foreign]
    assert service.list_deleted("not-a-uuid") == []


# ── the in-flight guard (Task 5a's analogue) ────────────────────────────────


def test_finish_onto_a_deleted_paper_is_refused_and_writes_nothing(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
) -> None:
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing)
    repo.finish(pid, _report(question_ids=("1",)))
    live = _paper_row(sessionmaker_, pid)
    assert live is not None
    assert live.report_json is not None
    assert [i.status for i in _items_of(sessionmaker_, pid)] == [ReviewStatus.open]
    first_report = live.report_json

    service.delete(str(teacher), str(pid))
    with pytest.raises(TeacherPaperDeletedError):
        repo.finish(pid, _report(question_ids=("2", "3")))

    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.report_json == first_report
    assert [i.status for i in _items_of(sessionmaker_, pid)] == [ReviewStatus.withdrawn]


def test_finish_onto_a_purged_paper_is_refused(
    repo: TeacherPaperRepository, sessionmaker_: sessionmaker[Session]
) -> None:
    with pytest.raises(TeacherPaperDeletedError):
        repo.finish(uuid.uuid4(), _report())


def test_a_deleted_paper_cannot_be_claimed(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
) -> None:
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.failed)
    service.delete(str(teacher), str(pid))
    assert repo.claim_run(pid) is False
    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.status is UploadStatus.failed


def test_run_progress_writes_skip_a_deleted_paper(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
) -> None:
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing, report=True)
    repo.set_stage(pid, "extract")
    live = _paper_row(sessionmaker_, pid)
    assert live is not None
    assert live.stage == "extract"

    service.delete(str(teacher), str(pid))
    repo.set_stage(pid, "mark")
    repo.set_progress(pid, 1, 4)
    repo.set_metadata(pid, _metadata())
    repo.set_mark_scheme(pid, _mark_scheme())
    repo.fail(pid, "Grading failed: boom")

    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    # Delete cleared the stage; the in-flight run's "mark" must not land.
    assert row.stage is None
    assert row.progress_index is None
    assert row.metadata_json is None
    assert row.mark_scheme_json is None
    assert row.status is UploadStatus.complete
    assert row.error is None


def test_a_delete_arriving_mid_finish_waits_and_withdraws_the_new_items(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lemely.db import teacher_paper_repo

    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing)
    inside, release = threading.Event(), threading.Event()
    real = teacher_paper_repo._review_items_for

    def paused(paper_id: uuid.UUID, report: object) -> object:
        inside.set()
        assert release.wait(timeout=20)
        return real(paper_id, report)  # type: ignore[arg-type]

    monkeypatch.setattr(teacher_paper_repo, "_review_items_for", paused)
    finishing = _Paused(lambda: repo.finish(pid, _report(question_ids=("1", "2"))))
    assert inside.wait(timeout=20)
    deleting = _Paused(lambda: service.delete(str(teacher), str(pid)))
    _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
    release.set()
    finishing.join()
    deleting.join()

    assert finishing.error is None
    assert deleting.error is None
    assert isinstance(deleting.result, DeletedTeacherPaper)
    items = _items_of(sessionmaker_, pid)
    assert len(items) == 2
    assert {i.status for i in items} == {ReviewStatus.withdrawn}
    assert {i.withdrawn_at for i in items} == {deleting.result.deleted_at}


def test_a_finish_arriving_mid_delete_waits_and_is_refused(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = _paper(sessionmaker_, teacher, status=UploadStatus.processing)
    inside, release = threading.Event(), threading.Event()
    real = TeacherPaperDeletionService._withdraw_console_items

    def paused(
        self: TeacherPaperDeletionService, session: Session, paper_id: uuid.UUID, now: datetime
    ) -> None:
        inside.set()
        assert release.wait(timeout=20)
        real(self, session, paper_id, now)

    monkeypatch.setattr(TeacherPaperDeletionService, "_withdraw_console_items", paused)
    deleting = _Paused(lambda: service.delete(str(teacher), str(pid)))
    assert inside.wait(timeout=20)
    finishing = _Paused(lambda: repo.finish(pid, _report(question_ids=("1",))))
    _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
    release.set()
    deleting.join()
    finishing.join()

    assert deleting.error is None
    assert isinstance(finishing.error, TeacherPaperDeletedError)
    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.deleted_at is not None
    assert row.report_json is None
    assert _items_of(sessionmaker_, pid) == []


def test_a_paper_deleted_mid_grading_ends_the_run_quietly(
    service: TeacherPaperDeletionService,
    repo: TeacherPaperRepository,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker neither writes the report nor records a failure on the deleted row."""
    from lemely.runtime.config import Settings
    from lemely.web.routers import student as student_router
    from lemely.web.routers import teacher as teacher_router
    from lemely.web.services import grading as grading_service
    from tests.storage_fakes import FakeStorageBackend

    pid = _paper(sessionmaker_, teacher, status=UploadStatus.pending)
    repo.set_metadata(pid, _metadata())
    assert repo.claim_run(pid) is True
    row = repo.get(pid)
    assert row is not None
    storage = FakeStorageBackend()
    settings = Settings()
    storage.upload(settings.storage.bucket, row.storage_path, b"%PDF-1.4", "application/pdf")

    def grade_then_delete(*_a: object, **_k: object) -> object:
        service.delete(str(teacher), str(pid))
        return _report(question_ids=("1",))

    monkeypatch.setattr(student_router, "resolve_mark_scheme", lambda *_a, **_k: _mark_scheme())
    monkeypatch.setattr(grading_service, "extract_answers", lambda *_a, **_k: [])
    monkeypatch.setattr(grading_service, "grade_paper", grade_then_delete)

    with structlog.testing.capture_logs() as logs:
        teacher_router._run_grading_job(
            pid,
            settings,
            repo,
            storage,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )

    after = _paper_row(sessionmaker_, pid)
    assert after is not None
    assert after.deleted_at is not None
    assert after.report_json is None
    assert after.error is not None
    assert "Grading failed" not in after.error
    assert _items_of(sessionmaker_, pid) == []
    events = {e["event"]: e["log_level"] for e in logs}
    assert events.get("teacher_grade_paper_deleted") == "info"
    assert "teacher_grade_failed" not in events


# ── a teacher closing an item vs. the paper's deletion ──────────────────────


@pytest.mark.parametrize("action", ["resolve", "dismiss"])
def test_a_close_arriving_mid_delete_is_refused_and_the_item_stays_withdrawn(
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    action: str,
) -> None:
    """The paper row lock is what keeps an item from being both closed and withdrawn.

    Another connection holds the paper ``FOR UPDATE`` as delete does, the close
    must queue on it, and once the deletion commits the close is refused.
    """
    item_id = _item(sessionmaker_, console_paper, reason=ReviewReason.plagiarism_flag)
    reviews = ReviewService(sessionmaker_, ClassService(sessionmaker_))
    now = datetime.now(UTC)

    holder = sessionmaker_()
    holder.begin()
    holder.execute(
        sa.text("SELECT id FROM teacher_papers WHERE id = :id FOR UPDATE"), {"id": console_paper}
    )

    def close() -> object:
        if action == "resolve":
            return reviews.resolve(teacher, Role.teacher, item_id)
        return reviews.dismiss(teacher, Role.teacher, item_id)

    closing = _Paused(close)
    try:
        _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
        holder.execute(
            sa.text("UPDATE teacher_papers SET deleted_at = :now WHERE id = :id"),
            {"now": now, "id": console_paper},
        )
        holder.execute(
            sa.text(
                "UPDATE review_queue SET status = 'withdrawn', withdrawn_at = :now "
                "WHERE teacher_paper_id = :id AND status = 'open'"
            ),
            {"now": now, "id": console_paper},
        )
        holder.commit()
    finally:
        holder.close()
    closing.join()

    assert isinstance(closing.error, ReviewOwnershipError)
    item = _item_row(sessionmaker_, item_id)
    assert item is not None
    assert item.status is ReviewStatus.withdrawn
    assert item.resolved_by is None


def test_a_bulk_approval_racing_a_delete_leaves_the_item_withdrawn(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk approve reads the item open, then waits on the delete's withdrawal of it.

    The real delete is paused after its withdrawal UPDATE, so it holds the item
    row. Once it commits, the approval must re-check the status and skip.
    """
    item_id = _item(sessionmaker_, console_paper)
    reviews = ReviewService(sessionmaker_, ClassService(sessionmaker_))
    inside, release = threading.Event(), threading.Event()
    real = TeacherPaperDeletionService._withdraw_console_items

    def paused(
        self: TeacherPaperDeletionService, session: Session, paper_id: uuid.UUID, now: datetime
    ) -> None:
        real(self, session, paper_id, now)
        inside.set()
        assert release.wait(timeout=20)

    monkeypatch.setattr(TeacherPaperDeletionService, "_withdraw_console_items", paused)
    deleting = _Paused(lambda: service.delete(str(teacher), str(console_paper)))
    assert inside.wait(timeout=20)
    approving = _Paused(lambda: reviews.bulk_approve(teacher, Role.teacher, [item_id]))
    _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
    release.set()
    deleting.join()
    approving.join()

    assert deleting.error is None
    assert approving.error is None
    assert isinstance(approving.result, BulkApproveResult)
    assert approving.result.approved == []
    assert approving.result.skipped == [BulkApproveSkip(item_id=item_id, reason="already_closed")]
    item = _item_row(sessionmaker_, item_id)
    assert item is not None
    assert item.status is ReviewStatus.withdrawn
    assert item.resolved_by is None

    service.restore(str(teacher), str(console_paper))
    reopened = _item_row(sessionmaker_, item_id)
    assert reopened is not None
    assert reopened.status is ReviewStatus.open


def test_a_close_arriving_mid_real_delete_is_refused(
    service: TeacherPaperDeletionService,
    sessionmaker_: sessionmaker[Session],
    teacher: uuid.UUID,
    console_paper: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real delete, paused before it withdraws, must already hold the paper lock."""
    item_id = _item(sessionmaker_, console_paper)
    reviews = ReviewService(sessionmaker_, ClassService(sessionmaker_))
    inside, release = threading.Event(), threading.Event()
    real = TeacherPaperDeletionService._withdraw_console_items

    def paused(
        self: TeacherPaperDeletionService, session: Session, paper_id: uuid.UUID, now: datetime
    ) -> None:
        inside.set()
        assert release.wait(timeout=20)
        real(self, session, paper_id, now)

    monkeypatch.setattr(TeacherPaperDeletionService, "_withdraw_console_items", paused)
    deleting = _Paused(lambda: service.delete(str(teacher), str(console_paper)))
    assert inside.wait(timeout=20)
    closing = _Paused(lambda: reviews.resolve(teacher, Role.teacher, item_id))
    _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
    release.set()
    deleting.join()
    closing.join()

    assert deleting.error is None
    assert isinstance(closing.error, ReviewOwnershipError)
    item = _item_row(sessionmaker_, item_id)
    assert item is not None
    assert item.status is ReviewStatus.withdrawn


def test_a_close_whose_item_a_regrade_replaced_is_a_404(
    sessionmaker_: sessionmaker[Session], teacher: uuid.UUID, console_paper: uuid.UUID
) -> None:
    """A finishing regrade deletes the paper's open items while the close waits on the paper."""
    item_id = _item(sessionmaker_, console_paper)
    reviews = ReviewService(sessionmaker_, ClassService(sessionmaker_))

    holder = sessionmaker_()
    holder.begin()
    holder.execute(
        sa.text("SELECT id FROM teacher_papers WHERE id = :id FOR UPDATE"), {"id": console_paper}
    )
    closing = _Paused(lambda: reviews.resolve(teacher, Role.teacher, item_id))
    try:
        _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
        holder.execute(sa.text("DELETE FROM review_queue WHERE id = :id"), {"id": item_id})
        holder.commit()
    finally:
        holder.close()
    closing.join()

    assert isinstance(closing.error, ReviewNotFoundError)
    assert _item_row(sessionmaker_, item_id) is None


def test_a_close_queued_behind_another_close_reads_the_committed_status(
    sessionmaker_: sessionmaker[Session], teacher: uuid.UUID, console_paper: uuid.UUID
) -> None:
    """The item is read before the paper lock; the status checked must be the one after it."""
    item_id = _item(sessionmaker_, console_paper, reason=ReviewReason.plagiarism_flag)
    reviews = ReviewService(sessionmaker_, ClassService(sessionmaker_))

    holder = sessionmaker_()
    holder.begin()
    holder.execute(
        sa.text("SELECT id FROM teacher_papers WHERE id = :id FOR UPDATE"), {"id": console_paper}
    )
    closing = _Paused(lambda: reviews.dismiss(teacher, Role.teacher, item_id))
    try:
        _wait_until_a_backend_waits_on_a_lock(sessionmaker_)
        holder.execute(
            sa.text(
                "UPDATE review_queue SET status = 'resolved', resolved_by = :by WHERE id = :id"
            ),
            {"by": teacher, "id": item_id},
        )
        holder.commit()
    finally:
        holder.close()
    closing.join()

    assert isinstance(closing.error, ReviewAlreadyClosedError)
    item = _item_row(sessionmaker_, item_id)
    assert item is not None
    assert item.status is ReviewStatus.resolved


# ── purge ───────────────────────────────────────────────────────────────────


def test_purge_removes_the_row_and_both_objects(
    sessionmaker_: sessionmaker[Session], fake_storage: RecordingStorage, teacher: uuid.UUID
) -> None:
    pid = _paper(
        sessionmaker_, teacher, scheme=True, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2)
    )
    item_id = _item(sessionmaker_, pid, status=ReviewStatus.withdrawn, withdrawn_at=NOW)
    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.scheme_storage_path is not None
    assert _item_row(sessionmaker_, item_id) is not None
    fake_storage.upload(BUCKET, row.storage_path, b"scan", "application/pdf")
    fake_storage.upload(BUCKET, row.scheme_storage_path, b"scheme", "application/pdf")

    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 1

    assert sorted(fake_storage.deleted) == sorted(
        [(BUCKET, row.storage_path), (BUCKET, row.scheme_storage_path)]
    )
    assert not fake_storage.holds(row.storage_path)
    assert not fake_storage.holds(row.scheme_storage_path)
    assert _paper_row(sessionmaker_, pid) is None
    assert _item_row(sessionmaker_, item_id) is None


def test_purge_deletes_the_objects_before_the_row(
    sessionmaker_: sessionmaker[Session], teacher: uuid.UUID
) -> None:
    pid = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))
    seen: list[bool] = []
    storage = RecordingStorage(
        on_delete=lambda _b, _p: seen.append(_paper_row(sessionmaker_, pid) is not None)
    )

    assert purge_expired_teacher_papers(sessionmaker_, storage, BUCKET, now=NOW) == 1

    assert seen == [True]
    assert _paper_row(sessionmaker_, pid) is None


def test_purge_without_a_scheme_deletes_only_the_scan(
    sessionmaker_: sessionmaker[Session], fake_storage: RecordingStorage, teacher: uuid.UUID
) -> None:
    pid = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))
    row = _paper_row(sessionmaker_, pid)
    assert row is not None

    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 1
    assert fake_storage.deleted == [(BUCKET, row.storage_path)]


def test_purge_respects_the_shared_retention_and_grace(
    sessionmaker_: sessionmaker[Session], fake_storage: RecordingStorage, teacher: uuid.UUID
) -> None:
    """One number across the product: the student flow's cutoff, not a second constant."""
    inside_grace = _paper(
        sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS, minutes=30)
    )
    past_grace = _paper(
        sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS, hours=2)
    )
    assert purge_cutoff(NOW) < NOW - timedelta(days=RETENTION_DAYS, minutes=30)

    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 1

    assert _paper_row(sessionmaker_, inside_grace) is not None
    assert _paper_row(sessionmaker_, past_grace) is None


def test_purge_leaves_live_and_recent_papers_alone(
    sessionmaker_: sessionmaker[Session], fake_storage: RecordingStorage, teacher: uuid.UUID
) -> None:
    live = _paper(sessionmaker_, teacher)
    recent = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=1))

    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 0

    assert _paper_row(sessionmaker_, live) is not None
    assert _paper_row(sessionmaker_, recent) is not None
    assert fake_storage.deleted == []


def test_a_storage_failure_keeps_the_row(
    sessionmaker_: sessionmaker[Session], teacher: uuid.UUID
) -> None:
    pid = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))

    with structlog.testing.capture_logs() as logs:
        assert purge_expired_teacher_papers(sessionmaker_, FailingStorage(), BUCKET, now=NOW) == 0

    assert _paper_row(sessionmaker_, pid) is not None
    assert any(e["event"] == "purge_teacher_object_delete_failed" for e in logs)
    assert purge_expired_teacher_papers(sessionmaker_, RecordingStorage(), BUCKET, now=NOW) == 1
    assert _paper_row(sessionmaker_, pid) is None


def test_purging_twice_is_a_no_op(
    sessionmaker_: sessionmaker[Session], fake_storage: RecordingStorage, teacher: uuid.UUID
) -> None:
    _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))
    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 1
    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 0


def test_the_oldest_deletion_goes_first_and_the_limit_holds(
    sessionmaker_: sessionmaker[Session], fake_storage: RecordingStorage, teacher: uuid.UUID
) -> None:
    oldest = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 5))
    younger = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))

    assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW, limit=1) == 1

    assert _paper_row(sessionmaker_, oldest) is None
    assert _paper_row(sessionmaker_, younger) is not None


def test_a_replica_that_finds_the_work_done_is_not_an_error(
    sessionmaker_: sessionmaker[Session], teacher: uuid.UUID
) -> None:
    pid = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))
    inner: list[int] = []

    def replica(_bucket: str, _path: str) -> None:
        if not inner:
            inner.append(
                purge_expired_teacher_papers(sessionmaker_, RecordingStorage(), BUCKET, now=NOW)
            )

    with structlog.testing.capture_logs() as logs:
        outer = purge_expired_teacher_papers(
            sessionmaker_, RecordingStorage(on_delete=replica), BUCKET, now=NOW
        )

    assert outer + inner[0] == 1
    assert _paper_row(sessionmaker_, pid) is None
    assert not [e for e in logs if e["log_level"] == "error"]
    assert any(e["event"] == "purge_already_done" for e in logs)


def test_a_paper_that_stops_qualifying_after_the_object_delete_is_kept_and_logged(
    sessionmaker_: sessionmaker[Session], teacher: uuid.UUID
) -> None:
    """Only clock skew past the grace reaches this; the row stays so a person can see it."""
    pid = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))

    def restored(_bucket: str, _path: str) -> None:
        with sessionmaker_.begin() as session:
            session.execute(
                sa.update(TeacherPaper).where(TeacherPaper.id == pid).values(deleted_at=None)
            )

    with structlog.testing.capture_logs() as logs:
        assert (
            purge_expired_teacher_papers(
                sessionmaker_, RecordingStorage(on_delete=restored), BUCKET, now=NOW
            )
            == 0
        )

    row = _paper_row(sessionmaker_, pid)
    assert row is not None
    assert row.deleted_at is None
    assert any(
        e["event"] == "purge_teacher_paper_changed_after_object_delete"
        and e["log_level"] == "error"
        for e in logs
    )


def test_one_papers_database_failure_does_not_stop_the_others(
    sessionmaker_: sessionmaker[Session],
    fake_storage: RecordingStorage,
    teacher: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 5))
    healthy = _paper(sessionmaker_, teacher, deleted_at=NOW - timedelta(days=RETENTION_DAYS + 2))
    real = purge_module._lock_teacher_paper

    def flaky(session: Session, paper_id: uuid.UUID) -> TeacherPaper | None:
        if paper_id == broken:
            raise sa.exc.OperationalError("SELECT", {}, Exception("connection reset"))
        return real(session, paper_id)

    monkeypatch.setattr(purge_module, "_lock_teacher_paper", flaky)
    with structlog.testing.capture_logs() as logs:
        assert purge_expired_teacher_papers(sessionmaker_, fake_storage, BUCKET, now=NOW) == 1

    assert _paper_row(sessionmaker_, broken) is not None
    assert _paper_row(sessionmaker_, healthy) is None
    assert [e["paper_id"] for e in logs if e["event"] == "purge_teacher_paper_failed"] == [
        str(broken)
    ]
