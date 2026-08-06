"""Postgres-integration tests for :class:`AtRiskAckService` (P3.4b/D3.5).

Exercises the service layer directly (upsert / re-upsert / delete / bulk-read
/ tenancy), independently of the HTTP routes (``tests/test_web_teacher.py``
covers the router-level behaviour, including the "reason not currently
firing" rejection and the ``?acknowledged=`` filter, both of which need the
core rules engine + HistoryStore this service deliberately does not own).

Follows ``tests/test_review_repo.py``'s fixture pattern: a throwaway Postgres
database per test, skipping cleanly when no local Postgres is reachable.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.at_risk import AtRiskReason
from lemely.db.at_risk_repo import AtRiskAckOwnershipError, AtRiskAckService
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.models.ops import AtRiskAcknowledgement
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


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.teacher, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_teacher_with_student(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    *,
    student_name: str = "Amelia",
) -> tuple[uuid.UUID, uuid.UUID]:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name=student_name)
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    return teacher, student


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def ack_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> AtRiskAckService:
    return AtRiskAckService(pg_sessionmaker, class_service)


# ── acknowledge (upsert) ─────────────────────────────────────────────────────


def test_acknowledge_then_load_for_teacher(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)

    row = ack_service.acknowledge(
        teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND, "fp-1", note="watching"
    )
    assert row.evidence_fingerprint == "fp-1"
    assert row.note == "watching"
    assert row.acknowledged_by == teacher
    assert row.student_id == student
    assert row.reason == AtRiskReason.DECLINING_TREND

    loaded = ack_service.load_for_teacher(teacher)
    assert (student, AtRiskReason.DECLINING_TREND) in loaded
    assert loaded[(student, AtRiskReason.DECLINING_TREND)].evidence_fingerprint == "fp-1"


def test_reacknowledge_overwrites_not_duplicates(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    """A second acknowledge for the same (teacher, student, reason) updates the
    existing row's fingerprint/note in place rather than creating a second
    one — the whole point of the unique constraint being the upsert key."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)

    ack_service.acknowledge(
        teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND, "fp-1", note="first note"
    )
    ack_service.acknowledge(
        teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND, "fp-2", note="second note"
    )

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(AtRiskAcknowledgement).where(
                AtRiskAcknowledgement.teacher_id == teacher,
                AtRiskAcknowledgement.student_id == student,
                AtRiskAcknowledgement.reason == AtRiskReason.DECLINING_TREND,
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].evidence_fingerprint == "fp-2"
    assert rows[0].note == "second note"


def test_acknowledge_different_reasons_coexist(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    """Two different reasons for the same student are two separate rows."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)

    ack_service.acknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND, "fp-1")
    ack_service.acknowledge(teacher, Role.teacher, student, AtRiskReason.INACTIVE, "fp-2")

    loaded = ack_service.load_for_teacher(teacher)
    assert set(loaded.keys()) == {
        (student, AtRiskReason.DECLINING_TREND),
        (student, AtRiskReason.INACTIVE),
    }


def test_acknowledge_out_of_scope_student_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, student_b = _seed_teacher_with_student(pg_sessionmaker, class_service, student_name="B")

    with pytest.raises(AtRiskAckOwnershipError):
        ack_service.acknowledge(
            teacher_a, Role.teacher, student_b, AtRiskReason.DECLINING_TREND, "fp-1"
        )

    # No row was written for the rejected attempt.
    with pg_sessionmaker() as session:
        rows = session.scalars(select(AtRiskAcknowledgement)).all()
    assert rows == []


def test_acknowledge_malformed_student_id_is_value_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    with pytest.raises(ValueError, match="must be a UUID"):
        ack_service.acknowledge(
            teacher, Role.teacher, "not-a-uuid", AtRiskReason.DECLINING_TREND, "fp-1"
        )


# ── unacknowledge (delete) ───────────────────────────────────────────────────


def test_unacknowledge_removes_the_row(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    ack_service.acknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND, "fp-1")

    ack_service.unacknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND)

    assert ack_service.load_for_teacher(teacher) == {}


def test_unacknowledge_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    """Un-acknowledging a reason that was never acked is a no-op, not an error."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    ack_service.unacknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND)
    ack_service.unacknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND)


def test_unacknowledge_out_of_scope_student_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, student_b = _seed_teacher_with_student(pg_sessionmaker, class_service, student_name="B")

    with pytest.raises(AtRiskAckOwnershipError):
        ack_service.unacknowledge(teacher_a, Role.teacher, student_b, AtRiskReason.DECLINING_TREND)


def test_unacknowledge_only_removes_the_named_reason(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)
    ack_service.acknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND, "fp-1")
    ack_service.acknowledge(teacher, Role.teacher, student, AtRiskReason.INACTIVE, "fp-2")

    ack_service.unacknowledge(teacher, Role.teacher, student, AtRiskReason.DECLINING_TREND)

    loaded = ack_service.load_for_teacher(teacher)
    assert set(loaded.keys()) == {(student, AtRiskReason.INACTIVE)}


# ── load_for_teacher (bulk read, tenancy, no N+1) ────────────────────────────


def test_load_for_teacher_scoped_per_teacher(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    """Two teachers with disjoint classes: A's acknowledgement never appears
    when reading teacher B's acks, even for a differently-named student."""
    teacher_a, student_a = _seed_teacher_with_student(
        pg_sessionmaker, class_service, student_name="A"
    )
    teacher_b, student_b = _seed_teacher_with_student(
        pg_sessionmaker, class_service, student_name="B"
    )
    ack_service.acknowledge(teacher_a, Role.teacher, student_a, AtRiskReason.DECLINING_TREND, "fp")

    loaded_a = ack_service.load_for_teacher(teacher_a)
    loaded_b = ack_service.load_for_teacher(teacher_b)
    assert set(loaded_a.keys()) == {(student_a, AtRiskReason.DECLINING_TREND)}
    assert loaded_b == {}
    # Confirm B genuinely has no acks at all, not merely a filtered subset.
    with pg_sessionmaker() as session:
        all_rows = session.scalars(select(AtRiskAcknowledgement)).all()
    assert len(all_rows) == 1
    assert all_rows[0].teacher_id == teacher_a


def test_load_for_teacher_filters_by_student_ids(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student_x = _seed_user(pg_sessionmaker, Role.student, display_name="X")
    student_y = _seed_user(pg_sessionmaker, Role.student, display_name="Y")
    cls = class_service.create_class(teacher, "Class")
    assert cls.join_code is not None
    class_service.join_by_code(student_x, cls.join_code)
    class_service.join_by_code(student_y, cls.join_code)
    ack_service.acknowledge(teacher, Role.teacher, student_x, AtRiskReason.DECLINING_TREND, "fp")
    ack_service.acknowledge(teacher, Role.teacher, student_y, AtRiskReason.INACTIVE, "fp")

    loaded = ack_service.load_for_teacher(teacher, student_ids=[student_x])
    assert set(loaded.keys()) == {(student_x, AtRiskReason.DECLINING_TREND)}


def test_load_for_teacher_empty_when_no_acks(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    ack_service: AtRiskAckService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    assert ack_service.load_for_teacher(teacher) == {}


# ── DB-level constraint ──────────────────────────────────────────────────────


def test_unique_constraint_rejects_duplicate_triple(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """The physical unique constraint on (teacher_id, student_id, reason) —
    proven by bypassing the service and inserting directly."""
    teacher, student = _seed_teacher_with_student(pg_sessionmaker, class_service)

    with pg_sessionmaker() as session, session.begin():
        session.add(
            AtRiskAcknowledgement(
                teacher_id=teacher,
                student_id=student,
                reason=AtRiskReason.DECLINING_TREND,
                evidence_fingerprint="fp-1",
            )
        )

    with pytest.raises(sa.exc.IntegrityError), pg_sessionmaker() as session, session.begin():
        session.add(
            AtRiskAcknowledgement(
                teacher_id=teacher,
                student_id=student,
                reason=AtRiskReason.DECLINING_TREND,
                evidence_fingerprint="fp-2",
            )
        )
