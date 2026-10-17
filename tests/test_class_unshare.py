"""Route tests for unsharing a paper from one class (D9, design §5, R3/R8/R9).

``POST /api/classes/{class_id}/papers/{attempt_id}/unshare`` hides one attempt
from one class's view and analytics; ``DELETE`` on the same path reshares it.
The student's own surfaces are never touched, and the review queue changes
only as a *read filter* — no :class:`ReviewQueueItem` is ever written.

Every dependency is overridden onto a throwaway Postgres database, and the
history store is the DB-backed :class:`DbHistoryStore`: the JSON file store's
records carry ``attempt_id=None`` and so can never be excluded, which would
make every "the average moved" assertion here vacuous.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeaknessReport,
)
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_exclusion_repo import ClassExclusionRepository
from lemely.db.class_repo import ClassService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import ClassPaperExclusion, User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import ReviewStatus, Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import ReviewService
from lemely.db.self_review_repo import SelfReviewService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_at_risk_ack_service,
    get_auth_context,
    get_class_exclusion_repository,
    get_class_service,
    get_history_store,
    get_review_service,
    get_self_review_service,
    get_student_profile_service,
    get_user_mirror,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


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
    """A sessionmaker bound to a throwaway Postgres DB; skips if unreachable."""
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


class _SessionUserMirror:
    """Just enough of :class:`~lemely.auth.mirror.UserMirror` for the overview route."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        with self._sm() as session:
            return session.get(User, user_id)


@dataclass
class World:
    """One seeded school of actors, sharing a single app bound to one DB."""

    client: TestClient
    sm: sessionmaker[Session]
    class_service: ClassService
    teacher: uuid.UUID
    student: uuid.UUID
    class_id: uuid.UUID
    earlier_attempt: uuid.UUID
    latest_attempt: uuid.UUID
    open_item: uuid.UUID

    def act_as(self, user_id: uuid.UUID, role: Role) -> None:
        self.client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
            user_id=str(user_id), role=role.value
        )

    def unshare_path(self, attempt_id: uuid.UUID | str, class_id: uuid.UUID | None = None) -> str:
        return f"/api/classes/{class_id or self.class_id}/papers/{attempt_id}/unshare"

    def average(self, class_id: uuid.UUID | None = None) -> float | None:
        """``ClassSummaryDTO.average`` — the mean of each student's latest paper."""
        self.act_as(self.teacher, Role.teacher)
        classes = self.client.get("/api/teacher/classes").json()["classes"]
        target = str(class_id or self.class_id)
        average: float | None = next(c for c in classes if c["id"] == target)["average"]
        return average

    def queue_item_ids(self, as_user: uuid.UUID, **params: str) -> set[str]:
        self.act_as(as_user, Role.teacher)
        resp = self.client.get("/api/teacher/review", params=params)
        assert resp.status_code == 200, resp.text
        return {item["itemId"] for item in resp.json()["items"]}

    def exclusion_rows(self) -> list[ClassPaperExclusion]:
        with self.sm() as session:
            return list(session.scalars(sa.select(ClassPaperExclusion)).all())

    def seed_user(self, role: Role, display_name: str | None = None) -> uuid.UUID:
        return _seed_user(self.sm, role, display_name)

    def enrol_in_new_class(self, teacher: uuid.UUID, student: uuid.UUID, name: str) -> uuid.UUID:
        cls = self.class_service.create_class(teacher, name)
        assert cls.join_code is not None
        self.class_service.join_by_code(student, cls.join_code)
        return cls.class_id


def _seed_user(sm: sessionmaker[Session], role: Role, display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _metadata() -> ExamMetadata:
    return ExamMetadata(
        subject_code="0625",
        paper_number=3,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _report(*, awarded: int, flagged: bool) -> AccuracyReport:
    """A one-question, two-mark paper; ``flagged`` earns it an open review item."""
    question = CorrectedQuestion(
        question_id="1",
        awarded_marks=awarded,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW if flagged else ConfidenceBand.HIGH,
        confidence_score=0.3 if flagged else 1.0,
        needs_teacher_review=flagged,
        student_answer="answer",
        expected_answer="expected",
        topic="Waves",
        marker_source="ai",
        matched_point_ids=["p1"] if awarded else [],
    )
    correction = CorrectionResult(metadata=_metadata(), questions=[question])
    pct = round(awarded / 2 * 100.0, 2)
    prediction = GradePrediction(
        awarded_marks=awarded,
        maximum_marks=2,
        percentage=pct,
        grade="A" if awarded else "U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=flagged,
        boundary_source="global_default",
    )
    return AccuracyReport(
        correction=correction, weaknesses=WeaknessReport(weak_areas=[]), grade_prediction=prediction
    )


@pytest.fixture
def world(pg_sessionmaker: sessionmaker[Session]) -> Iterator[World]:
    """A teacher's class with one student who has two papers.

    The earlier paper scores 100%; the *latest* scores 0% and carries an open
    review item. The class average is the mean of each student's latest paper,
    so unsharing the latest one is what moves it (to 100) — unsharing the
    earlier one would leave it where it is, and prove nothing.
    """
    sm = pg_sessionmaker
    class_service = ClassService(sm)
    teacher = _seed_user(sm, Role.teacher)
    student = _seed_user(sm, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    attempts = AttemptRepository(sm)
    earlier = attempts.persist_correction(
        user_id=str(student),
        report=_report(awarded=2, flagged=False),
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    latest = attempts.persist_correction(
        user_id=str(student),
        report=_report(awarded=0, flagged=True),
        recorded_at="2026-02-01T00:00:00+00:00",
    )
    with sm() as session:
        item = session.scalars(
            sa.select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == latest)
        ).one()

    app = create_app()
    app.dependency_overrides[get_class_service] = lambda: class_service
    app.dependency_overrides[get_history_store] = lambda: DbHistoryStore(sm)
    app.dependency_overrides[get_class_exclusion_repository] = lambda: ClassExclusionRepository(sm)
    app.dependency_overrides[get_at_risk_ack_service] = lambda: AtRiskAckService(sm, class_service)
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(sm)
    app.dependency_overrides[get_review_service] = lambda: ReviewService(sm, class_service)
    app.dependency_overrides[get_self_review_service] = lambda: SelfReviewService(sm, judge=None)
    app.dependency_overrides[get_user_mirror] = lambda: _SessionUserMirror(sm)
    yield World(
        client=TestClient(app),
        sm=sm,
        class_service=class_service,
        teacher=teacher,
        student=student,
        class_id=cls.class_id,
        earlier_attempt=earlier,
        latest_attempt=latest,
        open_item=item.id,
    )
    app.dependency_overrides.clear()


def _student_view(world: World) -> tuple[Any, Any]:
    """The student's overview and latest result screen, as their own client sees them."""
    world.act_as(world.student, Role.student)
    overview = world.client.get("/api/student/overview")
    questions = world.client.get(f"/api/student/attempts/{world.latest_attempt}/questions")
    assert overview.status_code == 200, overview.text
    assert questions.status_code == 200, questions.text
    return overview.json(), questions.json()


# ---------------------------------------------------------------------------
# The class view moves; the student's own view does not.
# ---------------------------------------------------------------------------


def test_unshare_changes_the_class_average_and_leaves_the_student_untouched(
    world: World,
) -> None:
    """Both halves in one test. Without the inequality the equality proves nothing."""
    student_before = _student_view(world)
    average_before = world.average()
    assert average_before == 0.0  # the latest (0%) paper is what the class sees

    world.act_as(world.teacher, Role.teacher)
    assert world.client.post(world.unshare_path(world.latest_attempt)).status_code == 204

    assert world.average() == 100.0  # falls back to the still-shared earlier paper
    assert world.average() != average_before
    assert _student_view(world) == student_before


def test_reshare_restores_the_average(world: World) -> None:
    before = world.average()
    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))
    assert world.average() != before

    world.act_as(world.teacher, Role.teacher)
    assert world.client.delete(world.unshare_path(world.latest_attempt)).status_code == 204
    assert world.average() == before
    assert world.exclusion_rows() == []


def test_unshare_records_who_excluded_it(world: World) -> None:
    """``excluded_by`` is the only trace a teacher removed a flagged paper (design §5)."""
    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    [row] = world.exclusion_rows()
    assert (row.class_id, row.attempt_id, row.excluded_by) == (
        world.class_id,
        world.latest_attempt,
        world.teacher,
    )


def test_unsharing_twice_is_idempotent(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    assert world.client.post(world.unshare_path(world.latest_attempt)).status_code == 204
    assert world.client.post(world.unshare_path(world.latest_attempt)).status_code == 204
    assert len(world.exclusion_rows()) == 1


def test_resharing_a_paper_that_was_never_unshared_is_a_no_op(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    assert world.client.delete(world.unshare_path(world.latest_attempt)).status_code == 204
    assert world.exclusion_rows() == []


def test_unshare_in_one_class_leaves_another_classs_average_alone(world: World) -> None:
    """Per-class grain (D9): the same student in a second class still counts there."""
    class_b = world.enrol_in_new_class(world.teacher, world.student, "Physics 10B")
    assert world.average(class_b) == 0.0

    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    assert world.average() == 100.0
    assert world.average(class_b) == 0.0


# ---------------------------------------------------------------------------
# Authorization and validation — every refusal writes no row.
# ---------------------------------------------------------------------------


def test_a_teacher_of_another_class_is_refused(world: World) -> None:
    """A foreign class is 403 via the class routes' existing scope check."""
    other_teacher = world.seed_user(Role.teacher)
    world.act_as(other_teacher, Role.teacher)
    for method in ("post", "delete"):
        resp = getattr(world.client, method)(world.unshare_path(world.latest_attempt))
        assert resp.status_code == 403
    assert world.exclusion_rows() == []


def test_a_student_cannot_unshare(world: World) -> None:
    world.act_as(world.student, Role.student)
    assert world.client.post(world.unshare_path(world.latest_attempt)).status_code == 403
    assert world.exclusion_rows() == []


def test_a_platform_admin_cannot_unshare(world: World) -> None:
    admin = world.seed_user(Role.platform_admin)
    world.act_as(admin, Role.platform_admin)
    assert world.client.post(world.unshare_path(world.latest_attempt)).status_code == 403
    assert world.exclusion_rows() == []


def test_an_unknown_attempt_is_404_and_never_reaches_the_foreign_key(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    for method in ("post", "delete"):
        resp = getattr(world.client, method)(world.unshare_path(uuid.uuid4()))
        assert resp.status_code == 404
    assert world.exclusion_rows() == []


def test_an_unknown_class_is_404(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    resp = world.client.post(world.unshare_path(world.latest_attempt, class_id=uuid.uuid4()))
    assert resp.status_code == 404
    assert world.exclusion_rows() == []


def test_a_malformed_attempt_id_is_422(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    assert world.client.post(world.unshare_path("not-a-uuid")).status_code == 422
    assert world.exclusion_rows() == []


def test_an_attempt_of_a_student_not_on_the_roster_is_404(world: World) -> None:
    """Another school's student: the attempt exists, but not in this class."""
    outsider_teacher = world.seed_user(Role.teacher)
    outsider = world.seed_user(Role.student)
    world.enrol_in_new_class(outsider_teacher, outsider, "Elsewhere")
    foreign_attempt = AttemptRepository(world.sm).persist_correction(
        user_id=str(outsider), report=_report(awarded=1, flagged=False)
    )

    world.act_as(world.teacher, Role.teacher)
    for method in ("post", "delete"):
        resp = getattr(world.client, method)(world.unshare_path(foreign_attempt))
        assert resp.status_code == 404
    assert world.exclusion_rows() == []


def test_a_deleted_attempt_is_404(world: World) -> None:
    """A soft-deleted paper is gone to every reader, the unshare check included."""
    with world.sm.begin() as session:
        session.execute(
            sa.update(Attempt)
            .where(Attempt.id == world.latest_attempt)
            .values(deleted_at=sa.func.now())
        )
    world.act_as(world.teacher, Role.teacher)
    assert world.client.post(world.unshare_path(world.latest_attempt)).status_code == 404
    assert world.exclusion_rows() == []


# ---------------------------------------------------------------------------
# The review queue: a read filter (R3), per class across the caller's classes (R8).
# ---------------------------------------------------------------------------


def test_unshare_removes_the_item_from_that_classs_queue(world: World) -> None:
    """R3: the queue is class-scoped, so an unshared paper leaves it."""
    assert str(world.open_item) in world.queue_item_ids(world.teacher)  # present first

    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    assert str(world.open_item) not in world.queue_item_ids(world.teacher)
    assert str(world.open_item) not in world.queue_item_ids(
        world.teacher, class_id=str(world.class_id)
    )


def test_unshare_does_not_mutate_the_items_status(world: World) -> None:
    """It is filtered out, not withdrawn.

    `withdrawn` means a student deleted the subject, and it is excluded from
    D8's lifting set (R4a). Setting it here would both lie about what happened
    and entangle a teacher's reversible toggle with the integrity hold.
    """
    with world.sm() as session:
        before = session.get(ReviewQueueItem, world.open_item)
        assert before is not None
        snapshot = (before.status, before.created_at, before.resolved_by, before.resolved_at)

    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    with world.sm() as session:
        after = session.get(ReviewQueueItem, world.open_item)
        assert after is not None
        assert after.status is ReviewStatus.open
        assert (after.status, after.created_at, after.resolved_by, after.resolved_at) == snapshot


def test_resharing_returns_the_item_to_the_queue_unchanged(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))
    assert str(world.open_item) not in world.queue_item_ids(world.teacher)

    world.act_as(world.teacher, Role.teacher)
    world.client.delete(world.unshare_path(world.latest_attempt))
    assert str(world.open_item) in world.queue_item_ids(world.teacher)


def test_the_item_stays_while_another_of_the_teachers_classes_still_shares_it(
    world: World,
) -> None:
    """R8: unshared in class A but still shared via class B, the item stays."""
    class_b = world.enrol_in_new_class(world.teacher, world.student, "Physics 10B")

    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    assert str(world.open_item) in world.queue_item_ids(world.teacher)
    # Narrowed to one class, each class sees its own sharing state.
    assert str(world.open_item) not in world.queue_item_ids(
        world.teacher, class_id=str(world.class_id)
    )
    assert str(world.open_item) in world.queue_item_ids(world.teacher, class_id=str(class_b))

    # Unshared from every class of theirs that rosters the student: now it leaves.
    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt, class_id=class_b))
    assert str(world.open_item) not in world.queue_item_ids(world.teacher)


def test_another_teachers_class_still_shows_the_item(world: World) -> None:
    """Exclusion is per class, so a second teacher's class teaching this student is unaffected."""
    other_teacher = world.seed_user(Role.teacher)
    world.enrol_in_new_class(other_teacher, world.student, "Chemistry 10A")

    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    assert str(world.open_item) in world.queue_item_ids(other_teacher)


# ---------------------------------------------------------------------------
# GET /classes/{class_id}/papers — visible unshared state (controller
# addition, Task 13's review: an unshare with no matching visibility).
# ---------------------------------------------------------------------------


def _papers(world: World) -> list[dict[str, Any]]:
    world.act_as(world.teacher, Role.teacher)
    resp = world.client.get(f"/api/classes/{world.class_id}/papers")
    assert resp.status_code == 200, resp.text
    return resp.json()["papers"]


def test_lists_every_rostered_students_papers_unshared_false_by_default(world: World) -> None:
    rows = _papers(world)
    ids = {r["attemptId"] for r in rows}
    assert ids == {str(world.earlier_attempt), str(world.latest_attempt)}
    assert all(r["unshared"] is False for r in rows)


def test_an_unshared_paper_stays_listed_but_flips_unshared_true(world: World) -> None:
    """The whole point of this route: unsharing must not make the row vanish."""
    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))

    rows = _papers(world)
    ids = {r["attemptId"] for r in rows}
    assert ids == {str(world.earlier_attempt), str(world.latest_attempt)}
    by_id = {r["attemptId"]: r["unshared"] for r in rows}
    assert by_id[str(world.latest_attempt)] is True
    assert by_id[str(world.earlier_attempt)] is False


def test_reshare_flips_unshared_back_to_false(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    world.client.post(world.unshare_path(world.latest_attempt))
    world.client.delete(world.unshare_path(world.latest_attempt))

    rows = _papers(world)
    by_id = {r["attemptId"]: r["unshared"] for r in rows}
    assert by_id[str(world.latest_attempt)] is False


def test_carries_the_student_identity_for_each_row(world: World) -> None:
    rows = _papers(world)
    assert all(r["studentId"] == str(world.student) for r in rows)
    assert all(r["studentName"] == "Amelia" for r in rows)


def test_a_platform_admin_cannot_read_the_class_papers_route(world: World) -> None:
    admin = world.seed_user(Role.platform_admin)
    world.act_as(admin, Role.platform_admin)
    resp = world.client.get(f"/api/classes/{world.class_id}/papers")
    assert resp.status_code == 403


def test_a_student_cannot_read_the_class_papers_route(world: World) -> None:
    world.act_as(world.student, Role.student)
    resp = world.client.get(f"/api/classes/{world.class_id}/papers")
    assert resp.status_code == 403


def test_an_unknown_class_is_404_for_the_papers_route(world: World) -> None:
    world.act_as(world.teacher, Role.teacher)
    resp = world.client.get(f"/api/classes/{uuid.uuid4()}/papers")
    assert resp.status_code == 404


def test_a_teacher_of_another_class_is_refused_the_papers_route(world: World) -> None:
    """Same 403 the unshare routes' own foreign-class test proves (D3.1's scope check)."""
    other_teacher = world.seed_user(Role.teacher)
    world.act_as(other_teacher, Role.teacher)
    resp = world.client.get(f"/api/classes/{world.class_id}/papers")
    assert resp.status_code == 403


def test_a_soft_deleted_attempt_is_excluded_from_the_papers_route(world: World) -> None:
    """Presence, then soft-delete, then absent — the loader criterion (T3) hides it here too."""
    ids_before = {r["attemptId"] for r in _papers(world)}
    assert str(world.latest_attempt) in ids_before

    with world.sm.begin() as session:
        session.execute(
            sa.update(Attempt)
            .where(Attempt.id == world.latest_attempt)
            .values(deleted_at=sa.func.now())
        )

    ids_after = {r["attemptId"] for r in _papers(world)}
    assert str(world.latest_attempt) not in ids_after
    assert str(world.earlier_attempt) in ids_after
