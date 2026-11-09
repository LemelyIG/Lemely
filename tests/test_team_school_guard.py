"""Assistants never reach school-scoped data, and every acting request is audited (Phase 03).

A lead who belongs to a school (or owns a school class) can read that school's shared
question-bank tier, rosters, analytics and invite codes. Team permissions were never
meant to cover that, so the assistant path is refused for such a lead, live on every
request, with the same uniform 403 ``team_permission_denied``. The lead acting for
themselves, a ``school_admin`` and a ``platform_admin`` are untouched.

Real users, real routes, a real Postgres: only Gemini is a mock.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import event

from lemely.core.team_permissions import TeamPermission
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import School, SchoolMembership
from lemely.db.models.enums import MembershipRole, Role
from lemely.db.models.team import AssistantRole
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.db.review_repo import ReviewService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.db.teacher_team_repo import TeacherTeamStore, assistant_has_permission
from lemely.io.history_store import HistoryStore
from lemely.web.app import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_announcement_service,
    get_at_risk_ack_service,
    get_auth_context,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_invite_service,
    get_notification_service,
    get_push_transport,
    get_question_bank_service,
    get_quiz_service,
    get_review_service,
    get_scheme_corpus_repo,
    get_storage_backend,
    get_student_profile_service,
    get_teacher_paper_repo,
    get_teacher_team_store,
)
from lemely.web.push import RecordingPushTransport
from tests.storage_fakes import FakeStorageBackend
from tests.team_db import (
    add_assistant,
    add_class,
    add_subject,
    add_user,
    emptied_after,
    enrol,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.orm import Session, sessionmaker

DENIED = "team_permission_denied"


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _client(
    sm: sessionmaker[Session], user: uuid.UUID, tmp_path: Path, role: Role = Role.teacher
) -> TestClient:
    """The real app with every collaborator the routes under test resolve, on the test DB."""
    app = create_app()
    classes = ClassService(sm)
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_invite_service] = lambda: InviteService(
        sm, classes, ParentLinkService(sm)
    )
    app.dependency_overrides[get_announcement_service] = lambda: AnnouncementService(sm, classes)
    notifications = NotificationService(sm, NotificationPreferencesService(sm))
    transport = RecordingPushTransport()
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_push_transport] = lambda: transport
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user), role=role.value
    )
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(
        sm, classes, QuestionBankService(sm)
    )
    papers = TeacherPaperRepository(sm, stale_after=timedelta(minutes=10))
    app.dependency_overrides[get_teacher_paper_repo] = lambda: papers
    app.dependency_overrides[get_question_bank_service] = lambda: QuestionBankService(sm)
    app.dependency_overrides[get_review_service] = lambda: ReviewService(sm, classes)
    app.dependency_overrides[get_at_risk_ack_service] = lambda: AtRiskAckService(sm, classes)
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(sm)
    app.dependency_overrides[get_history_store] = lambda: HistoryStore(tmp_path / "history")
    storage = FakeStorageBackend()
    app.dependency_overrides[get_storage_backend] = lambda: storage
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock()
    app.dependency_overrides[get_scheme_corpus_repo] = lambda: MagicMock()
    return TestClient(app)


def _acting_for(lead: uuid.UUID) -> dict[str, str]:
    return {ACTING_TEACHER_HEADER: str(lead)}


def _add_school(sm: sessionmaker[Session]) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Guard Test School", seat_quota=5))
    return school_id


def _join_school(sm: sessionmaker[Session], user: uuid.UUID, school_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=user, membership_role=MembershipRole.teacher
            )
        )


class _Team:
    """A lead with a class and one enrolled student, and a co-teacher assistant."""

    def __init__(self, sm: sessionmaker[Session], *, school_class: bool = False) -> None:
        self.lead = add_user(sm, Role.teacher)
        self.helper = add_user(sm, Role.teacher)
        self.student = add_user(sm)
        add_subject(sm, "0580")
        self.school_id: uuid.UUID | None = _add_school(sm) if school_class else None
        self.class_id, _ = add_class(
            sm, teacher_id=self.lead, subject_code="0580", school_id=self.school_id
        )
        enrol(sm, self.class_id, self.student)
        add_assistant(
            sm, teacher_id=self.lead, assistant_id=self.helper, role=AssistantRole.co_teacher
        )


def _assert_denied(resp_status: int, body: dict[str, object], where: str) -> None:
    assert resp_status == 403, where
    assert body["detail"] == {
        "code": DENIED,
        "message": "You do not have permission to do this for that teacher.",
    }, where


def _hit_every_school_reachable_route(
    client: TestClient, team: _Team
) -> list[tuple[str, int, dict[str, object]]]:
    """Call the routes the review found reachable; return (label, status, body) for each."""
    headers = _acting_for(team.lead)
    calls: list[tuple[str, str, str, dict[str, object] | None]] = [
        ("pool-count", "GET", "/api/teacher/quizzes/pool-count?subject_code=0580", None),
        ("quiz pools", "GET", "/api/quizzes/pools?subject_code=0580", None),
        ("quiz preview", "POST", "/api/quizzes/preview?subject_code=0580&count=3", None),
        ("quiz generate", "POST", "/api/quizzes/generate?subject_code=0580&count=3", None),
        ("student detail", "GET", f"/api/teacher/students/{team.student}", None),
        ("review list", "GET", "/api/teacher/review", None),
        ("classes list", "GET", "/api/teacher/classes", None),
        ("class create", "POST", "/api/classes", {"name": "Smuggled class"}),
        ("roster", "GET", f"/api/classes/{team.class_id}/roster", None),
        ("mint", "POST", f"/api/school/classes/{team.class_id}/invite-code", None),
        ("announcements", "GET", "/api/teacher/announcements", None),
    ]
    out: list[tuple[str, int, dict[str, object]]] = []
    for label, method, path, body in calls:
        resp = client.request(method, path, headers=headers, json=body)
        out.append((label, resp.status_code, resp.json()))
    return out


def test_an_outsider_assistant_is_refused_for_a_lead_with_a_school_membership(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm)
    _join_school(sm, team.lead, _add_school(sm))
    results = _hit_every_school_reachable_route(_client(sm, team.helper, tmp_path), team)
    assert len(results) == 11
    for label, code, body in results:
        _assert_denied(code, body, label)


def test_an_outsider_assistant_is_refused_for_a_lead_who_owns_a_school_class(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm, school_class=True)
    results = _hit_every_school_reachable_route(_client(sm, team.helper, tmp_path), team)
    assert len(results) == 11
    for label, code, body in results:
        _assert_denied(code, body, label)


def test_the_same_assistant_still_works_for_a_school_less_lead(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm)
    client = _client(sm, team.helper, tmp_path)
    headers = _acting_for(team.lead)
    assert client.get("/api/teacher/classes", headers=headers).status_code == 200
    assert client.get(f"/api/classes/{team.class_id}/roster", headers=headers).status_code == 200
    assert client.get("/api/teacher/review", headers=headers).status_code == 200
    assert client.get("/api/teacher/announcements", headers=headers).status_code == 200
    assert client.get(f"/api/teacher/students/{team.student}", headers=headers).status_code == 200
    assert (
        client.get("/api/teacher/quizzes/pool-count?subject_code=0580", headers=headers).status_code
        == 200
    )
    assert (
        client.post(f"/api/school/classes/{team.class_id}/invite-code", headers=headers).status_code
        == 200
    )
    created = client.post("/api/classes", json={"name": "Made by the assistant"}, headers=headers)
    assert created.status_code == 201


def test_a_lead_who_joins_a_school_mid_session_immediately_loses_the_assistant_path(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm)
    client = _client(sm, team.helper, tmp_path)
    headers = _acting_for(team.lead)
    assert client.get("/api/teacher/classes", headers=headers).status_code == 200
    _join_school(sm, team.lead, _add_school(sm))
    resp = client.get("/api/teacher/classes", headers=headers)
    _assert_denied(resp.status_code, resp.json(), "after joining a school")


def test_a_lead_who_is_given_a_school_class_mid_session_loses_the_assistant_path(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm)
    client = _client(sm, team.helper, tmp_path)
    headers = _acting_for(team.lead)
    assert client.get("/api/teacher/classes", headers=headers).status_code == 200
    add_class(sm, teacher_id=team.lead, subject_code="0580", school_id=_add_school(sm))
    resp = client.get("/api/teacher/classes", headers=headers)
    _assert_denied(resp.status_code, resp.json(), "after a school class appeared")


def test_leaving_the_school_restores_the_path(sm: sessionmaker[Session], tmp_path: Path) -> None:
    """The refusal is a live predicate, not a flag written once."""
    team = _Team(sm)
    school_id = _add_school(sm)
    _join_school(sm, team.lead, school_id)
    client = _client(sm, team.helper, tmp_path)
    headers = _acting_for(team.lead)
    assert client.get("/api/teacher/classes", headers=headers).status_code == 403
    with sm.begin() as session:
        session.query(SchoolMembership).filter_by(user_id=team.lead).delete()
    assert client.get("/api/teacher/classes", headers=headers).status_code == 200


def test_the_lead_without_a_header_is_unaffected_inside_their_own_school(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm, school_class=True)
    assert team.school_id is not None
    _join_school(sm, team.lead, team.school_id)
    client = _client(sm, team.lead, tmp_path)
    assert client.get("/api/teacher/classes").status_code == 200
    assert client.get(f"/api/classes/{team.class_id}/roster").status_code == 200
    assert client.get("/api/teacher/review").status_code == 200
    assert client.get("/api/quizzes/pools?subject_code=0580").status_code == 200
    # A header naming the caller is the same as no header.
    assert client.get("/api/teacher/classes", headers=_acting_for(team.lead)).status_code == 200


def test_a_school_admin_is_unaffected(sm: sessionmaker[Session], tmp_path: Path) -> None:
    admin = add_user(sm, Role.school_admin)
    school_id = _add_school(sm)
    _join_school(sm, admin, school_id)
    client = _client(sm, admin, tmp_path, Role.school_admin)
    assert client.get("/api/teacher/classes").status_code == 200
    assert client.get("/api/teacher/announcements").status_code == 200


def test_a_platform_admin_is_unaffected(sm: sessionmaker[Session], tmp_path: Path) -> None:
    admin = add_user(sm, Role.platform_admin)
    client = _client(sm, admin, tmp_path, Role.platform_admin)
    assert client.get("/api/teacher/classes").status_code == 200
    assert client.get("/api/teacher/review").status_code == 200


def test_the_service_method_itself_refuses_so_phase_04_inherits_the_rule(
    sm: sessionmaker[Session],
) -> None:
    team = _Team(sm)
    with sm() as session:
        assert (
            assistant_has_permission(session, team.helper, team.lead, TeamPermission.VIEW_RESULTS)
            is not None
        )
    _join_school(sm, team.lead, _add_school(sm))
    with sm() as session:
        assert (
            assistant_has_permission(session, team.helper, team.lead, TeamPermission.VIEW_RESULTS)
            is None
        )


def test_the_permission_lookup_and_the_school_refusal_are_one_statement(
    sm: sessionmaker[Session],
) -> None:
    team = _Team(sm)
    _join_school(sm, team.lead, _add_school(sm))
    statements: list[str] = []
    with sm() as session:
        engine = session.get_bind()

        def _count(*args: object) -> None:
            statements.append(str(args[2]))

        event.listen(engine, "before_cursor_execute", _count)
        try:
            assistant_has_permission(session, team.helper, team.lead, TeamPermission.VIEW_RESULTS)
        finally:
            event.remove(engine, "before_cursor_execute", _count)
    assert len(statements) == 1, statements


def test_an_acting_assistant_is_audited_and_the_event_carries_ids_only(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm)
    client = _client(sm, team.helper, tmp_path)
    with structlog.testing.capture_logs() as logs:
        resp = client.get("/api/teacher/classes", headers=_acting_for(team.lead))
    assert resp.status_code == 200
    acting = [row for row in logs if row["event"] == "team_acting"]
    assert len(acting) == 1
    event_row = acting[0]
    assert event_row["actor_user_id"] == str(team.helper)
    assert event_row["lead_teacher_user_id"] == str(team.lead)
    assert event_row["permission"] == "view_results"
    assert event_row["member_id"]
    uuid.UUID(str(event_row["member_id"]))
    assert set(event_row) == {
        "event",
        "log_level",
        "actor_user_id",
        "lead_teacher_user_id",
        "member_id",
        "permission",
    }
    assert "@" not in repr(event_row)


def test_no_audit_event_on_the_self_path_or_a_refusal(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    team = _Team(sm)
    lead_client = _client(sm, team.lead, tmp_path)
    with structlog.testing.capture_logs() as self_logs:
        assert lead_client.get("/api/teacher/classes").status_code == 200
        assert (
            lead_client.get("/api/teacher/classes", headers=_acting_for(team.lead)).status_code
            == 200
        )
    assert [row for row in self_logs if row["event"] == "team_acting"] == []

    _join_school(sm, team.lead, _add_school(sm))
    helper_client = _client(sm, team.helper, tmp_path)
    with structlog.testing.capture_logs() as refused_logs:
        resp = helper_client.get("/api/teacher/classes", headers=_acting_for(team.lead))
    assert resp.status_code == 403
    assert [row for row in refused_logs if row["event"] == "team_acting"] == []
