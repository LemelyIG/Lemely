"""Postgres integration tests for :class:`~lemely.db.teacher_paper_repo.TeacherPaperRepository`

(spec 2026-09-03 §4.2). Skip cleanly when no local Postgres is reachable
(mirrors ``test_auth_token_repo.py`` / ``test_db_schema.py``). They prove the
guarantees the design depends on:

* **``claim_run`` is atomic.** Two concurrent callers racing the same paper
  never both win — the database's row lock decides, not a read-then-write in
  this process. A ``processing`` row is reclaimable only once it has gone
  stale (``updated_at`` older than the injected ``stale_after`` window); a
  ``pending``, ``failed`` or ``complete`` row is claimable immediately.
* **Visibility (DS11) is enforced in the query, not filtered afterwards.** The
  uploading teacher and their school's admins can see a paper; a teacher or
  admin from another school cannot, and ``get`` — the worker's read — has no
  visibility filter at all.
* **The NOT NULL and ``ondelete`` behaviours Task 4 left untested** (directed
  addition, see task-5-report.md): ``uploaded_by`` and ``storage_path`` are
  both required, deleting the uploading user cascades the paper away, and
  deleting a student referenced by ``student_id`` nulls that column but
  leaves the paper in place.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeakArea,
    WeaknessReport,
)
from lemely.db.base import Base
from lemely.db.models import School, SchoolMembership, TeacherPaper, User
from lemely.db.models.enums import MembershipRole, Role, UploadStatus
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


# ---------------------------------------------------------------------------
# Builders (real core objects — nothing fabricated).
# ---------------------------------------------------------------------------


def _user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as s:
        s.add(User(id=uid, email=f"{uid.hex}@example.com", role=role))
    return uid


def _school_with(
    sm: sessionmaker[Session], *, admin: uuid.UUID, teachers: list[uuid.UUID]
) -> uuid.UUID:
    sid = uuid.uuid4()
    with sm.begin() as s:
        s.add(School(id=sid, name=f"School {sid.hex[:6]}"))
        s.flush()
        s.add(
            SchoolMembership(
                school_id=sid, user_id=admin, membership_role=MembershipRole.school_admin
            )
        )
        for t in teachers:
            s.add(
                SchoolMembership(school_id=sid, user_id=t, membership_role=MembershipRole.teacher)
            )
    return sid


def _repo(sm: sessionmaker[Session], *, stale_seconds: int = 900) -> TeacherPaperRepository:
    return TeacherPaperRepository(sm, stale_after=timedelta(seconds=stale_seconds))


def _paper(repo: TeacherPaperRepository, owner: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    repo.create(
        paper_id=pid,
        uploaded_by=owner,
        storage_path=f"teacher/{owner}/{pid.hex}/scan.pdf",
        scheme_storage_path=None,
        original_filename="scan.pdf",
        content_type="application/pdf",
        byte_size=3,
    )
    return pid


def _metadata(subject_code: str = "0625", paper_number: int = 3) -> ExamMetadata:
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=paper_number,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _report(
    *,
    awarded: int = 7,
    maximum: int = 10,
    confidence_score: float = 0.6,
    needs_review: bool = True,
    topic: str = "Moments",
    grade: str = "D",
    question_ids: tuple[str, ...] = ("5b",),
) -> AccuracyReport:
    """Build a real ``AccuracyReport``, copied from ``tests/test_web_teacher.py``'s

    helper of the same name, with the default ``awarded`` raised from 2 to 7
    (and ``maximum`` from 4 to 10, so ``awarded <= maximum`` still validates)
    so that ``_report()``'s default totals to ``correction.awarded_marks == 7``
    per the brief.
    """
    questions = [
        CorrectedQuestion(
            question_id=question_id,
            awarded_marks=awarded,
            maximum_marks=maximum,
            confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
            confidence_score=confidence_score,
            needs_teacher_review=needs_review,
            marker_source="ai",
            topic=topic,
        )
        for question_id in question_ids
    ]
    count = len(question_ids)
    correction = CorrectionResult(metadata=_metadata(), questions=questions)
    weaknesses = WeaknessReport(
        weak_areas=[
            WeakArea(
                topic=topic,
                lost_marks=(maximum - awarded) * count,
                maximum_marks=maximum * count,
                accuracy=awarded / maximum,
                question_ids=list(question_ids),
            )
        ],
        needs_teacher_review=needs_review,
    )
    prediction = GradePrediction(
        awarded_marks=awarded * count,
        maximum_marks=maximum * count,
        percentage=round(awarded / maximum * 100, 2),
        grade=grade,
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=needs_review,
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


# ---------------------------------------------------------------------------
# claim_run: atomicity.
# ---------------------------------------------------------------------------


def test_exactly_one_of_two_concurrent_claims_wins(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    pid = _paper(repo, _user(pg_sessionmaker, Role.teacher))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.claim_run(pid), range(2)))
    assert sorted(results) == [False, True]


def test_processing_row_cannot_be_reclaimed_until_stale(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    repo = _repo(pg_sessionmaker, stale_seconds=60)
    pid = _paper(repo, _user(pg_sessionmaker, Role.teacher))
    assert repo.claim_run(pid) is True
    assert repo.claim_run(pid) is False
    with pg_sessionmaker.begin() as s:
        s.execute(
            sa.update(TeacherPaper)
            .where(TeacherPaper.id == pid)
            .values(updated_at=datetime.now(UTC) - timedelta(seconds=120))
        )
    assert repo.claim_run(pid) is True


def test_finished_and_failed_rows_can_be_reclaimed(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    pid = _paper(repo, _user(pg_sessionmaker, Role.teacher))
    assert repo.claim_run(pid)
    repo.fail(pid, "boom")
    assert repo.claim_run(pid)
    repo.finish(pid, _report())
    assert repo.claim_run(pid)


# ---------------------------------------------------------------------------
# Visibility (DS11).
# ---------------------------------------------------------------------------


def test_visibility_matrix(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    t1, t2, t3 = (_user(pg_sessionmaker, Role.teacher) for _ in range(3))
    admin_a = _user(pg_sessionmaker, Role.school_admin)
    admin_b = _user(pg_sessionmaker, Role.school_admin)
    platform = _user(pg_sessionmaker, Role.platform_admin)
    _school_with(pg_sessionmaker, admin=admin_a, teachers=[t1, t2])
    _school_with(pg_sessionmaker, admin=admin_b, teachers=[t3])
    p1, p2, p3 = (_paper(repo, t) for t in (t1, t2, t3))

    ids = lambda rows: {r.id for r in rows}  # noqa: E731
    assert ids(repo.list_visible(viewer_id=t1, viewer_role=Role.teacher)) == {p1}
    assert ids(repo.list_visible(viewer_id=admin_a, viewer_role=Role.school_admin)) == {p1, p2}
    assert ids(repo.list_visible(viewer_id=admin_b, viewer_role=Role.school_admin)) == {p3}
    assert ids(repo.list_visible(viewer_id=platform, viewer_role=Role.platform_admin)) == {
        p1,
        p2,
        p3,
    }
    assert repo.get_visible(p3, viewer_id=admin_a, viewer_role=Role.school_admin) is None
    assert repo.get_visible(p1, viewer_id=t1, viewer_role=Role.teacher) is not None
    # The worker reads without a viewer: it is not a person, it is the run.
    assert repo.get(p3) is not None
    assert repo.get(uuid.uuid4()) is None


def test_progress_and_report_round_trip(pg_sessionmaker: sessionmaker[Session]) -> None:
    repo = _repo(pg_sessionmaker)
    owner = _user(pg_sessionmaker, Role.teacher)
    pid = _paper(repo, owner)
    repo.claim_run(pid)
    repo.set_stage(pid, "mark")
    repo.set_progress(pid, 3, 12)
    row = repo.get_visible(pid, viewer_id=owner, viewer_role=Role.teacher)
    assert row is not None and row.stage == "mark" and row.progress == (3, 12)
    assert row.status is UploadStatus.processing and row.stale is False
    repo.finish(pid, _report())
    row = repo.get_visible(pid, viewer_id=owner, viewer_role=Role.teacher)
    assert row is not None and row.status is UploadStatus.complete
    assert row.report is not None and row.report.correction.awarded_marks == 7


# ---------------------------------------------------------------------------
# Directed additions (per task-5-report.md): Task 4's schema test never
# exercised the NOT NULL columns or the FK ondelete behaviours this
# repository depends on. Added here, against real Postgres, at the
# orchestrator's explicit request rather than the brief.
# ---------------------------------------------------------------------------


def test_uploaded_by_is_not_nullable(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pg_sessionmaker() as session, pytest.raises(IntegrityError):
        session.add(TeacherPaper(uploaded_by=None, storage_path="teacher/none/x/scan.pdf"))  # type: ignore[arg-type]
        session.commit()


def test_storage_path_is_not_nullable(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _user(pg_sessionmaker, Role.teacher)
    with pg_sessionmaker() as session, pytest.raises(IntegrityError):
        session.add(TeacherPaper(uploaded_by=owner, storage_path=None))  # type: ignore[arg-type]
        session.commit()


def test_deleting_the_uploader_cascades_the_paper(pg_sessionmaker: sessionmaker[Session]) -> None:
    """``uploaded_by`` is ``ON DELETE CASCADE`` — the paper cannot outlive its owner."""
    repo = _repo(pg_sessionmaker)
    owner = _user(pg_sessionmaker, Role.teacher)
    pid = _paper(repo, owner)

    with pg_sessionmaker.begin() as s:
        s.execute(sa.delete(User).where(User.id == owner))

    with pg_sessionmaker() as s:
        assert s.get(TeacherPaper, pid) is None


def test_deleting_the_student_nulls_student_id_and_keeps_the_paper(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``student_id`` is ``ON DELETE SET NULL`` — unlike ``uploaded_by``, the paper survives."""
    repo = _repo(pg_sessionmaker)
    owner = _user(pg_sessionmaker, Role.teacher)
    student = _user(pg_sessionmaker, Role.student)
    pid = _paper(repo, owner)
    with pg_sessionmaker.begin() as s:
        s.execute(sa.update(TeacherPaper).where(TeacherPaper.id == pid).values(student_id=student))

    with pg_sessionmaker.begin() as s:
        s.execute(sa.delete(User).where(User.id == student))

    with pg_sessionmaker() as s:
        row = s.get(TeacherPaper, pid)
        assert row is not None
        assert row.student_id is None


def test_no_orm_relationship_between_teacher_paper_and_user(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Confirms the carry-forward from Task 4's review: no ``relationship()`` exists.

    Both FK columns must be queried directly (as this repository's ``get``/
    ``get_visible``/``list_visible`` and ``_visible`` all do) rather than
    through an ORM-level relationship attribute in either direction, because
    none was added to the model. This asserts the mapper's own configuration
    rather than merely failing to call a nonexistent attribute, so it fails
    loudly if a future change quietly adds one.
    """
    mapper = sa.inspect(TeacherPaper)
    assert set(mapper.relationships.keys()) == set()

    user_mapper = sa.inspect(User)
    assert not any(rel.mapper.class_ is TeacherPaper for rel in user_mapper.relationships), (
        "User must not gain a relationship() to TeacherPaper without a controller decision"
    )

    # And the row itself is reachable only via the FK column value, never a
    # convenience attribute — proven against a live row, not just the mapper.
    owner = _user(pg_sessionmaker, Role.teacher)
    pid = _paper(_repo(pg_sessionmaker), owner)
    with pg_sessionmaker() as s:
        paper = s.get(TeacherPaper, pid)
        assert paper is not None
        assert paper.uploaded_by == owner
        assert not hasattr(TeacherPaper, "uploader")
        assert not hasattr(TeacherPaper, "student")
