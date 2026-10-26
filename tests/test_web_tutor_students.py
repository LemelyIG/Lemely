"""T19 and T20: a tutor's students and the tutor's view of one (SPEC §b.2, §e.2, O2, O3, SC-11).

Route-level. Apps are built with ``tests.tutoring_app.app_with_routers`` through
``tests.test_tutor_grant_repo.grants_client`` (a lane never edits
``lemely/web/app.py``); ``create_app`` already serves the teacher routes, so the
parity test reads ``GET /api/teacher/students/{id}`` from the same app.

* T20's ``detail`` is the teacher route's response with acknowledgements removed,
  passed through ``project_for_tutor`` (SPEC §e.2: the route-level parity test
  that replaced the old one, F31).
* T20's JSON carries no key outside ``TutorStudentDetailDTO``; the allowed keys
  come from the DTO classes themselves and from the core at-risk evidence models
  (camel-cased), never from a list written here.
* Every ended grant answers one 403 ``access_ended`` with the same body (SC-11).
* A teacher without a tutor profile gets 404 ``no_tutor_profile`` on both (O1).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, get_args, get_origin

import pytest
import sqlalchemy as sa
from pydantic import BaseModel

from lemely.core.at_risk import (
    BelowTargetEvidence,
    DecliningTrendEvidence,
    InactivityEvidence,
    assess_at_risk,
    flag_fingerprint,
)
from lemely.db.at_risk_repo import AtRiskAckService
from lemely.db.class_repo import ClassService
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models.enums import GrantRevokeReason, Role
from lemely.db.models.profiles import StudentSubjectEnrolment
from lemely.web.schemas_analytics import StudentDetailDTO
from lemely.web.schemas_tutoring import TutorStudentDetailDTO
from lemely.web.student_detail_view import project_for_tutor
from tests.test_tutor_grant_repo import (
    add_grant,
    add_student,
    audit_rows,
    grants_client,
    link_parent,
    seed_history,
)
from tests.test_tutor_review_repo import add_booking
from tests.tutoring_db import (
    act_as,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
ACCESS_ENDED = {
    "detail": {
        "code": "access_ended",
        "message": "This student's progress is no longer shared with you.",
    }
}


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = grants_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def set_target(sm: sessionmaker[Session], student: uuid.UUID, subject: str, grade: str) -> None:
    with sm.begin() as session:
        session.add(
            StudentSubjectEnrolment(user_id=student, subject_code=subject, target_grade=grade)
        )


# ---------------------------------------------------------------------------
# The parity test (SPEC §e.2)
# ---------------------------------------------------------------------------


def _world_with_roster_and_grant(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """A teacher who teaches the student's class **and** holds a grant from them.

    Returns ``(teacher_user_id, student_id)``. The student has three declining
    papers, an inactivity streak and a target grade, so every at-risk rule fires.
    """
    add_subject(sm, code="0625", name="Physics")
    tutor = add_tutor(sm, subjects=["0625"])
    student = add_student(sm, display_name="Amelia")
    classes = ClassService(sm)
    made = classes.create_class(tutor.user_id, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(student, made.join_code)
    seed_history(sm, student)
    set_target(sm, student, "0625", "A")
    add_grant(sm, student, tutor)
    return tutor.user_id, student


def test_t20_equals_projection_of_teacher_route(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    teacher, student = _world_with_roster_and_grant(sm)
    # The teacher acknowledged one flag on T-05: the tutor's view must not carry it.
    history = DbHistoryStore(sm).load(str(student))
    flag = assess_at_risk(history, targets={"0625": "A"}, now=_now()).flags[0]
    AtRiskAckService(sm, ClassService(sm)).acknowledge(
        teacher, Role.teacher, student, flag.reason, flag_fingerprint(flag), note="Called home"
    )
    act_as(client, teacher, Role.teacher)

    teacher_view = client.get(f"/api/teacher/students/{student}")
    tutor_view = client.get(f"/api/tutor/students/{student}")

    assert teacher_view.status_code == 200, teacher_view.text
    assert tutor_view.status_code == 200, tutor_view.text
    teacher_json = teacher_view.json()
    assert any(f["acknowledged"] is not None for f in teacher_json["atRiskFlags"])  # red case
    for item in teacher_json["atRiskFlags"]:
        item["acknowledged"] = None
    expected = project_for_tutor(
        StudentDetailDTO.model_validate(teacher_json), zone="Africa/Cairo"
    ).model_dump(mode="json")
    assert tutor_view.json()["detail"] == expected
    # Non-vacuity: the compared detail has every part populated.
    detail = tutor_view.json()["detail"]
    assert detail["attempts"] and detail["trend"] and detail["weaknesses"] and detail["subjects"]
    assert {f["reason"] for f in detail["atRiskFlags"]} == {
        "declining_trend",
        "below_target",
        "inactive",
    }
    assert "Called home" not in tutor_view.text
    assert tutor_view.headers["cache-control"] == NO_STORE


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# No key outside the DTO (non-vacuity: >= 1 key compared per nested DTO)
# ---------------------------------------------------------------------------


def _model_of(annotation: object) -> type[BaseModel] | None:
    """The pydantic model inside ``annotation`` (``X``, ``X | None``, ``list[X]``), if any."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        found = _model_of(arg)
        if found is not None:
            return found
    return None


def _is_plain_dict(annotation: object) -> bool:
    if get_origin(annotation) is dict:
        return True
    return any(_is_plain_dict(arg) for arg in get_args(annotation))


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


#: Keys of the at-risk ``evidence`` dict: the core evidence models' fields, camel-cased
#: (the wire form ``_at_risk_flag_dto`` writes). Derived, not listed.
EVIDENCE_KEYS = frozenset(
    _camel(name)
    for model in (DecliningTrendEvidence, BelowTargetEvidence, InactivityEvidence)
    for name in model.model_fields
)


def _check_keys(
    value: object, model: type[BaseModel], compared: dict[str, int], path: str
) -> list[str]:
    """Every key of ``value`` outside ``model``'s fields, walking nested DTOs."""
    if not isinstance(value, dict):
        return [f"{path}: not an object"]
    problems = [f"{path}.{key}" for key in value if key not in model.model_fields]
    compared[model.__name__] = compared.get(model.__name__, 0) + len(value)
    for name, field in model.model_fields.items():
        if name not in value or value[name] is None:
            continue
        nested = _model_of(field.annotation)
        item = value[name]
        if nested is not None:
            for index, element in enumerate(item if isinstance(item, list) else [item]):
                problems += _check_keys(element, nested, compared, f"{path}.{name}[{index}]")
        elif _is_plain_dict(field.annotation):
            problems += [f"{path}.{name}.{k}" for k in item if k not in EVIDENCE_KEYS]
            compared["evidence"] = compared.get("evidence", 0) + len(item)
    return problems


def _nested_models(model: type[BaseModel], seen: set[str]) -> set[str]:
    seen.add(model.__name__)
    for field in model.model_fields.values():
        nested = _model_of(field.annotation)
        if nested is not None and nested.__name__ not in seen:
            _nested_models(nested, seen)
    return seen


def test_t20_json_has_no_key_outside_dto(sm: sessionmaker[Session], client: TestClient) -> None:
    teacher, student = _world_with_roster_and_grant(sm)
    act_as(client, teacher, Role.teacher)
    # Give the teacher's acknowledgement a row, so a leak of it would show as a key.
    history = DbHistoryStore(sm).load(str(student))
    flag = assess_at_risk(history, targets={"0625": "A"}, now=_now()).flags[0]
    AtRiskAckService(sm, ClassService(sm)).acknowledge(
        teacher, Role.teacher, student, flag.reason, flag_fingerprint(flag)
    )

    body = client.get(f"/api/tutor/students/{student}").json()

    compared: dict[str, int] = {}
    assert _check_keys(body, TutorStudentDetailDTO, compared, "$") == []
    # Non-vacuity: at least one key compared in every nested DTO the response can carry,
    # except the teacher-only acknowledgement, which the projection always nulls.
    expected_models = _nested_models(TutorStudentDetailDTO, set()) - {"AtRiskAcknowledgementDTO"}
    assert expected_models <= set(compared)
    assert all(compared[name] >= 1 for name in expected_models)
    assert compared["evidence"] >= 1
    assert len(expected_models) >= 8
    assert {"lastActiveAt", "percentages", "targetGrade"} <= EVIDENCE_KEYS


# ---------------------------------------------------------------------------
# 403 access_ended: one code, one body, every reason (SC-11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ending",
    [
        "student_revoked",
        "block_revoked",
        "active_block_not_yet_swept",
        "tutor_suspended",
        "tutor_closed",
        "listing_rejected",
        "expired",
    ],
)
def test_authz_t20_reason_code_generic_access_ended(
    sm: sessionmaker[Session], client: TestClient, ending: str
) -> None:
    state = {
        "tutor_suspended": "suspended",
        "tutor_closed": "closed",
        "listing_rejected": "rejected",
    }.get(ending, "listed")
    tutor = add_tutor(sm, state=state)
    student = add_student(sm)
    revoked = {
        "student_revoked": GrantRevokeReason.student,
        "block_revoked": GrantRevokeReason.block,
        "tutor_suspended": GrantRevokeReason.tutor_suspended,
        "tutor_closed": GrantRevokeReason.tutor_closed,
    }.get(ending)
    add_grant(
        sm,
        student,
        tutor,
        revoked=revoked,
        created_ago=timedelta(days=10),
        expires_in=-timedelta(days=1) if ending == "expired" else None,
    )
    if ending in ("block_revoked", "active_block_not_yet_swept"):
        add_block(sm, student, tutor.user_id)
    act_as(client, tutor.user_id, Role.teacher)

    response = client.get(f"/api/tutor/students/{student}")

    assert response.status_code == 403
    assert response.json() == ACCESS_ENDED
    assert response.headers["cache-control"] == NO_STORE
    for word in ("block", "suspend", "revok", "closed", "expir", "reject"):
        assert word not in response.text.lower()
    assert audit_rows(sm) == []
    # T19 does not list the student either.
    listing = client.get("/api/tutor/students")
    assert listing.status_code == 200
    assert listing.json() == {"items": [], "nextCursor": None}


def test_t19_t20_404_no_tutor_profile(sm: sessionmaker[Session], client: TestClient) -> None:
    teacher = add_user(sm, Role.teacher)
    student = add_student(sm)
    act_as(client, teacher, Role.teacher)
    for path in ("/api/tutor/students", f"/api/tutor/students/{student}"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["detail"]["code"] == "no_tutor_profile"
        assert response.headers["cache-control"] == NO_STORE
    assert audit_rows(sm) == []


def test_t20_malformed_id_422_no_store(sm: sessionmaker[Session], client: TestClient) -> None:
    tutor = add_tutor(sm)
    act_as(client, tutor.user_id, Role.teacher)
    response = client.get("/api/tutor/students/not-a-uuid")
    assert response.status_code == 422
    assert response.headers["cache-control"] == NO_STORE
    assert audit_rows(sm) == []


# ---------------------------------------------------------------------------
# T19 and T20 success
# ---------------------------------------------------------------------------


def test_t20_success_shape_and_one_detail_row(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    add_subject(sm, code="0625", name="Physics")
    tutor = add_tutor(sm)
    student = add_student(sm, display_name="amelia@example.com")  # never shown to a tutor
    seed_history(sm, student)
    grant = add_grant(sm, student, tutor)
    act_as(client, tutor.user_id, Role.teacher)

    response = client.get(f"/api/tutor/students/{student}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"detail", "grantId", "grantedAt", "accessRecordedAt"}
    assert body["grantId"] == str(grant)
    assert body["detail"]["studentId"] == str(student)
    assert body["detail"]["displayName"].startswith("Student ")
    assert "@" not in response.text
    rows = audit_rows(sm)
    assert rows == [(grant, student, tutor.profile_id, "Sara M.", "detail")]
    with sm() as session:
        accessed = session.execute(
            sa.text("SELECT accessed_at FROM tutor_access_audit")
        ).scalar_one()
    assert body["accessRecordedAt"] == accessed.astimezone(UTC).isoformat()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*\+00:00", body["grantedAt"])


def test_t19_lists_valid_grants_with_upcoming_counts_and_pages(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, subjects=[subject])
    older = add_student(sm, display_name="Omar")
    newer = add_student(sm, display_name="Lina")
    older_grant = add_grant(sm, older, tutor, created_ago=timedelta(days=9))
    newer_grant = add_grant(sm, newer, tutor, created_ago=timedelta(days=2))
    add_grant(sm, add_student(sm), tutor, revoked=GrantRevokeReason.student)
    add_booking(
        sm,
        student=newer,
        tutor=tutor,
        subject=subject,
        state="accepted",
        ended_ago=-timedelta(days=3),
    )
    act_as(client, tutor.user_id, Role.teacher)

    first = client.get("/api/tutor/students", params={"limit": 1})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert page["items"] == [
        {
            "studentId": str(newer),
            "displayName": "Lina",
            "grantId": str(newer_grant),
            "grantedAt": page["items"][0]["grantedAt"],
            "upcomingSessions": 1,
        }
    ]
    second = client.get("/api/tutor/students", params={"limit": 1, "cursor": page["nextCursor"]})
    assert [i["grantId"] for i in second.json()["items"]] == [str(older_grant)]
    assert second.json()["items"][0]["upcomingSessions"] == 0
    assert second.json()["nextCursor"] is None
    assert sorted(r[1] for r in audit_rows(sm)) == sorted([newer, older])
    # O21: another list's cursor, or a tampered one, is a 422 and writes nothing.
    for bad in ("not-a-cursor", "eyJlIjoidHV0b3JfcmV2aWV3cyIsImsiOltdfQ"):
        refused = client.get("/api/tutor/students", params={"cursor": bad})
        assert refused.status_code == 422
        assert refused.json()["detail"]["code"] == "invalid_cursor"
    assert len(audit_rows(sm)) == 2
    assert client.get("/api/tutor/students", params={"limit": 51}).status_code == 422


def test_tutor_responses_never_reveal_parent_link_presence(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """SC-9: T19 and T20 read the same for a student with linked parents and without."""
    add_subject(sm, code="0625", name="Physics")
    tutor = add_tutor(sm)
    student = add_student(sm)
    seed_history(sm, student)
    add_grant(sm, student, tutor)
    act_as(client, tutor.user_id, Role.teacher)

    def scrubbed() -> tuple[object, object]:
        detail = client.get(f"/api/tutor/students/{student}").json()
        detail.pop("accessRecordedAt")
        return client.get("/api/tutor/students").json(), detail

    before = scrubbed()
    link_parent(sm, student)
    link_parent(sm, student)
    after = scrubbed()

    assert after == before
    assert "parent" not in str(after).lower()
