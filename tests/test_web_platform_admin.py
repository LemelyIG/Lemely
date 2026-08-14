"""Platform-admin console (UI spec X-01/X-02/X-03) — service + HTTP, on Postgres.

``tests/test_authz_matrix_complete.py`` proves the role gate: these five routes
are ``platform_admin``-only and every other role, ``school_admin`` included, gets
a 403. This file proves the numbers behind them are counted rather than derived,
which is the property that matters on a console whose reader is the last person
in the chain.

The cases chosen are the ones where a reasonable implementation would be wrong
in a way nobody would notice:

* **Quiz attempts are not marking throughput.** They are ``Attempt`` rows too.
* **A zero is a counted zero.** ``uploadsByStatus`` carries every status,
  including the ones with no rows, so "no failures" is never inferred from a
  missing key.
* **A rejection is not a cancellation.** Migration ``0019`` exists for this.
* **A decided subscription cannot be decided again.** Two admins working one
  queue is the ordinary case, so the second click is refused, not applied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.admin_repo import (
    PlatformAdminService,
    SubscriptionAlreadyDecidedError,
    SubscriptionNotFoundError,
)
from lemely.db.base import Base
from lemely.db.models import (
    Attempt,
    MarkScheme,
    Paper,
    ReviewQueueItem,
    Subject,
    Subscription,
    Upload,
    User,
)
from lemely.db.models.billing import PlanTier
from lemely.db.models.enums import (
    AttemptOrigin,
    BoundarySource,
    ReviewReason,
    ReviewStatus,
    Role,
    SessionMonth,
    SubscriptionStatus,
    UploadStatus,
)
from lemely.runtime.config import DatabaseSettings
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_platform_admin_service

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
    """A throwaway database, dropped afterwards (mirrors ``test_seat_repo.py``)."""
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


# ── Seeding helpers ───────────────────────────────────────────────────────────


def _user(
    sm: sessionmaker[Session], role: Role, *, created_at: datetime | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        user = User(id=uid, email=f"{uid}@example.com", role=role, display_name=role.value)
        if created_at is not None:
            user.created_at = created_at
        session.add(user)
    return uid


def _attempt(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    when: datetime,
    origin: AttemptOrigin = AttemptOrigin.past_paper,
    boundary: BoundarySource | None = BoundarySource.exact,
) -> None:
    with sm.begin() as session:
        session.add(
            Attempt(
                user_id=student_id,
                awarded_marks=40,
                maximum_marks=50,
                percentage=80.0,
                recorded_at=when,
                origin=origin,
                boundary_source=boundary,
            )
        )


def _upload(sm: sessionmaker[Session], user_id: uuid.UUID, status: UploadStatus) -> uuid.UUID:
    upload_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Upload(id=upload_id, user_id=user_id, storage_path=f"{upload_id}.pdf", status=status)
        )
    return upload_id


def _plan(sm: sessionmaker[Session], code: str = "student_monthly") -> uuid.UUID:
    plan_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=plan_id,
                code=code,
                name="Student monthly",
                price_minor=9900,
                currency="EGP",
            )
        )
    return plan_id


def _subscription(
    sm: sessionmaker[Session],
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    status: SubscriptionStatus = SubscriptionStatus.inactive,
    created_at: datetime | None = None,
) -> uuid.UUID:
    subscription_id = uuid.uuid4()
    with sm.begin() as session:
        subscription = Subscription(
            id=subscription_id, user_id=user_id, plan_tier_id=plan_id, status=status
        )
        if created_at is not None:
            subscription.created_at = created_at
        session.add(subscription)
    return subscription_id


def _paper_with_scheme(sm: sessionmaker[Session], *, variant: int, with_scheme: bool) -> None:
    with sm.begin() as session:
        # `subjects.code` is a unique column, not the primary key, so this is a
        # lookup by code rather than `session.get`.
        existing = session.scalars(sa.select(Subject).where(Subject.code == "0625")).first()
        if existing is None:
            session.add(Subject(code="0625", name="Physics"))
    paper_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Paper(
                id=paper_id,
                subject_code="0625",
                session_month=SessionMonth.may_june,
                session_year=2024,
                paper_number=4,
                paper_variant=variant,
            )
        )
        if with_scheme:
            session.add(MarkScheme(paper_id=paper_id, maximum_mark=80, parsed_payload={}))


def _client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    service = PlatformAdminService(sm)
    app = create_app()
    app.dependency_overrides[get_platform_admin_service] = lambda: service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(uuid.uuid4()), role=Role.platform_admin.value
    )
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


# ── X-01: counts ──────────────────────────────────────────────────────────────


def test_counts_report_every_role_separately(pg_sessionmaker: sessionmaker[Session]) -> None:
    _user(pg_sessionmaker, Role.student)
    _user(pg_sessionmaker, Role.student)
    _user(pg_sessionmaker, Role.parent)
    _user(pg_sessionmaker, Role.teacher)
    _user(pg_sessionmaker, Role.school_admin)
    _user(pg_sessionmaker, Role.platform_admin)

    counts = PlatformAdminService(pg_sessionmaker).counts()

    assert (counts.students, counts.parents, counts.teachers) == (2, 1, 1)
    assert (counts.school_admins, counts.platform_admins) == (1, 1)


def test_marking_throughput_excludes_quiz_attempts_and_respects_its_windows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A quiz submission is an ``Attempt`` row the marking pipeline never ran."""
    student = _user(pg_sessionmaker, Role.student)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    _attempt(pg_sessionmaker, student, when=now - timedelta(hours=2))
    _attempt(pg_sessionmaker, student, when=now - timedelta(days=3))
    _attempt(pg_sessionmaker, student, when=now - timedelta(days=30))
    # Two quizzes inside the 24-hour window: neither is marking throughput.
    _attempt(pg_sessionmaker, student, when=now, origin=AttemptOrigin.quiz, boundary=None)
    _attempt(pg_sessionmaker, student, when=now, origin=AttemptOrigin.quiz, boundary=None)

    counts = PlatformAdminService(pg_sessionmaker).counts(now=now)

    assert counts.papers_marked_last_24_hours == 1
    assert counts.papers_marked_last_7_days == 2
    assert counts.papers_marked_total == 3


def test_uploads_by_status_carries_the_zeroes(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A missing key would let the screen read "no failures" off an absent entry."""
    student = _user(pg_sessionmaker, Role.student)
    _upload(pg_sessionmaker, student, UploadStatus.complete)

    counts = PlatformAdminService(pg_sessionmaker).counts()

    assert counts.uploads_by_status == {
        "pending": 0,
        "processing": 0,
        "complete": 1,
        "failed": 0,
    }


def test_open_review_depth_counts_only_open_items(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _user(pg_sessionmaker, Role.student)
    now = datetime.now(UTC)
    with pg_sessionmaker.begin() as session:
        attempt = Attempt(
            user_id=student,
            awarded_marks=1,
            maximum_marks=2,
            percentage=50.0,
            recorded_at=now,
            origin=AttemptOrigin.past_paper,
        )
        session.add(attempt)
        session.flush()
        session.add(
            ReviewQueueItem(
                attempt_id=attempt.id,
                reason=ReviewReason.low_confidence,
                status=ReviewStatus.open,
            )
        )
        session.add(
            ReviewQueueItem(
                attempt_id=attempt.id,
                reason=ReviewReason.manual,
                status=ReviewStatus.resolved,
            )
        )

    assert PlatformAdminService(pg_sessionmaker).counts().open_review_items == 1


def test_recent_signups_are_newest_first_and_include_every_role(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    _user(pg_sessionmaker, Role.student, created_at=base)
    newest = _user(pg_sessionmaker, Role.teacher, created_at=base + timedelta(days=2))

    rows = PlatformAdminService(pg_sessionmaker).recent_signups(limit=5)

    assert rows[0].user_id == newest
    assert rows[0].role is Role.teacher


def test_overview_over_http_reports_spend_with_its_thresholds(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A spend figure without its alarm points cannot be read as safe or unsafe."""
    for client in _client(pg_sessionmaker):
        body = client.get("/api/admin/overview").json()

    assert body["spend"]["thresholdsUsd"]
    assert body["spend"]["cumulativeUsd"] >= 0
    if body["spend"]["ceilingUsd"] is not None:
        assert body["spend"]["remainingUsd"] is not None
    assert body["health"]["databaseReachable"] is True


# ── X-02: the activation queue ────────────────────────────────────────────────


def test_queue_holds_only_undecided_subscriptions_oldest_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    plan = _plan(pg_sessionmaker)
    older_user = _user(pg_sessionmaker, Role.student)
    newer_user = _user(pg_sessionmaker, Role.student)
    decided_user = _user(pg_sessionmaker, Role.student)
    base = datetime(2026, 8, 1, tzinfo=UTC)
    older = _subscription(pg_sessionmaker, older_user, plan, created_at=base)
    newer = _subscription(pg_sessionmaker, newer_user, plan, created_at=base + timedelta(days=1))
    _subscription(pg_sessionmaker, decided_user, plan, status=SubscriptionStatus.active)

    queue = PlatformAdminService(pg_sessionmaker).pending_activations()

    assert [row.subscription_id for row in queue] == [older, newer]
    assert queue[0].plan_code == "student_monthly"
    assert queue[0].price_minor == 9900


def test_activation_records_the_manual_flag_the_instant_and_the_note(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    subscription_id = _subscription(pg_sessionmaker, user, plan)
    decided_at = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)

    status = PlatformAdminService(pg_sessionmaker).decide_activation(
        subscription_id, activate=True, note="Paid by transfer, receipt seen", now=decided_at
    )

    assert status is SubscriptionStatus.active
    with pg_sessionmaker() as session:
        row = session.get(Subscription, subscription_id)
        assert row.is_manually_activated is True
        assert row.activated_at == decided_at
        assert row.activation_note == "Paid by transfer, receipt seen"


def test_a_rejection_is_rejected_not_cancelled_and_has_no_activation_instant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Migration ``0019``'s whole reason.

    ``cancelled`` already means "the subscriber ended this". Reusing it for "we
    declined this" would make the two indistinguishable in the one table an
    audit would read.
    """
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    subscription_id = _subscription(pg_sessionmaker, user, plan)

    status = PlatformAdminService(pg_sessionmaker).decide_activation(
        subscription_id, activate=False, note="No payment received"
    )

    assert status is SubscriptionStatus.rejected
    with pg_sessionmaker() as session:
        row = session.get(Subscription, subscription_id)
        assert row.status is SubscriptionStatus.rejected
        assert row.is_manually_activated is False
        assert row.activated_at is None
        assert row.activation_note == "No payment received"


def test_a_second_decision_is_refused_rather_than_overwriting_the_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    subscription_id = _subscription(pg_sessionmaker, user, plan)
    service = PlatformAdminService(pg_sessionmaker)
    service.decide_activation(subscription_id, activate=True, note="first")

    with pytest.raises(SubscriptionAlreadyDecidedError) as excinfo:
        service.decide_activation(subscription_id, activate=False, note="second")

    assert excinfo.value.status is SubscriptionStatus.active
    with pg_sessionmaker() as session:
        # The first decision stands, note included.
        assert session.get(Subscription, subscription_id).activation_note == "first"


def test_deciding_an_unknown_subscription_raises(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(SubscriptionNotFoundError):
        PlatformAdminService(pg_sessionmaker).decide_activation(uuid.uuid4(), activate=True)


def test_decision_routes_map_their_errors(pg_sessionmaker: sessionmaker[Session]) -> None:
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    subscription_id = _subscription(pg_sessionmaker, user, plan)

    for client in _client(pg_sessionmaker):
        unknown = client.post(f"/api/admin/activations/{uuid.uuid4()}/activate", json={})
        first = client.post(
            f"/api/admin/activations/{subscription_id}/reject", json={"note": "no payment"}
        )
        second = client.post(f"/api/admin/activations/{subscription_id}/activate", json={})

    assert unknown.status_code == 404
    assert first.status_code == 200
    assert first.json()["status"] == "rejected"
    assert second.status_code == 409


# ── X-03: pipeline health ─────────────────────────────────────────────────────


def test_corpus_coverage_separates_papers_with_and_without_a_scheme(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _paper_with_scheme(pg_sessionmaker, variant=1, with_scheme=True)
    _paper_with_scheme(pg_sessionmaker, variant=2, with_scheme=False)
    _paper_with_scheme(pg_sessionmaker, variant=3, with_scheme=False)

    health = PlatformAdminService(pg_sessionmaker).pipeline_health(
        exact_boundary_keys=7, subject_default_boundary_keys=2
    )

    assert len(health.subjects) == 1
    assert health.subjects[0].subject_code == "0625"
    assert health.subjects[0].papers == 3
    assert health.subjects[0].papers_with_scheme == 1
    assert health.subjects[0].papers_without_scheme == 2
    assert health.exact_boundary_keys == 7


def test_boundary_reliance_counts_past_paper_attempts_by_source(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """X-03's "real or estimated", measured from what predictions actually used."""
    student = _user(pg_sessionmaker, Role.student)
    now = datetime.now(UTC)
    _attempt(pg_sessionmaker, student, when=now, boundary=BoundarySource.exact)
    _attempt(pg_sessionmaker, student, when=now, boundary=BoundarySource.global_default)
    _attempt(pg_sessionmaker, student, when=now, boundary=BoundarySource.global_default)
    # A quiz carries no boundary at all and must not appear as an "unrecorded"
    # past-paper prediction.
    _attempt(pg_sessionmaker, student, when=now, origin=AttemptOrigin.quiz, boundary=None)

    health = PlatformAdminService(pg_sessionmaker).pipeline_health(
        exact_boundary_keys=0, subject_default_boundary_keys=0
    )

    assert health.boundary_source_counts == {"exact": 1, "global_default": 2}


def test_pipeline_over_http_says_where_accuracy_is_measured_instead_of_guessing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """X-03 asks for accuracy metrics; nothing at runtime carries them.

    The response says so in prose and names the harness, rather than deriving a
    number from whatever happens to be in the database.
    """
    for client in _client(pg_sessionmaker):
        body = client.get("/api/admin/pipeline").json()

    assert "accuracy harness" in body["markingAccuracyNote"]
    assert "reports/" in body["markingAccuracyNote"]
    assert body["uploadsByStatus"] == {
        "pending": 0,
        "processing": 0,
        "complete": 0,
        "failed": 0,
    }


def test_recent_failed_uploads_are_listed_for_triage(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _user(pg_sessionmaker, Role.student)
    failed = _upload(pg_sessionmaker, student, UploadStatus.failed)
    _upload(pg_sessionmaker, student, UploadStatus.complete)

    health = PlatformAdminService(pg_sessionmaker).pipeline_health(
        exact_boundary_keys=0, subject_default_boundary_keys=0
    )

    assert health.recent_failed_uploads == [failed]
    assert health.uploads_by_status["failed"] == 1
