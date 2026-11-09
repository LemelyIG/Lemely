"""Assistants acting on the lead teacher's classes through adopted routes (spec §2.3, §7)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import ClassEnrollment, Invite, SchoolClass
from lemely.db.models.enums import Role
from lemely.db.models.ops import Announcement
from lemely.db.models.team import AssistantRole
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.web.app import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_announcement_service,
    get_auth_context,
    get_class_service,
    get_invite_service,
    get_notification_service,
    get_push_transport,
    get_teacher_team_store,
)
from lemely.web.push import RecordingPushTransport
from tests.team_db import (
    add_assistant,
    add_class,
    add_user,
    emptied_after,
    enrol,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

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
