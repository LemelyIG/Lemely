"""Assistants acting on the lead teacher's classes through adopted routes (spec §2.3, §7)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.class_repo import ClassService
from lemely.db.deletion_repo import TeacherPaperDeletionService
from lemely.db.invite_repo import InviteService
from lemely.db.models import ClassEnrollment, Invite, SchoolClass
from lemely.db.models.enums import Role
from lemely.db.models.ops import Announcement
from lemely.db.models.team import AssistantRole
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.db.review_repo import ReviewService
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.db.teacher_team_repo import TeacherTeamStore
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
    get_quiz_service,
    get_review_service,
    get_scheme_corpus_repo,
    get_storage_backend,
    get_student_profile_service,
    get_teacher_paper_deletion_service,
    get_teacher_paper_repo,
    get_teacher_team_store,
)
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import teacher as teacher_router
from tests.pdf_fakes import born_digital_text_pdf
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
from tests.test_web_review import (
    _question,
    _seed_boxed_review_item,
    _seed_console_paper,
    _synthetic_scan,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def build_app(sm: sessionmaker[Session], user: uuid.UUID, role: Role = Role.teacher) -> FastAPI:
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
    return app


def as_user(sm: sessionmaker[Session], user: uuid.UUID, role: Role = Role.teacher) -> TestClient:
    return TestClient(build_app(sm, user, role))


def _class_exists(sm: sessionmaker[Session], class_id: uuid.UUID) -> bool:
    with sm() as session:
        return session.get(SchoolClass, class_id) is not None


def _enrolled(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> bool:
    with sm() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ClassEnrollment)
            .where(ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student)
        )
    return bool(count)


def _announcement_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return session.scalar(select(func.count()).select_from(Announcement)) or 0


def _team(sm: sessionmaker[Session], role: AssistantRole) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A lead with one class (one student enrolled) and an assistant of ``role``."""
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, _ = add_class(sm, teacher_id=lead, subject_code="0580")
    enrol(sm, class_id, add_user(sm))
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=role)
    return lead, helper, class_id


def acting_for(lead: uuid.UUID) -> dict[str, str]:
    return {ACTING_TEACHER_HEADER: str(lead)}


def test_the_lead_without_header_is_unchanged(sm: sessionmaker[Session]) -> None:
    lead, _, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, lead).get(f"/api/classes/{class_id}/roster")
    assert resp.status_code == 200
    assert len(resp.json()["students"]) == 1


def test_a_school_admin_without_header_is_unchanged(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.school_admin)
    client = as_user(sm, admin, Role.school_admin)
    assert client.get("/api/teacher/classes").status_code == 200
    assert client.get("/api/teacher/announcements").status_code == 200


def test_a_school_admin_cannot_borrow_a_teacher_with_the_header(
    sm: sessionmaker[Session],
) -> None:
    lead, _, class_id = _team(sm, AssistantRole.co_teacher)
    admin = add_user(sm, Role.school_admin)
    resp = as_user(sm, admin, Role.school_admin).get(
        f"/api/classes/{class_id}/roster", headers=acting_for(lead)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_a_viewer_reads_the_leads_roster(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).get(f"/api/classes/{class_id}/roster", headers=acting_for(lead))
    assert resp.status_code == 200
    assert len(resp.json()["students"]) == 1


def test_a_viewer_reads_the_leads_class_list_detail_analytics_and_papers(
    sm: sessionmaker[Session],
) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    client = as_user(sm, helper)
    headers = acting_for(lead)
    listing = client.get("/api/teacher/classes", headers=headers)
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["classes"]] == [str(class_id)]
    for path in (
        f"/api/classes/{class_id}",
        f"/api/classes/{class_id}/analytics",
        f"/api/classes/{class_id}/papers",
    ):
        assert client.get(path, headers=headers).status_code == 200, path


def test_without_the_header_the_assistant_sees_only_their_own_classes(
    sm: sessionmaker[Session],
) -> None:
    _, helper, _ = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).get("/api/teacher/classes")
    assert resp.status_code == 200
    assert resp.json()["classes"] == []


def test_a_viewer_cannot_delete_the_leads_class(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).delete(f"/api/classes/{class_id}", headers=acting_for(lead))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    assert _class_exists(sm, class_id)


def test_a_co_teacher_deletes_the_leads_class(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).delete(f"/api/classes/{class_id}", headers=acting_for(lead))
    assert resp.status_code == 204
    assert not _class_exists(sm, class_id)


def test_a_co_teacher_creates_a_class_owned_by_the_lead(sm: sessionmaker[Session]) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).post(
        "/api/classes", json={"name": "Made by the assistant"}, headers=acting_for(lead)
    )
    assert resp.status_code == 201
    with sm() as session:
        made = session.get(SchoolClass, uuid.UUID(resp.json()["id"]))
    assert made is not None
    assert made.teacher_id == lead


def test_a_viewer_cannot_create_a_class(sm: sessionmaker[Session]) -> None:
    lead, helper, _ = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).post("/api/classes", json={"name": "Nope"}, headers=acting_for(lead))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_a_marker_cannot_remove_students(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, _ = add_class(sm, teacher_id=lead)
    student = add_user(sm)
    enrol(sm, class_id, student)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.marker)
    resp = as_user(sm, helper).delete(
        f"/api/classes/{class_id}/students/{student}", headers=acting_for(lead)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    assert _enrolled(sm, class_id, student)


def test_a_co_teacher_removes_a_student_from_the_leads_class(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, _ = add_class(sm, teacher_id=lead)
    student = add_user(sm)
    enrol(sm, class_id, student)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    resp = as_user(sm, helper).delete(
        f"/api/classes/{class_id}/students/{student}", headers=acting_for(lead)
    )
    assert resp.status_code == 204
    assert not _enrolled(sm, class_id, student)


def test_a_viewer_cannot_unshare_a_paper(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).post(
        f"/api/classes/{class_id}/papers/{uuid.uuid4()}/unshare", headers=acting_for(lead)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_a_co_teacher_mints_a_class_invite_as_the_lead(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).post(
        f"/api/school/classes/{class_id}/invite-code", headers=acting_for(lead)
    )
    assert resp.status_code == 200
    with sm() as session:
        invite = session.scalars(select(Invite).where(Invite.code == resp.json()["code"])).one()
    assert invite.created_by == lead


def test_a_viewer_cannot_mint_a_class_invite(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).post(
        f"/api/school/classes/{class_id}/invite-code", headers=acting_for(lead)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_a_stranger_with_the_header_is_403(sm: sessionmaker[Session]) -> None:
    lead, _, class_id = _team(sm, AssistantRole.co_teacher)
    stranger = add_user(sm, Role.teacher)
    resp = as_user(sm, stranger).get(f"/api/classes/{class_id}/roster", headers=acting_for(lead))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_an_assistant_without_header_cannot_touch_the_leads_class(
    sm: sessionmaker[Session],
) -> None:
    _, helper, class_id = _team(sm, AssistantRole.co_teacher)
    assert as_user(sm, helper).get(f"/api/classes/{class_id}/roster").status_code == 403


def test_the_header_reaches_only_the_leads_own_classes(sm: sessionmaker[Session]) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    other_teacher = add_user(sm, Role.teacher)
    other_class, _ = add_class(sm, teacher_id=other_teacher)
    client = as_user(sm, helper)
    resp = client.delete(f"/api/classes/{other_class}", headers=acting_for(lead))
    assert resp.status_code == 403
    assert "team_permission_denied" not in str(resp.json()["detail"])  # the ownership check refused
    assert _class_exists(sm, other_class)
    roster = client.get(f"/api/classes/{other_class}/roster", headers=acting_for(lead))
    assert roster.status_code == 403


def test_a_co_teacher_posts_an_announcement_as_the_lead(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).post(
        "/api/teacher/announcements",
        json={"title": "Hello", "body": "Exam moved", "classIds": [str(class_id)]},
        headers=acting_for(lead),
    )
    assert resp.status_code == 200
    posted = resp.json()["announcements"]
    assert [row["authorId"] for row in posted] == [str(lead)]


def test_a_viewer_lists_the_leads_announcements_but_cannot_post(
    sm: sessionmaker[Session],
) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    as_user(sm, lead).post(
        "/api/teacher/announcements",
        json={"title": "From the lead", "body": "b", "classIds": [str(class_id)]},
    )
    client = as_user(sm, helper)
    listing = client.get("/api/teacher/announcements", headers=acting_for(lead))
    assert listing.status_code == 200
    assert [row["title"] for row in listing.json()["announcements"]] == ["From the lead"]
    before = _announcement_count(sm)
    denied = client.post(
        "/api/teacher/announcements",
        json={"title": "Nope", "body": "b", "classIds": [str(class_id)]},
        headers=acting_for(lead),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "team_permission_denied"
    assert _announcement_count(sm) == before


def test_without_the_header_an_assistant_lists_only_their_own_announcements(
    sm: sessionmaker[Session],
) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    as_user(sm, lead).post(
        "/api/teacher/announcements",
        json={"title": "From the lead", "body": "b", "classIds": [str(class_id)]},
    )
    listing = as_user(sm, helper).get("/api/teacher/announcements")
    assert listing.status_code == 200
    assert listing.json()["announcements"] == []


def test_a_co_teacher_deletes_the_leads_announcement(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    created = as_user(sm, lead).post(
        "/api/teacher/announcements",
        json={"title": "t", "body": "b", "classIds": [str(class_id)]},
    )
    announcement_id = created.json()["announcements"][0]["announcementId"]
    resp = as_user(sm, helper).delete(
        f"/api/teacher/announcements/{announcement_id}", headers=acting_for(lead)
    )
    assert resp.status_code == 204
    assert _announcement_count(sm) == 0


def test_a_viewer_cannot_delete_the_leads_announcement(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    created = as_user(sm, lead).post(
        "/api/teacher/announcements",
        json={"title": "t", "body": "b", "classIds": [str(class_id)]},
    )
    announcement_id = created.json()["announcements"][0]["announcementId"]
    resp = as_user(sm, helper).delete(
        f"/api/teacher/announcements/{announcement_id}", headers=acting_for(lead)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    assert _announcement_count(sm) == 1


def test_the_header_cannot_reach_another_leads_announcement(sm: sessionmaker[Session]) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    other = add_user(sm, Role.teacher)
    other_class, _ = add_class(sm, teacher_id=other)
    created = as_user(sm, other).post(
        "/api/teacher/announcements",
        json={"title": "t", "body": "b", "classIds": [str(other_class)]},
    )
    announcement_id = created.json()["announcements"][0]["announcementId"]
    resp = as_user(sm, helper).delete(
        f"/api/teacher/announcements/{announcement_id}", headers=acting_for(lead)
    )
    assert resp.status_code == 403
    assert _announcement_count(sm) == 1


# ---------------------------------------------------------------------------
# teacher.py, quiz.py and review.py (Phase 03 Task 9).
# ---------------------------------------------------------------------------


def _quiz_and_paper_app(sm: sessionmaker[Session], user: uuid.UUID) -> TestClient:
    app = build_app(sm, user)
    classes = ClassService(sm)
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(
        sm, classes, QuestionBankService(sm)
    )
    app.dependency_overrides[get_teacher_paper_repo] = lambda: TeacherPaperRepository(
        sm, stale_after=timedelta(minutes=10)
    )
    return TestClient(app)


def test_a_viewer_lists_the_leads_quizzes(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    QuizService(sm, ClassService(sm), QuestionBankService(sm)).create_quiz(
        lead, "0580", "Lead quiz"
    )
    resp = _quiz_and_paper_app(sm, helper).get(
        "/api/teacher/quizzes", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 200
    assert [q["title"] for q in resp.json()["quizzes"]] == ["Lead quiz"]


def test_a_marker_cannot_create_quizzes_but_a_co_teacher_creates_them_as_the_lead(
    sm: sessionmaker[Session],
) -> None:
    lead, marker, co = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    add_subject(sm, "0580")
    add_assistant(sm, teacher_id=lead, assistant_id=marker, role=AssistantRole.marker)
    add_assistant(sm, teacher_id=lead, assistant_id=co, role=AssistantRole.co_teacher)
    body = {"subjectCode": "0580", "title": "Made by an assistant"}
    as_lead = {ACTING_TEACHER_HEADER: str(lead)}
    denied = _quiz_and_paper_app(sm, marker).post(
        "/api/teacher/quizzes", json=body, headers=as_lead
    )
    assert denied.status_code == 403
    created = _quiz_and_paper_app(sm, co).post("/api/teacher/quizzes", json=body, headers=as_lead)
    assert created.status_code == 201
    listed = _quiz_and_paper_app(sm, lead).get("/api/teacher/quizzes").json()["quizzes"]
    assert [q["title"] for q in listed] == ["Made by an assistant"]


def _make_paper(sm: sessionmaker[Session], uploader: uuid.UUID) -> uuid.UUID:
    return TeacherPaperRepository(sm, stale_after=timedelta(minutes=10)).create(
        paper_id=uuid.uuid4(),
        uploaded_by=uploader,
        storage_path=f"papers/{uploader}/scan.pdf",
        scheme_storage_path=None,
        original_filename="scan.pdf",
        content_type="application/pdf",
        byte_size=10,
    )


def test_a_viewer_sees_the_leads_papers_but_cannot_regrade(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    paper_id = _make_paper(sm, lead)
    client = _quiz_and_paper_app(sm, helper)
    as_lead = {ACTING_TEACHER_HEADER: str(lead)}
    listed = client.get("/api/papers", headers=as_lead)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()["papers"]] == [str(paper_id)]
    assert client.get("/api/papers").json()["papers"] == []  # as themselves: nothing
    regrade = client.post(f"/api/papers/{paper_id}/regrade", headers=as_lead)
    assert regrade.status_code == 403
    assert regrade.json()["detail"]["code"] == "team_permission_denied"


def _console_app(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    tmp_path: Path,
    *,
    role: Role = Role.teacher,
    storage: FakeStorageBackend | None = None,
) -> TestClient:
    """Every collaborator the teacher, quiz and review routers resolve, on the test database."""
    app = build_app(sm, user, role)
    classes = ClassService(sm)
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(
        sm, classes, QuestionBankService(sm)
    )
    papers = TeacherPaperRepository(sm, stale_after=timedelta(minutes=10))
    app.dependency_overrides[get_teacher_paper_repo] = lambda: papers
    app.dependency_overrides[get_teacher_paper_deletion_service] = lambda: (
        TeacherPaperDeletionService(sm)
    )
    app.dependency_overrides[get_review_service] = lambda: ReviewService(sm, classes)
    app.dependency_overrides[get_at_risk_ack_service] = lambda: AtRiskAckService(sm, classes)
    app.dependency_overrides[get_student_profile_service] = lambda: StudentProfileService(sm)
    app.dependency_overrides[get_history_store] = lambda: HistoryStore(tmp_path / "history")
    fake_storage = storage if storage is not None else FakeStorageBackend()
    app.dependency_overrides[get_storage_backend] = lambda: fake_storage
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock()
    app.dependency_overrides[get_scheme_corpus_repo] = lambda: MagicMock()
    return TestClient(app)


def test_the_lead_without_header_still_sees_their_own_papers_and_quizzes(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead = add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    paper_id = _make_paper(sm, lead)
    QuizService(sm, ClassService(sm), QuestionBankService(sm)).create_quiz(lead, "0580", "Mine")
    client = _console_app(sm, lead, tmp_path)
    assert [p["id"] for p in client.get("/api/papers").json()["papers"]] == [str(paper_id)]
    assert [q["title"] for q in client.get("/api/teacher/quizzes").json()["quizzes"]] == ["Mine"]
    assert client.get("/api/grading/queue").status_code == 200


def test_a_platform_admin_without_header_is_unchanged(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    admin = add_user(sm, Role.platform_admin)
    client = _console_app(sm, admin, tmp_path, role=Role.platform_admin)
    for path in (
        "/api/papers",
        "/api/papers/deleted",
        "/api/grading/queue",
        "/api/teacher/overview",
        "/api/teacher/at-risk",
        "/api/teacher/quizzes",
        "/api/teacher/review",
    ):
        assert client.get(path).status_code == 200, path


def test_a_platform_admin_cannot_borrow_a_teacher_with_the_header(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, _, _ = _team(sm, AssistantRole.co_teacher)
    admin = add_user(sm, Role.platform_admin)
    client = _console_app(sm, admin, tmp_path, role=Role.platform_admin)
    for path in ("/api/papers", "/api/teacher/quizzes", "/api/teacher/review"):
        resp = client.get(path, headers=acting_for(lead))
        assert resp.status_code == 403, path
        assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_a_viewer_reads_the_leads_paper_detail_and_the_queue_overview_and_at_risk(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, _ = _team(sm, AssistantRole.viewer)
    paper_id = _make_paper(sm, lead)
    client = _console_app(sm, helper, tmp_path)
    headers = acting_for(lead)
    detail = client.get(f"/api/papers/{paper_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == str(paper_id)
    assert client.get(f"/api/papers/{paper_id}").status_code == 404  # as themselves
    for path in ("/api/grading/queue", "/api/teacher/overview", "/api/teacher/at-risk"):
        assert client.get(path, headers=headers).status_code == 200, path
    assert client.get("/api/papers/deleted", headers=headers).status_code == 200


def test_the_header_cannot_reach_another_leads_paper(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    other_paper = _make_paper(sm, add_user(sm, Role.teacher))
    own_paper = _make_paper(sm, lead)
    client = _console_app(sm, helper, tmp_path)
    headers = acting_for(lead)
    listed = client.get("/api/papers", headers=headers).json()["papers"]
    assert [p["id"] for p in listed] == [str(own_paper)]
    assert client.get(f"/api/papers/{other_paper}", headers=headers).status_code == 404
    assert client.delete(f"/api/papers/{other_paper}", headers=headers).status_code == 404
    assert client.get(f"/api/papers/{other_paper}/preview", headers=headers).status_code == 404


def test_a_co_teacher_deletes_and_restores_the_leads_paper_a_viewer_cannot(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    viewer = add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    paper_id = _make_paper(sm, lead)
    headers = acting_for(lead)
    denied = _console_app(sm, viewer, tmp_path).delete(f"/api/papers/{paper_id}", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "team_permission_denied"
    client = _console_app(sm, helper, tmp_path)
    assert client.delete(f"/api/papers/{paper_id}", headers=headers).status_code == 204
    deleted = client.get("/api/papers/deleted", headers=headers).json()["papers"]
    assert [p["paperId"] for p in deleted] == [str(paper_id)]
    assert client.post(f"/api/papers/{paper_id}/restore", headers=headers).status_code == 204
    lead_papers = _console_app(sm, lead, tmp_path).get("/api/papers").json()["papers"]
    assert [p["id"] for p in lead_papers] == [str(paper_id)]


def test_a_marker_regrades_the_leads_paper_and_a_viewer_cannot(
    sm: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[uuid.UUID] = []
    monkeypatch.setattr(
        teacher_router,
        "_start_run_if_claimed",
        lambda paper_id, *_args, **_kwargs: started.append(paper_id),
    )
    lead, marker, viewer = (add_user(sm, Role.teacher) for _ in range(3))
    add_assistant(sm, teacher_id=lead, assistant_id=marker, role=AssistantRole.marker)
    add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    paper_id = _make_paper(sm, lead)
    headers = acting_for(lead)
    assert (
        _console_app(sm, viewer, tmp_path)
        .post(f"/api/papers/{paper_id}/regrade", headers=headers)
        .status_code
        == 403
    )
    assert started == []
    resp = _console_app(sm, marker, tmp_path).post(
        f"/api/papers/{paper_id}/regrade", headers=headers
    )
    assert resp.status_code == 202
    assert started == [paper_id]


def test_a_marker_cannot_regrade_another_leads_paper(
    sm: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[uuid.UUID] = []
    monkeypatch.setattr(
        teacher_router,
        "_start_run_if_claimed",
        lambda paper_id, *_args, **_kwargs: started.append(paper_id),
    )
    lead, marker = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=marker, role=AssistantRole.marker)
    other_paper = _make_paper(sm, add_user(sm, Role.teacher))
    resp = _console_app(sm, marker, tmp_path).post(
        f"/api/papers/{other_paper}/regrade", headers=acting_for(lead)
    )
    assert resp.status_code == 404
    assert started == []


def test_a_marker_uploads_a_paper_recorded_against_the_lead_a_viewer_cannot(
    sm: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[uuid.UUID] = []
    monkeypatch.setattr(
        teacher_router,
        "_start_run_if_claimed",
        lambda paper_id, *_args, **_kwargs: started.append(paper_id),
    )
    lead, marker, viewer = (add_user(sm, Role.teacher) for _ in range(3))
    add_assistant(sm, teacher_id=lead, assistant_id=marker, role=AssistantRole.marker)
    add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    files = {"scan": ("scan.pdf", born_digital_text_pdf(pages=1), "application/pdf")}
    headers = acting_for(lead)
    storage = FakeStorageBackend()
    denied = _console_app(sm, viewer, tmp_path, storage=storage).post(
        "/api/papers/upload", files=files, headers=headers
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "team_permission_denied"
    assert started == []
    resp = _console_app(sm, marker, tmp_path, storage=storage).post(
        "/api/papers/upload", files=files, headers=headers
    )
    assert resp.status_code == 200
    paper_id = uuid.UUID(resp.json()["paperId"])
    assert started == [paper_id]
    stored = TeacherPaperRepository(sm, stale_after=timedelta(minutes=10)).get(paper_id)
    assert stored is not None
    assert stored.uploaded_by == lead
    assert f"teacher/{lead}/" in stored.storage_path
    # The lead sees it; the marker, as themselves, does not.
    assert [
        p["id"] for p in _console_app(sm, lead, tmp_path).get("/api/papers").json()["papers"]
    ] == [str(paper_id)]
    assert _console_app(sm, marker, tmp_path).get("/api/papers").json()["papers"] == []


def test_quiz_tools_need_generate_quiz(sm: sessionmaker[Session], tmp_path: Path) -> None:
    lead, viewer = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    client = _console_app(sm, viewer, tmp_path)
    headers = acting_for(lead)
    for method, path in (
        ("get", "/api/quizzes/pools"),
        ("post", "/api/quizzes/preview"),
        ("post", "/api/quizzes/generate"),
    ):
        resp = client.request(method, path, headers=headers, json={} if method == "post" else None)
        assert resp.status_code == 403, path
        assert resp.json()["detail"]["code"] == "team_permission_denied", path
    # A viewer holds view_results, so the read-only pool count passes the guard.
    assert (
        client.get("/api/teacher/quizzes/pool-count?subjectCode=0580", headers=headers).status_code
        != 403
    )


def test_a_co_teacher_runs_the_whole_quiz_lifecycle_on_the_leads_quiz(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, co, viewer = (add_user(sm, Role.teacher) for _ in range(3))
    add_subject(sm, "0580")
    add_assistant(sm, teacher_id=lead, assistant_id=co, role=AssistantRole.co_teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    class_id, _ = add_class(sm, teacher_id=lead, subject_code="0580")
    quiz = QuizService(sm, ClassService(sm), QuestionBankService(sm)).create_quiz(
        lead, "0580", "Lead quiz"
    )
    headers = acting_for(lead)
    co_client = _console_app(sm, co, tmp_path)
    viewer_client = _console_app(sm, viewer, tmp_path)
    quiz_path = f"/api/teacher/quizzes/{quiz.quiz_id}"
    assert co_client.get(quiz_path, headers=headers).status_code == 200
    assert viewer_client.get(quiz_path, headers=headers).status_code == 200
    renamed = co_client.patch(quiz_path, json={"title": "Renamed"}, headers=headers)
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed"
    denied = viewer_client.patch(quiz_path, json={"title": "Nope"}, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "team_permission_denied"
    assert co_client.get(f"{quiz_path}/assignments", headers=headers).status_code == 200
    assert viewer_client.get(f"{quiz_path}/assignments", headers=headers).status_code == 200
    assigned = viewer_client.post(
        f"{quiz_path}/assignments", json={"classId": str(class_id)}, headers=headers
    )
    assert assigned.status_code == 403
    assert assigned.json()["detail"]["code"] == "team_permission_denied"
    own = _console_app(sm, lead, tmp_path).get(quiz_path)
    assert own.status_code == 200
    assert own.json()["quiz"]["title"] == "Renamed"


def test_the_header_cannot_reach_another_leads_quiz(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, co = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    other = add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    add_assistant(sm, teacher_id=lead, assistant_id=co, role=AssistantRole.co_teacher)
    foreign = QuizService(sm, ClassService(sm), QuestionBankService(sm)).create_quiz(
        other, "0580", "Foreign"
    )
    client = _console_app(sm, co, tmp_path)
    headers = acting_for(lead)
    path = f"/api/teacher/quizzes/{foreign.quiz_id}"
    assert client.get(path, headers=headers).status_code in (403, 404)
    assert client.patch(path, json={"title": "Taken"}, headers=headers).status_code in (403, 404)
    assert client.get("/api/teacher/quizzes", headers=headers).json()["quizzes"] == []
    titles = [
        q["title"]
        for q in _console_app(sm, other, tmp_path).get("/api/teacher/quizzes").json()["quizzes"]
    ]
    assert titles == ["Foreign"]


def test_a_co_teacher_works_the_leads_at_risk_acknowledgements_within_the_leads_roster(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    viewer = add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    with sm() as session:
        lead_student = session.scalars(
            select(ClassEnrollment.student_id).where(ClassEnrollment.class_id == class_id)
        ).one()
    stranger_student = add_user(sm)
    headers = acting_for(lead)
    client = _console_app(sm, helper, tmp_path)
    # In the lead's roster: past the roster check, the reason simply is not firing (422).
    inside = client.post(
        f"/api/teacher/at-risk/{lead_student}/acknowledge",
        json={"reason": "declining_trend"},
        headers=headers,
    )
    assert inside.status_code == 422
    # Outside the lead's roster: the lead's scope applies, not the assistant's (403).
    outside = client.post(
        f"/api/teacher/at-risk/{stranger_student}/acknowledge",
        json={"reason": "declining_trend"},
        headers=headers,
    )
    assert outside.status_code == 403
    assert (
        client.delete(
            f"/api/teacher/at-risk/{lead_student}/acknowledge/declining_trend", headers=headers
        ).status_code
        == 204
    )
    # A viewer lacks manage_students.
    viewer_client = _console_app(sm, viewer, tmp_path)
    denied = viewer_client.post(
        f"/api/teacher/at-risk/{lead_student}/acknowledge",
        json={"reason": "declining_trend"},
        headers=headers,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "team_permission_denied"
    denied_delete = viewer_client.delete(
        f"/api/teacher/at-risk/{lead_student}/acknowledge/declining_trend", headers=headers
    )
    assert denied_delete.status_code == 403
    assert denied_delete.json()["detail"]["code"] == "team_permission_denied"


def test_a_viewer_reads_a_students_detail_only_inside_the_leads_roster(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    with sm() as session:
        lead_student = session.scalars(
            select(ClassEnrollment.student_id).where(ClassEnrollment.class_id == class_id)
        ).one()
    stranger_student = add_user(sm)
    client = _console_app(sm, helper, tmp_path)
    headers = acting_for(lead)
    assert client.get(f"/api/teacher/students/{lead_student}", headers=headers).status_code == 200
    assert (
        client.get(f"/api/teacher/students/{stranger_student}", headers=headers).status_code == 403
    )
    assert client.get(f"/api/teacher/students/{lead_student}").status_code == 403  # as themselves


def _review_items(client: TestClient, headers: dict[str, str] | None = None) -> list[str]:
    resp = client.get("/api/teacher/review", headers=headers)
    assert resp.status_code == 200
    return [row["itemId"] for row in resp.json()["items"]]


def test_a_viewer_reads_the_leads_review_queue_but_cannot_resolve_or_dismiss(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, _ = _team(sm, AssistantRole.viewer)
    _seed_console_paper(sm, uploader=lead, questions=[_question("1a", awarded=1, maximum=2)])
    client = _console_app(sm, helper, tmp_path)
    headers = acting_for(lead)
    ids = _review_items(client, headers)
    assert len(ids) == 1
    assert _review_items(client) == []  # as themselves: nothing
    assert client.get(f"/api/teacher/review/{ids[0]}", headers=headers).status_code == 200
    for path, body in (
        (f"/api/teacher/review/{ids[0]}/resolve", {"note": "fine"}),
        (f"/api/teacher/review/{ids[0]}/dismiss", {"note": "n"}),
        ("/api/teacher/review/bulk-approve", {"itemIds": ids}),
    ):
        denied = client.post(path, json=body, headers=headers)
        assert denied.status_code == 403, path
        assert denied.json()["detail"]["code"] == "team_permission_denied", path
    assert _review_items(_console_app(sm, lead, tmp_path)) == ids  # nothing was closed


def test_a_marker_bulk_approves_resolves_and_dismisses_the_leads_review_items(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, _ = _team(sm, AssistantRole.marker)
    _seed_console_paper(
        sm,
        uploader=lead,
        questions=[
            _question("1a", awarded=1, maximum=2),
            _question("1c", awarded=1, maximum=2),
            _question(
                "2a",
                awarded=0,
                maximum=3,
                confidence_score=1.0,
                needs_review=False,
                plagiarism_flagged=True,
            ),
        ],
    )
    client = _console_app(sm, helper, tmp_path)
    headers = acting_for(lead)
    rows = client.get("/api/teacher/review", headers=headers).json()["items"]
    flagged = [r["itemId"] for r in rows if r["reason"] == "plagiarism_flag"]
    plain = [r["itemId"] for r in rows if r["reason"] != "plagiarism_flag"]
    assert len(flagged) == 1
    first, third = plain
    second = flagged[0]
    resolved = client.post(
        f"/api/teacher/review/{first}/resolve", json={"note": "fine"}, headers=headers
    )
    assert resolved.status_code == 200
    dismissed = client.post(
        f"/api/teacher/review/{second}/dismiss", json={"note": "fine"}, headers=headers
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    approved = client.post(
        "/api/teacher/review/bulk-approve", json={"itemIds": [third]}, headers=headers
    )
    assert approved.status_code == 200
    assert approved.json()["approved"] == [third]
    assert _review_items(_console_app(sm, lead, tmp_path)) == []


def test_the_header_cannot_reach_another_leads_review_items(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    other = add_user(sm, Role.teacher)
    _seed_console_paper(sm, uploader=other, questions=[_question("1a", awarded=1, maximum=2)])
    foreign_ids = _review_items(_console_app(sm, other, tmp_path))
    assert len(foreign_ids) == 1
    client = _console_app(sm, helper, tmp_path)
    headers = acting_for(lead)
    assert _review_items(client, headers) == []
    assert client.get(f"/api/teacher/review/{foreign_ids[0]}", headers=headers).status_code == 403
    assert (
        client.post(
            f"/api/teacher/review/{foreign_ids[0]}/dismiss", json={"note": "x"}, headers=headers
        ).status_code
        == 403
    )
    bulk = client.post(
        "/api/teacher/review/bulk-approve", json={"itemIds": foreign_ids}, headers=headers
    )
    assert bulk.status_code == 200
    assert bulk.json()["approved"] == []
    assert _review_items(_console_app(sm, other, tmp_path)) == foreign_ids


def test_a_viewer_reads_the_leads_whole_page_only_when_acting_for_the_lead(
    sm: sessionmaker[Session], tmp_path: Path
) -> None:
    storage = FakeStorageBackend()
    lead, item_id = _seed_boxed_review_item(
        sm, ClassService(sm), storage=storage, scan=_synthetic_scan()
    )
    helper = add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    client = _console_app(sm, helper, tmp_path, storage=storage)
    page_path = f"/api/teacher/review/{item_id}/page"
    allowed = client.get(page_path, headers=acting_for(lead))
    assert allowed.status_code == 200
    assert allowed.headers["content-type"] == "image/png"
    assert allowed.content.startswith(b"\x89PNG\r\n\x1a\n")
    # As themselves the assistant has no claim on the lead's student: refused, never an image.
    own = client.get(page_path)
    assert own.status_code == client.get(f"/api/teacher/review/{item_id}").status_code
    assert own.status_code in (403, 404)
    assert own.headers["content-type"] != "image/png"


def test_a_non_uuid_token_subject_is_rejected_by_the_guard_with_401(
    sm: sessionmaker[Session],
) -> None:
    # The team guard parses the subject before the handler runs: 401 where a bare handler said 422.
    app = build_app(sm, add_user(sm, Role.teacher))
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id="not-a-uuid", role=Role.teacher.value
    )
    assert TestClient(app).get("/api/papers").status_code == 401
