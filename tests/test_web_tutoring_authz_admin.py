"""Object-level rules for tutor evidence and the admin tutor routes (SPEC §c.3 O15, O17, O20).

* **O20.** Evidence delete is scoped ``WHERE tutor_profile_id = :caller_profile``:
  another tutor's evidence id is a 404, and nothing is removed.
* **O17.** Evidence files are never served to non-admins; the admin gets
  300 s attachment URLs on A2 only. Proved from the routes themselves (only
  A2 can return a URL) and from real responses (T1 and T6 carry metadata only;
  A3 and A4 send ``signedUrl: null``).
* **O15, admin half.** No platform-admin tutor route returns granted analytics:
  no ``StudentDetailDTO`` field, no notes.
* Role halves: a platform admin cannot use the tutor evidence routes, and a
  teacher cannot use the admin routes (the generated sweep in
  ``tests/test_authz_matrix_complete.py`` repeats this once the lead mounts them).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, get_args, get_origin

import pytest
import sqlalchemy as sa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from lemely.db.models.enums import Role
from lemely.db.models.tutoring import TutorEvidenceFile
from lemely.web.routers import (
    admin_tutors,
    tutor_evidence,
    tutor_profile,
    tutoring_directory,
    tutoring_public,
)
from lemely.web.schemas_analytics import StudentDetailDTO
from lemely.web.schemas_tutoring import NoteDTO, SubjectRefDTO
from tests.storage_fakes import FakeStorageBackend
from tests.test_web_admin_tutoring import PDF, admin_tutoring_client, seed_evidence
from tests.tutoring_app import flatten_routes
from tests.tutoring_db import act_as, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

_TUTORING_ROUTERS = (
    tutoring_public,
    tutoring_directory,
    tutor_profile,
    tutor_evidence,
    admin_tutors,
)


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def storage() -> FakeStorageBackend:
    return FakeStorageBackend()


@pytest.fixture
def client(sm: sessionmaker[Session], storage: FakeStorageBackend) -> Iterator[TestClient]:
    test_client = admin_tutoring_client(sm, storage)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# O20
# ---------------------------------------------------------------------------


def test_idor_t7_cannot_delete_other_tutors_evidence(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    owner = add_tutor(sm, state="listed")
    other = add_tutor(sm, state="listed")
    evidence_id = seed_evidence(sm, storage, owner.profile_id)
    act_as(client, other.user_id, Role.teacher)

    refused = client.delete(f"/api/tutor/profile/evidence/{evidence_id}")

    assert refused.status_code == 404
    assert refused.json()["detail"]["code"] == "evidence_not_found"
    with sm() as session:
        assert session.get(TutorEvidenceFile, evidence_id) is not None
    assert len(storage._objects) == 1
    # The other tutor cannot see it either, and the owner still can.
    assert client.get("/api/tutor/profile").json()["evidence"] == []
    act_as(client, owner.user_id, Role.teacher)
    assert [e["evidenceId"] for e in client.get("/api/tutor/profile").json()["evidence"]] == [
        str(evidence_id)
    ]
    # Red case: the owner's own delete succeeds, so the 404 above is the scope, not a broken route.
    assert client.delete(f"/api/tutor/profile/evidence/{evidence_id}").status_code == 204


# ---------------------------------------------------------------------------
# O17
# ---------------------------------------------------------------------------


def _model_fields(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    """Every field name reachable from ``model`` through nested models, lists and unions."""
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        for nested in _models_in(field.annotation):
            names |= _model_fields(nested, seen)
    return names


def _models_in(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    if get_origin(annotation) is not None or get_args(annotation):
        for arg in get_args(annotation):
            found.extend(_models_in(arg))
    return found


def _routes() -> list[tuple[str, str, APIRoute]]:
    return [
        (method, route.path, route)
        for module in _TUTORING_ROUTERS
        for route in flatten_routes(module.router)
        for method in sorted(route.methods)
    ]


def test_o17_only_a2_and_its_detail_siblings_can_carry_an_evidence_url() -> None:
    """``signedUrl`` exists only on admin responses; every other tutoring response lacks it."""
    routes = _routes()
    carrying = {
        (method, path)
        for method, path, route in routes
        if route.response_model is not None
        and "signedUrl" in _model_fields(_models_in(route.response_model)[0])
    }
    # Non-vacuity: the scan saw every route of the five routers mounted so far.
    assert len(routes) >= 16
    assert carrying == {
        ("GET", "/api/admin/tutors/{tutor_id}"),
        ("POST", "/api/admin/tutors/{tutor_id}/approve"),
        ("POST", "/api/admin/tutors/{tutor_id}/reject"),
    }
    for method, path, route in routes:
        if (method, path) in carrying:
            assert path.startswith("/api/admin/"), (method, path, route.name)


def test_o17_tutor_sees_evidence_metadata_only(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    act_as(client, tutor.user_id, Role.teacher)
    uploaded = client.post(
        "/api/tutor/profile/evidence", files={"file": ("degree.pdf", PDF, "application/pdf")}
    )
    own = client.get("/api/tutor/profile")

    metadata = {"evidenceId", "filename", "contentType", "sizeBytes", "description", "uploadedAt"}
    assert set(uploaded.json()) == metadata
    [item] = own.json()["evidence"]
    assert set(item) == metadata
    for text in (uploaded.text, own.text):
        assert "fake://" not in text
        assert "tutor-evidence/" not in text  # never the storage path


def test_o17_a3_and_a4_send_no_url_and_log_no_access(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    admin = add_user(sm, Role.platform_admin)
    act_as(client, admin, Role.platform_admin)
    approved = add_tutor(sm, state="pending_review")
    rejected = add_tutor(sm, state="pending_review")
    seed_evidence(sm, storage, approved.profile_id)
    seed_evidence(sm, storage, rejected.profile_id)

    # documentsSeen false: true needs A2 to have issued (and logged) a link first (R3).
    a3 = client.post(
        f"/api/admin/tutors/{approved.profile_id}/approve", json={"documentsSeen": False}
    )
    a4 = client.post(f"/api/admin/tutors/{rejected.profile_id}/reject", json={"note": "Unclear."})

    for response in (a3, a4):
        assert response.status_code == 200, response.text
        assert [item["signedUrl"] for item in response.json()["evidence"]] == [None]
        assert "fake://" not in response.text
    with sm() as session:
        logged = session.execute(sa.text("SELECT count(*) FROM tutoring_admin_access")).scalar()
    assert logged == 0


# ---------------------------------------------------------------------------
# O15 (admin half)
# ---------------------------------------------------------------------------


def test_o15_admin_tutor_routes_return_no_granted_analytics(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    """No model of the ``StudentDetailDTO`` family is reachable, and no field reuses its names.

    ``subjects`` is exempt only as the tutor's taught subjects (``list[SubjectRefDTO]``,
    from ``TutorCardDTO``), the rule ``test_schemas_tutoring`` applies to the DTOs.
    """
    student_detail = set(StudentDetailDTO.model_fields)
    analytics = _reachable_models(StudentDetailDTO)
    # Non-vacuity: the comparison sets are the real DTO family.
    assert len(student_detail) >= 5
    assert len(analytics) >= 2
    admin_routes = [r for r in _routes() if r[1].startswith("/api/admin/tutors")]
    assert len(admin_routes) == 4
    for method, path, route in admin_routes:
        assert route.response_model is not None
        [model] = _models_in(route.response_model)
        reachable = _reachable_models(model)
        assert not reachable & analytics, (method, path)
        assert NoteDTO not in reachable, (method, path)
        for cls in reachable:
            for field, info in cls.model_fields.items():
                if field in student_detail:
                    assert field == "subjects", (method, path, cls.__name__, field)
                    assert info.annotation == list[SubjectRefDTO], (method, path, cls.__name__)

    admin = add_user(sm, Role.platform_admin)
    act_as(client, admin, Role.platform_admin)
    tutor = add_tutor(sm, state="pending_review")
    seed_evidence(sm, storage, tutor.profile_id)
    body = client.get(f"/api/admin/tutors/{tutor.profile_id}").json()
    assert not (_json_keys(body) & student_detail) - {"subjects"}
    assert all(set(subject) == {"code", "name"} for subject in body["subjects"])


def _reachable_models(model: type[BaseModel]) -> set[type[BaseModel]]:
    found: set[type[BaseModel]] = set()
    pending = [model]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        for field in current.model_fields.values():
            pending.extend(_models_in(field.annotation))
    return found


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _json_keys(item)
        return keys
    if isinstance(value, list):
        out: set[str] = set()
        for item in value:
            out |= _json_keys(item)
        return out
    return set()


# ---------------------------------------------------------------------------
# Role halves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [Role.platform_admin, Role.student, Role.parent, Role.school_admin]
)
def test_only_teachers_reach_the_evidence_routes(
    client: TestClient, sm: sessionmaker[Session], role: Role
) -> None:
    act_as(client, add_user(sm, role), role)
    upload = client.post(
        "/api/tutor/profile/evidence", files={"file": ("a.pdf", PDF, "application/pdf")}
    )
    delete = client.delete(f"/api/tutor/profile/evidence/{uuid.uuid4()}")
    assert (upload.status_code, delete.status_code) == (403, 403)


@pytest.mark.parametrize("role", [Role.teacher, Role.student, Role.parent, Role.school_admin])
def test_only_platform_admins_reach_the_admin_tutor_routes(
    client: TestClient, sm: sessionmaker[Session], role: Role
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    act_as(client, add_user(sm, role), role)
    responses = [
        client.get("/api/admin/tutors"),
        client.get(f"/api/admin/tutors/{tutor.profile_id}"),
        client.post(f"/api/admin/tutors/{tutor.profile_id}/approve", json={"documentsSeen": True}),
        client.post(f"/api/admin/tutors/{tutor.profile_id}/reject", json={"note": "No."}),
    ]
    assert [r.status_code for r in responses] == [403, 403, 403, 403]
    for response in responses:
        assert response.headers["cache-control"] == "private, no-store"
