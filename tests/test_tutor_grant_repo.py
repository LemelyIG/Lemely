"""Data grants and the tutor access audit at the repository (SPEC §a.2, §b.2 S8-S11, T19, T20).

The module also holds the seeding helpers the other grant test files import
(``add_student``, ``add_grant``, ``link_parent``, ``audit_rows``, ``outbox_rows``,
``inbox_rows``, ``live_grant_count``): the repository under test never builds the
world it is judged against.

What is proved here (ADR-T02, O2, O3):

* one live grant per pair: a second create returns the existing grant (200);
* revoke is idempotent and only ever touches the caller's own grant (O5);
* T20's validity check and its ``detail`` audit row are one transaction that
  commits before any student data is read, and a failed audit write fails the
  request with no data (fail closed);
* T19 writes exactly one ``list`` row per student on the page, in three
  statements whatever the page size (no N+1); its cursor names the anchor grant
  by id only, and paging stays exact when that grant ends between pages (F30-6);
* a 403 or a 404 writes no audit row; ``studentShared`` writes none either;
* S8/PA6 read ``blocked`` only for the student's own block; a tutor's block reads
  ``tutor_unavailable`` (SPEC §i.7, SC-11);
* the pair lock is booking_repo's one implementation, keyed exactly as SPEC §a.4b
  prints it.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core.history import PaperRecord
from lemely.core.keyset import CursorError, encode_cursor
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.db import booking_repo, tutor_grant_repo
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.class_repo import ClassService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models.enums import GrantRevokeReason, Role
from lemely.db.models.tutoring import TutorDataGrant, TutoringBlock
from lemely.db.models.users import ParentChildLink
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.tutor_directory_repo import TutorDirectoryRepository
from lemely.db.tutor_grant_repo import (
    AccessEnded,
    AccessLogKey,
    GrantNotFound,
    NoGrant,
    TutorBlocked,
    TutorGrantRepository,
    TutorNotFound,
    TutorNotListed,
    TutorStudentKey,
    access_log_cursor,
    parse_access_log_cursor,
    parse_tutor_students_cursor,
    revoke_live_in_session,
    tutor_students_cursor,
)
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.web.deps import (
    get_at_risk_ack_service,
    get_class_service,
    get_history_store,
    get_notification_service,
    get_push_transport,
    get_student_profile_service,
    get_user_mirror,
)
from lemely.web.deps_tutoring import get_tutor_directory_repo, get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import student_tutor_access, tutor_students, tutoring_directory
from lemely.web.routers.student_tutor_access import get_tutor_grant_repo
from tests.test_tutor_review_repo import add_booking
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    NOW,
    DbMirror,
    SeededTutor,
    act_as,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    count_statements,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

#: The tutor's public name every seeded tutor gets ("Sara" + "M"), as SPEC §e.1 formats it.
SARA = "Sara M."
SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"


def spec_pair_lock_key_sql() -> str:
    """The pair-lock key exactly as SPEC §a.4b step 3 prints it, with the two ids made bindable.

    Read from the SPEC text, never from the code under test, so a key the code
    changed on its own no longer matches.
    """
    section = SPEC.read_text(encoding="utf-8").split("### a.4b", 1)[1].split("\n### ", 1)[0]
    [expression] = re.findall(r"`pg_advisory_xact_lock\((hashtextextended\([^`]*\))\)`", section)
    assert "student_id" in expression
    assert "tutor_profile_id" in expression
    return expression.replace("student_id", "CAST(:student_id AS uuid)").replace(
        "tutor_profile_id", "CAST(:tutor_profile_id AS uuid)"
    )


# ---------------------------------------------------------------------------
# Seeding helpers (direct inserts; imported by the other grant test files)
# ---------------------------------------------------------------------------


def add_student(
    sm: sessionmaker[Session], *, display_name: str | None = "Amelia Hassan", verified: bool = True
) -> uuid.UUID:
    return add_user(sm, Role.student, verified=verified, display_name=display_name)


def add_grant(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    tutor: SeededTutor | uuid.UUID,
    *,
    created_ago: timedelta = timedelta(days=10),
    revoked: GrantRevokeReason | None = None,
    expires_in: timedelta | None = None,
) -> uuid.UUID:
    """A grant row written directly. A revoked one ended a day after it was made."""
    profile_id = tutor.profile_id if isinstance(tutor, SeededTutor) else tutor
    created_at = NOW - created_ago
    grant_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            TutorDataGrant(
                id=grant_id,
                student_id=student,
                tutor_profile_id=profile_id,
                created_at=created_at,
                revoked_at=created_at + timedelta(days=1) if revoked is not None else None,
                revoke_reason=revoked,
                expires_at=NOW + expires_in if expires_in is not None else None,
            )
        )
    return grant_id


def link_parent(sm: sessionmaker[Session], child: uuid.UUID) -> uuid.UUID:
    parent = add_user(sm, Role.parent)
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=child))
    return parent


def audit_rows(
    sm: sessionmaker[Session],
) -> list[tuple[uuid.UUID | None, uuid.UUID, uuid.UUID | None, str, str]]:
    """``(grant_id, student_id, tutor_profile_id, tutor_public_name, action)`` in write order."""
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT grant_id, student_id, tutor_profile_id, tutor_public_name, action::text "
                "FROM tutor_access_audit ORDER BY accessed_at, id"
            )
        ).all()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def outbox_rows(sm: sessionmaker[Session]) -> list[tuple[uuid.UUID, str, str]]:
    """``(recipient_user_id, template, dedupe_key)`` of every queued email."""
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT recipient_user_id, template, dedupe_key FROM email_outbox "
                "ORDER BY created_at, id"
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def inbox_rows(sm: sessionmaker[Session]) -> list[tuple[uuid.UUID, str, str, str | None]]:
    """``(user_id, type, title, body)`` of every inbox notification."""
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT user_id, type::text, title, body FROM notifications ORDER BY created_at"
            )
        ).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def live_grant_count(sm: sessionmaker[Session], student: uuid.UUID, profile_id: uuid.UUID) -> int:
    with sm() as session:
        return int(
            session.execute(
                sa.text(
                    "SELECT count(*) FROM tutor_data_grants WHERE student_id = :s "
                    "AND tutor_profile_id = :t AND revoked_at IS NULL"
                ),
                {"s": student, "t": profile_id},
            ).scalar_one()
        )


def paper(
    student: uuid.UUID,
    *,
    recorded_at: datetime,
    percentage: float,
    grade: str,
    subject: str = "0625",
    question_ids: tuple[str, ...] = ("3a", "7b(ii)"),
) -> PaperRecord:
    """One past-paper record whose weakness carries question ids (the projection drops them)."""
    return PaperRecord(
        student_id=str(student),
        metadata=ExamMetadata(
            subject_code=subject,
            paper_number=4,
            paper_variant=2,
            session_month="May/June",
            session_year=2025,
        ),
        awarded_marks=int(percentage / 100 * 80),
        maximum_marks=80,
        percentage=percentage,
        grade=grade,
        weak_areas=[
            WeakArea(
                topic="Thermal physics",
                lost_marks=10,
                maximum_marks=40,
                accuracy=0.75,
                question_ids=list(question_ids),
            )
        ],
        recorded_at=recorded_at.isoformat(),
    )


def grants_client(
    sm: sessionmaker[Session], transport: RecordingPushTransport | None = None
) -> TestClient:
    """S8-S11, T19, T20 and SP2 (plus ``create_app``'s teacher router) on the test database.

    Built through ``app_with_routers`` (a lane never edits ``lemely/web/app.py``).
    The history store, target grades, classes and at-risk acknowledgements all read
    the same throwaway database, so the teacher route and T20 see one world; SP2 is
    there so S9's refusals can be compared with the directory's own 404 (O11).
    """
    app = app_with_routers(
        student_tutor_access.router, tutor_students.router, tutoring_directory.router
    )
    classes = ClassService(sm)
    push = transport if transport is not None else RecordingPushTransport()
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(sm)
    app.dependency_overrides[get_tutor_directory_repo] = lambda: TutorDirectoryRepository(sm)
    app.dependency_overrides[get_tutor_grant_repo] = lambda: TutorGrantRepository(sm)
    app.dependency_overrides[get_user_mirror] = lambda: DbMirror(sm)
    app.dependency_overrides[get_notification_service] = lambda: NotificationService(
        sm, NotificationPreferencesService(sm)
    )
    app.dependency_overrides[get_push_transport] = lambda: push
    app.dependency_overrides[get_history_store] = lambda: DbHistoryStore(sm)
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(sm)
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_at_risk_ack_service] = lambda: AtRiskAckService(sm, classes)
    return TestClient(app)


def seed_history(sm: sessionmaker[Session], student: uuid.UUID) -> None:
    """Three declining papers, the last about 20 days ago at 23:40 UTC.

    23:40 UTC is 01:40 or 02:40 the next day in Cairo: a projection that kept the
    UTC day would give the late-night session away.
    """
    store = DbHistoryStore(sm)
    last = (datetime.now(UTC) - timedelta(days=20)).replace(
        hour=23, minute=40, second=0, microsecond=0
    )
    for days_before, percentage, grade in ((30, 80.0, "B"), (15, 70.0, "C"), (0, 55.0, "E")):
        store.append(
            str(student),
            paper(
                student,
                recorded_at=last - timedelta(days=days_before),
                percentage=percentage,
                grade=grade,
            ),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutorGrantRepository:
    return TutorGrantRepository(sm)


@pytest.fixture
def tutor(sm: sessionmaker[Session]) -> SeededTutor:
    return add_tutor(sm)


@pytest.fixture
def student(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_student(sm)


@contextmanager
def refused_audit_writes(sm: sessionmaker[Session]) -> Iterator[None]:
    """Make every ``tutor_access_audit`` insert fail, as a full disk or a lost table would."""
    with sm.begin() as session:
        session.execute(
            sa.text(
                "CREATE FUNCTION t14_refuse_audit() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'audit log unavailable'; END $$"
            )
        )
        session.execute(
            sa.text(
                "CREATE TRIGGER t14_refuse BEFORE INSERT ON tutor_access_audit "
                "FOR EACH ROW EXECUTE FUNCTION t14_refuse_audit()"
            )
        )
    try:
        yield
    finally:
        with sm.begin() as session:
            session.execute(sa.text("DROP TRIGGER t14_refuse ON tutor_access_audit"))
            session.execute(sa.text("DROP FUNCTION t14_refuse_audit()"))


@contextmanager
def transaction_log(sm: sessionmaker[Session]) -> Iterator[list[tuple[str, str]]]:
    """Every ``begin``/``commit``/``rollback`` and statement on the engine, in order."""
    engine = sm.kw["bind"]
    events: list[tuple[str, str]] = []

    def on_begin(_conn: object) -> None:
        events.append(("begin", ""))

    def on_commit(_conn: object) -> None:
        events.append(("commit", ""))

    def on_rollback(_conn: object) -> None:
        events.append(("rollback", ""))

    def on_execute(*args: object) -> None:
        events.append(("sql", str(args[2])))

    listeners = (
        ("begin", on_begin),
        ("commit", on_commit),
        ("rollback", on_rollback),
        ("before_cursor_execute", on_execute),
    )
    for name, fn in listeners:
        sa.event.listen(engine, name, fn)
    try:
        yield events
    finally:
        for name, fn in listeners:
            sa.event.remove(engine, name, fn)


# ---------------------------------------------------------------------------
# S9 create, S10 revoke
# ---------------------------------------------------------------------------


def test_one_live_grant_returns_existing_200(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor, student: uuid.UUID
) -> None:
    parent = link_parent(sm, student)

    first = repo.create(student, tutor.profile_id)
    second = repo.create(student, tutor.profile_id)

    assert first.created is True
    assert second.created is False
    assert second.grant.id == first.grant.id
    assert first.grant.scope == "all_subjects_derived"
    assert first.grant.revoked_at is None
    assert live_grant_count(sm, student, tutor.profile_id) == 1
    # The parent's email is queued once, in the grant's transaction (SPEC §b.4).
    assert outbox_rows(sm) == [
        (parent, "tutor_access_granted", f"grant:{first.grant.id}:created:{parent}")
    ]
    assert first.notice.linked_parent_ids == (parent,)
    assert first.notice.tutor_user_id == tutor.user_id
    assert first.notice.tutor_name == SARA
    assert first.notice.student_label == "Amelia Hassan"


def test_create_refused_unknown_unlisted_paused_or_blocked(
    sm: sessionmaker[Session], repo: TutorGrantRepository, student: uuid.UUID
) -> None:
    """O11: each reason is told apart here, and every one carries the one ``not_found`` code."""
    refusals: list[TutorNotFound] = []
    with pytest.raises(TutorNotFound) as unknown:
        repo.create(student, uuid.uuid4())
    refusals.append(unknown.value)
    for state in ("draft", "pending_review", "rejected", "suspended", "closed"):
        with pytest.raises(TutorNotListed) as hidden:
            repo.create(student, add_tutor(sm, state=state).profile_id)
        refusals.append(hidden.value)
    with pytest.raises(TutorNotListed) as paused:
        repo.create(student, add_tutor(sm, paused=True).profile_id)
    refusals.append(paused.value)
    blocked_by_student = add_tutor(sm)
    add_block(sm, student, blocked_by_student.user_id)
    blocked_by_tutor = add_tutor(sm)
    add_block(sm, blocked_by_tutor.user_id, student)
    for blocked in (blocked_by_student, blocked_by_tutor):
        with pytest.raises(TutorBlocked) as refused:
            repo.create(student, blocked.profile_id)
        refusals.append(refused.value)
    assert len(refusals) == 9  # unknown, five hidden states, paused, two block directions
    assert {refusal.code for refusal in refusals} == {"not_found"}
    assert all(isinstance(refusal, TutorNotFound) for refusal in refusals)
    with sm() as session:
        assert session.execute(sa.text("SELECT count(*) FROM tutor_data_grants")).scalar_one() == 0
    assert outbox_rows(sm) == []


def test_revoke_idempotent(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor, student: uuid.UUID
) -> None:
    grant = repo.create(student, tutor.profile_id).grant

    first = repo.revoke(student, grant.id)
    second = repo.revoke(student, grant.id)

    assert first.revoked_now is True
    assert first.grant.revoke_reason is GrantRevokeReason.student
    assert first.grant.revoked_at is not None
    assert second.revoked_now is False
    assert second.grant.revoked_at == first.grant.revoked_at
    assert second.grant.revoke_reason is GrantRevokeReason.student
    assert live_grant_count(sm, student, tutor.profile_id) == 0
    assert first.notice.tutor_user_id == tutor.user_id

    # O5: a grant is revoked only by its own student; an unknown id is the same 404.
    other = add_student(sm)
    for caller, grant_id in ((other, grant.id), (student, uuid.uuid4())):
        with pytest.raises(GrantNotFound):
            repo.revoke(caller, grant_id)


def test_revoke_keeps_a_sweep_reason_and_regrant_is_a_new_grant(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor, student: uuid.UUID
) -> None:
    ended = add_grant(sm, student, tutor, revoked=GrantRevokeReason.block)
    outcome = repo.revoke(student, ended)
    assert outcome.revoked_now is False
    assert outcome.grant.revoke_reason is GrantRevokeReason.block

    again = repo.create(student, tutor.profile_id)
    assert again.created is True
    assert again.grant.id != ended


def test_revoke_live_in_session_sweeps_only_live_grants_of_that_tutor(
    sm: sessionmaker[Session], tutor: SeededTutor
) -> None:
    other_tutor = add_tutor(sm)
    students = [add_student(sm) for _ in range(3)]
    live = [add_grant(sm, s, tutor) for s in students[:2]]
    add_grant(sm, students[2], tutor, revoked=GrantRevokeReason.student)
    elsewhere = add_grant(sm, students[0], other_tutor)

    with sm.begin() as session:
        one = revoke_live_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            student_id=students[0],
            reason=GrantRevokeReason.block,
        )
    assert one == [live[0]]
    with sm.begin() as session:
        rest = TutorGrantRepository.revoke_live_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            student_id=None,
            reason=GrantRevokeReason.tutor_suspended,
        )
    assert rest == [live[1]]
    with sm() as session:
        reasons = dict(
            session.execute(
                sa.text(
                    "SELECT id, revoke_reason::text FROM tutor_data_grants "
                    "WHERE revoked_at IS NOT NULL"
                )
            ).all()
        )
    assert reasons[live[0]] == "block"
    assert reasons[live[1]] == "tutor_suspended"
    assert elsewhere not in reasons
    with sm.begin() as session, pytest.raises(ValueError, match="student"):
        revoke_live_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            student_id=None,
            reason=GrantRevokeReason.student,
        )


def test_revoke_live_in_session_stamps_the_sweeps_instant_or_now(
    sm: sessionmaker[Session], tutor: SeededTutor
) -> None:
    """A sweep passes ``at``, the clock it read after the tutor row lock (SPEC §a.4b); without
    it the revoke keeps the transaction's ``now()``."""
    first, second = add_student(sm), add_student(sm)
    swept, plain = add_grant(sm, first, tutor), add_grant(sm, second, tutor)
    with sm.begin() as session:
        now = session.execute(sa.text("SELECT now()")).scalar_one()
        at = now + timedelta(minutes=5)
        assert revoke_live_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            student_id=first,
            reason=GrantRevokeReason.block,
            at=at,
        ) == [swept]
        assert revoke_live_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            student_id=second,
            reason=GrantRevokeReason.block,
        ) == [plain]
    with sm() as session:
        stamps = {
            row[0]: (row[1], row[2])
            for row in session.execute(
                sa.text(
                    "SELECT id, revoked_at, updated_at FROM tutor_data_grants "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": [swept, plain]},
            ).all()
        }
    assert stamps == {swept: (at, at), plain: (now, now)}


def test_pair_lock_is_the_booking_one_keyed_as_the_spec_prints_it(
    sm: sessionmaker[Session], tutor: SeededTutor, student: uuid.UUID
) -> None:
    """SPEC §a.4b step 3: one implementation for every pair path, and its key is the SPEC's.

    The function the grant writes call is read from the module the repository
    runs in, so a private copy (or a re-keyed one) fails here.
    """
    used_by_grants = vars(tutor_grant_repo)["lock_pair_in_session"]
    assert used_by_grants is booking_repo.lock_pair_in_session
    params = {"student_id": student, "tutor_profile_id": tutor.profile_id}
    with sm.begin() as session:
        expected = session.execute(sa.text(f"SELECT {spec_pair_lock_key_sql()}"), params)
        key = expected.scalar_one()
        used_by_grants(session, student_id=student, tutor_profile_id=tutor.profile_id)
        held = (
            session.execute(
                sa.text(
                    "SELECT (classid::bigint << 32) | objid::bigint FROM pg_locks "
                    "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 1"
                )
            )
            .scalars()
            .all()
        )
    assert held == [key]


# ---------------------------------------------------------------------------
# T20: the gate, the audit row, the transaction
# ---------------------------------------------------------------------------


def test_require_valid_grant_writes_one_detail_row(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor, student: uuid.UUID
) -> None:
    grant = add_grant(sm, student, tutor)

    access = repo.require_valid_grant(tutor.profile_id, student)

    assert access.grant.id == grant
    assert access.student_label == "Amelia Hassan"
    assert audit_rows(sm) == [(grant, student, tutor.profile_id, SARA, "detail")]
    with sm() as session:
        stored = session.execute(sa.text("SELECT accessed_at FROM tutor_access_audit")).scalar_one()
    assert access.accessed_at == stored


def test_403_and_404_write_no_audit(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor, student: uuid.UUID
) -> None:
    add_grant(sm, student, tutor, revoked=GrantRevokeReason.student)
    with pytest.raises(AccessEnded):
        repo.require_valid_grant(tutor.profile_id, student)
    for unknown in (add_student(sm), uuid.uuid4()):
        with pytest.raises(NoGrant):
            repo.require_valid_grant(tutor.profile_id, unknown)
    assert audit_rows(sm) == []
    # T19 lists no ended grant, so it writes no row for one either.
    assert repo.students_page(tutor.profile_id, None, 20).items == ()
    assert audit_rows(sm) == []


def test_audit_row_written_before_data_and_in_same_transaction(
    sm: sessionmaker[Session], tutor: SeededTutor, student: uuid.UUID
) -> None:
    """O3: validity and the audit row commit together before any history is read."""
    add_subject(sm, code="0625", name="Physics")
    seed_history(sm, student)
    add_grant(sm, student, tutor)
    client = grants_client(sm)
    act_as(client, tutor.user_id, Role.teacher)

    with transaction_log(sm) as events:
        response = client.get(f"/api/tutor/students/{student}")
    assert response.status_code == 200, response.text

    insert_at = next(
        i
        for i, (kind, sql) in enumerate(events)
        if kind == "sql" and "INSERT INTO tutor_access_audit" in sql
    )
    begin_at = max(i for i, (kind, _) in enumerate(events[:insert_at]) if kind == "begin")
    end_at = next(i for i in range(insert_at, len(events)) if events[i][0] != "sql")
    assert events[end_at][0] == "commit"
    transaction = [sql for kind, sql in events[begin_at:end_at] if kind == "sql"]
    # The validity check ran in the audit row's transaction, before the insert.
    validity = [i for i, sql in enumerate(transaction) if "FROM tutor_data_grants" in sql]
    assert validity
    assert min(validity) < transaction.index(next(s for s in transaction if "INSERT INTO" in s))
    data_tables = (
        "FROM attempts",
        "weakness_records",
        "student_subject_enrolments",
        "display_name",
    )
    first_data = next(
        i
        for i, (kind, sql) in enumerate(events)
        if kind == "sql" and any(table in sql for table in data_tables)
    )
    assert first_data > insert_at
    history_reads = [
        i for i, (kind, sql) in enumerate(events) if kind == "sql" and "FROM attempts" in sql
    ]
    assert history_reads
    assert min(history_reads) > end_at  # the history loads only after the audit commit


class _ForbiddenHistory:
    """A history store that fails the test if anything reads it."""

    def __init__(self) -> None:
        self.calls = 0

    def load(self, student_id: str) -> object:
        self.calls += 1
        raise AssertionError(f"history read for {student_id} after a failed audit write")


def test_audit_failure_returns_500_no_body(
    sm: sessionmaker[Session], tutor: SeededTutor, student: uuid.UUID
) -> None:
    add_grant(sm, student, tutor)
    client = grants_client(sm)
    history = _ForbiddenHistory()
    client.app.dependency_overrides[get_history_store] = lambda: history  # type: ignore[attr-defined]
    act_as(client, tutor.user_id, Role.teacher)
    quiet = TestClient(client.app, raise_server_exceptions=False)

    with refused_audit_writes(sm):
        detail = quiet.get(f"/api/tutor/students/{student}")
        listing = quiet.get("/api/tutor/students")

    for response in (detail, listing):
        assert response.status_code == 500
        assert response.content == b""
        assert response.headers["cache-control"] == "private, no-store"
    assert history.calls == 0
    assert audit_rows(sm) == []
    # The same request succeeds once the log accepts writes again.
    assert TutorGrantRepository(sm).students_page(tutor.profile_id, None, 20).items


# ---------------------------------------------------------------------------
# T19: one list row per listed student, no N+1
# ---------------------------------------------------------------------------


def test_t19_one_list_row_per_listed_student(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor
) -> None:
    students = [add_student(sm, display_name=f"Student {n}") for n in range(3)]
    grants = [
        add_grant(sm, s, tutor, created_ago=timedelta(days=10 - n)) for n, s in enumerate(students)
    ]
    add_grant(sm, add_student(sm), tutor, revoked=GrantRevokeReason.student)
    add_grant(sm, add_student(sm), add_tutor(sm))

    first = repo.students_page(tutor.profile_id, None, 2)
    assert [item.grant_id for item in first.items] == [grants[2], grants[1]]
    assert first.next_key is not None
    second = repo.students_page(tutor.profile_id, first.next_key, 2)
    assert [item.grant_id for item in second.items] == [grants[0]]
    assert second.next_key is None

    rows = audit_rows(sm)
    assert sorted((r[0], r[1]) for r in rows) == sorted(zip(grants, students, strict=True))
    assert {(r[2], r[3], r[4]) for r in rows} == {(tutor.profile_id, SARA, "list")}
    assert [item.display_name for item in first.items] == ["Student 2", "Student 1"]


def test_t19_upcoming_sessions_count_only_accepted_sessions_not_yet_over(
    sm: sessionmaker[Session], repo: TutorGrantRepository
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, subjects=[subject])
    student = add_student(sm)
    add_grant(sm, student, tutor)
    for ended_ago in (timedelta(days=-2), timedelta(days=-9)):  # two upcoming
        add_booking(
            sm, student=student, tutor=tutor, subject=subject, state="accepted", ended_ago=ended_ago
        )
    add_booking(
        sm,
        student=student,
        tutor=tutor,
        subject=subject,
        state="accepted",
        ended_ago=timedelta(days=1),
    )  # over, awaiting an outcome
    add_booking(sm, student=student, tutor=tutor, subject=subject, state="completed")
    other = add_tutor(sm, subjects=[subject])
    add_booking(
        sm,
        student=student,
        tutor=other,
        subject=subject,
        state="accepted",
        ended_ago=timedelta(days=-3),
    )  # another tutor's session

    [item] = repo.students_page(tutor.profile_id, None, 20).items

    assert item.upcoming_sessions == 2


def test_t19_query_budget_three_statements_whatever_the_page(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor
) -> None:
    """SPEC §e.3: validity + rows, one audit insert, one names-and-counts read."""
    add_grant(sm, add_student(sm), tutor)
    with count_statements(sm) as one:
        assert len(repo.students_page(tutor.profile_id, None, 20).items) == 1
    for _ in range(9):
        add_grant(sm, add_student(sm), tutor)
    with count_statements(sm) as ten:
        assert len(repo.students_page(tutor.profile_id, None, 20).items) == 10
    assert len(one) == len(ten) == 3
    assert sum("INSERT INTO tutor_access_audit" in sql for sql in ten) == 1
    assert len(audit_rows(sm)) == 11


def test_t19_paging_is_stable_when_the_anchor_grant_is_revoked_between_pages(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor
) -> None:
    """F30-6: the cursor names its anchor grant by id, and the anchor keeps its place once it ends.

    The order is ``created_at DESC, id ASC`` and neither value ever changes, so a grant
    that left the list between pages (here: revoked by its student) still marks where
    the next page starts: nothing is skipped and nothing is served twice. Two grants
    share one instant across the page boundary, so the id tie-break is exercised too.
    Every cursor goes through the wire codec. The query budget on later pages: three
    statements when the page has rows, as on the first; at most two when it is empty
    (the rows, then the look that tells the end of the list from a bad anchor).
    """
    students = [add_student(sm, display_name=f"Student {n}") for n in range(5)]
    oldest = add_grant(sm, students[0], tutor, created_ago=timedelta(days=10))
    older = add_grant(sm, students[1], tutor, created_ago=timedelta(days=9))
    tied = sorted(add_grant(sm, students[n], tutor, created_ago=timedelta(days=8)) for n in (2, 3))
    newest = add_grant(sm, students[4], tutor, created_ago=timedelta(days=7))

    def wire(key: TutorStudentKey | None) -> TutorStudentKey:
        assert key is not None
        return parse_tutor_students_cursor(
            tutor_students_cursor("tutor_students", key), "tutor_students"
        )

    first = repo.students_page(tutor.profile_id, None, 2)
    assert [item.grant_id for item in first.items] == [newest, tied[0]]

    # The anchor ends between pages: its student revokes it.
    anchor_student = first.items[-1].student_id
    assert repo.revoke(anchor_student, tied[0]).revoked_now

    with count_statements(sm) as second_statements:
        second = repo.students_page(tutor.profile_id, wire(first.next_key), 2)
    assert [item.grant_id for item in second.items] == [tied[1], older]
    assert len(second_statements) == 3

    # The next anchor stays live, but every grant after it ends: an empty page, not a 422.
    assert repo.revoke(students[0], oldest).revoked_now
    with count_statements(sm) as third_statements:
        third = repo.students_page(tutor.profile_id, wire(second.next_key), 2)
    assert third.items == ()
    assert third.next_key is None
    assert len(third_statements) <= 2

    # Each grant was served once, in order, and only served grants were logged.
    served = [i.grant_id for page in (first, second) for i in page.items]
    assert served == [newest, *tied, older]
    assert sorted(r[0] for r in audit_rows(sm) if r[0] is not None) == sorted(served)


def test_t19_cursor_round_trip_and_endpoint_tag() -> None:
    key = TutorStudentKey(grant_id=uuid.uuid4())
    token = tutor_students_cursor("tutor_students", key)
    assert parse_tutor_students_cursor(token, "tutor_students") == key
    with pytest.raises(CursorError):
        parse_tutor_students_cursor(token, "student_tutor_access_log")
    # A cursor in the old shape (the grant instant, then the id) is no longer accepted (F30-6).
    accessed_at = datetime(2026, 10, 1, 9, 30, 0, 123456, tzinfo=UTC)
    with pytest.raises(CursorError):
        parse_tutor_students_cursor(
            encode_cursor("tutor_students", [accessed_at, key.grant_id]), "tutor_students"
        )
    log_key = AccessLogKey(accessed_at=accessed_at, entry_id=key.grant_id)
    log_token = access_log_cursor("student_tutor_access_log", log_key)
    assert parse_access_log_cursor(log_token, "student_tutor_access_log") == log_key
    with pytest.raises(CursorError):
        parse_access_log_cursor(log_token, "tutor_students")


# ---------------------------------------------------------------------------
# studentShared, S8 views, S11 log
# ---------------------------------------------------------------------------


def test_student_shared_is_the_validity_predicate_and_writes_no_audit_row(
    sm: sessionmaker[Session], repo: TutorGrantRepository, tutor: SeededTutor
) -> None:
    valid = add_student(sm)
    add_grant(sm, valid, tutor)
    revoked = add_student(sm)
    add_grant(sm, revoked, tutor, revoked=GrantRevokeReason.student)
    blocked = add_student(sm)
    add_grant(sm, blocked, tutor)
    add_block(sm, blocked, tutor.user_id)
    never = add_student(sm)

    shared = repo.student_shared(tutor.profile_id, [valid, revoked, blocked, never])

    assert shared == {valid}
    assert repo.student_shared(tutor.profile_id, []) == set()
    assert audit_rows(sm) == []


def test_grants_for_student_live_first_with_status_and_also_teaches(
    sm: sessionmaker[Session], repo: TutorGrantRepository, student: uuid.UUID
) -> None:
    listed = add_tutor(sm)
    rejected = add_tutor(sm, state="rejected", first_name="Omar", initial="K")
    ended = add_tutor(sm, first_name="Lina", initial=None)
    newest_live = add_grant(sm, student, listed, created_ago=timedelta(days=2))
    older_live = add_grant(sm, student, rejected, created_ago=timedelta(days=5))
    ended_grant = add_grant(
        sm, student, ended, created_ago=timedelta(days=1), revoked=GrantRevokeReason.block
    )
    classes = ClassService(sm)
    for name in ("Physics 10B", "Physics 10A"):
        made = classes.create_class(listed.user_id, name)
        assert made.join_code is not None
        classes.join_by_code(student, made.join_code)
    elsewhere = classes.create_class(listed.user_id, "Not my class")
    assert elsewhere.join_code is not None

    views = repo.grants_for_student(student)

    assert [v.grant.id for v in views] == [newest_live, older_live, ended_grant]
    # The block that ended ``ended_grant`` is not the student's (they never blocked Lina), so it
    # reads as the tutor being unavailable (SPEC §i.7, SC-11); the student's own block keeps
    # ``blocked`` (test_grant_status_reads_blocked_only_for_the_students_own_block).
    assert [v.status for v in views] == ["active", "tutor_unavailable", "tutor_unavailable"]
    assert views[0].also_teaches_classes == ("Physics 10A", "Physics 10B")
    assert views[1].also_teaches_classes == ()
    assert views[0].tutor.tutor_id == listed.profile_id
    assert repo.grants_for_student(student, include_classes=False)[0].also_teaches_classes == ()
    assert repo.grant_view(student, older_live) == views[1]
    assert repo.grant_view(add_student(sm), older_live) is None
    assert audit_rows(sm) == []


def add_block_at(
    sm: sessionmaker[Session],
    blocker: uuid.UUID,
    blocked: uuid.UUID,
    *,
    created_at: datetime,
    removed_at: datetime | None = None,
) -> None:
    """A ``tutoring_blocks`` row whose first-block instant is ``created_at``."""
    with sm.begin() as session:
        session.add(
            TutoringBlock(
                blocker_user_id=blocker,
                blocked_user_id=blocked,
                created_at=created_at,
                removed_at=removed_at,
            )
        )


def grant_end(sm: sessionmaker[Session], grant_id: uuid.UUID) -> datetime:
    with sm() as session:
        revoked_at = session.execute(
            sa.text("SELECT revoked_at FROM tutor_data_grants WHERE id = :g"), {"g": grant_id}
        ).scalar_one()
    assert isinstance(revoked_at, datetime)
    return revoked_at


def test_grant_status_reads_blocked_only_for_the_students_own_block(
    sm: sessionmaker[Session], repo: TutorGrantRepository, student: uuid.UUID
) -> None:
    """S8/PA6 (SPEC §i.7, SC-11): ``blocked`` only when the student's own first block fell inside
    the grant's life (its revoke instant, or now for a live grant); any other block, the tutor's,
    reads ``tutor_unavailable``, so a student never learns that a tutor blocked them."""
    tutors = {
        name: add_tutor(sm, first_name=first_name)
        for name, first_name in (
            ("own_block_ended_it", "Amal"),
            ("tutor_block_ended_it", "Badr"),
            ("old_lifted_own_block", "Dina"),
            ("own_block_came_after", "Fady"),
            ("live_own_block", "Hoda"),
            ("live_tutor_block", "Karim"),
        )
    }
    ended = {
        name: add_grant(sm, student, tutors[name], revoked=GrantRevokeReason.block)
        for name in (
            "own_block_ended_it",
            "tutor_block_ended_it",
            "old_lifted_own_block",
            "own_block_came_after",
        )
    }
    at = {name: grant_end(sm, grant) for name, grant in ended.items()}
    created_at = NOW - timedelta(days=10)  # add_grant's default ``created_ago``
    add_block_at(
        sm, student, tutors["own_block_ended_it"].user_id, created_at=at["own_block_ended_it"]
    )
    add_block_at(
        sm, tutors["tutor_block_ended_it"].user_id, student, created_at=at["tutor_block_ended_it"]
    )
    # Blocked once before this grant, lifted, re-shared; the tutor's block ended this one.
    add_block_at(
        sm,
        student,
        tutors["old_lifted_own_block"].user_id,
        created_at=created_at - timedelta(days=20),
        removed_at=created_at - timedelta(days=15),
    )
    add_block_at(
        sm,
        tutors["old_lifted_own_block"].user_id,
        student,
        created_at=at["old_lifted_own_block"],
    )
    # The tutor's block ended the grant; the student blocked only later.
    add_block_at(
        sm,
        tutors["own_block_came_after"].user_id,
        student,
        created_at=at["own_block_came_after"],
    )
    add_block_at(
        sm,
        student,
        tutors["own_block_came_after"].user_id,
        created_at=at["own_block_came_after"] + timedelta(hours=1),
    )
    # Live grants under an active block (no sweep ran): the active rule of grant_status.
    for name in ("live_own_block", "live_tutor_block"):
        add_grant(sm, student, tutors[name])
    add_block_at(sm, student, tutors["live_own_block"].user_id, created_at=NOW - timedelta(days=1))
    add_block_at(
        sm, tutors["live_tutor_block"].user_id, student, created_at=NOW - timedelta(days=1)
    )

    by_tutor = {view.tutor.tutor_id: view.status for view in repo.grants_for_student(student)}
    shown = {name: by_tutor[tutor.profile_id] for name, tutor in tutors.items()}

    assert shown == {
        "own_block_ended_it": "blocked",
        "tutor_block_ended_it": "tutor_unavailable",
        "old_lifted_own_block": "tutor_unavailable",
        "own_block_came_after": "tutor_unavailable",
        "live_own_block": "blocked",
        "live_tutor_block": "tutor_unavailable",
    }
    # One grant, one read path: grant_view (S9/S10's answer) agrees with the list.
    for name, grant in ended.items():
        view = repo.grant_view(student, grant)
        assert view is not None
        assert view.status == shown[name], name


def test_access_log_page_newest_first_with_tutor_filter_and_cursor(
    sm: sessionmaker[Session], repo: TutorGrantRepository, student: uuid.UUID
) -> None:
    first_tutor = add_tutor(sm)
    second_tutor = add_tutor(sm, first_name="Omar", initial="K")
    add_grant(sm, student, first_tutor)
    add_grant(sm, student, second_tutor)
    repo.students_page(first_tutor.profile_id, None, 20)
    repo.require_valid_grant(first_tutor.profile_id, student)
    repo.require_valid_grant(second_tutor.profile_id, student)

    page = repo.access_log_page(student, tutor_id=None, cursor=None, limit=2)
    assert [(e.tutor_name, e.action) for e in page.items] == [
        ("Omar K.", "detail"),
        (SARA, "detail"),
    ]
    assert page.next_key is not None
    rest = repo.access_log_page(student, tutor_id=None, cursor=page.next_key, limit=2)
    assert [(e.tutor_name, e.action) for e in rest.items] == [(SARA, "list")]
    assert rest.next_key is None

    only_first = repo.access_log_page(
        student, tutor_id=first_tutor.profile_id, cursor=None, limit=20
    )
    assert [e.action for e in only_first.items] == ["detail", "list"]
    assert {e.tutor_profile_id for e in only_first.items} == {first_tutor.profile_id}
    assert repo.access_log_page(add_student(sm), tutor_id=None, cursor=None, limit=20).items == ()
