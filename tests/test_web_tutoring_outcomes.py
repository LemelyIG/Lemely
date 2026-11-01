"""SP4 and T8: a tutor's outcome figures over HTTP (SPEC §b.2, §a.4b, §e.3; ADR-T04; O11).

Route-level. The app is built with ``tests.tutoring_app.app_with_routers`` (a
lane never edits ``lemely/web/app.py``) and carries SP2 as well, so SP4's 404
can be compared with the directory's own (O11: one body for every hidden tutor).

* **Byte-identical figures (F1, row 18).** Marking sessions completed or no-show,
  and a tutor's late cancel, change nothing in the ``OutcomesDTO`` that T8 and
  SP4 return. Each world is built so that a membership rule reading the outcome
  mark (``completed``) or ignoring the state would move the figure: the test
  first checks the figure is sufficient with the affected member in it.
* **T8 omits outcomes** unless the profile is listed or in review (ID-7).
* **Cross-cutting cases (PLAN global constraints a, c, f):** ``private,
  no-store`` on success, 403 ``email_unverified`` on SP4, 404
  ``no_tutor_profile`` on T8.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from lemely.db.booking_repo import Actor, BookingService
from lemely.db.models.enums import Role
from lemely.db.tutor_directory_repo import TutorDirectoryRepository
from lemely.db.tutor_outcomes_repo import TutorOutcomesRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.web.deps import get_user_mirror
from lemely.web.deps_tutoring import get_tutor_directory_repo, get_tutor_profile_repo
from lemely.web.routers import tutor_preview, tutoring_directory, tutoring_outcomes
from lemely.web.routers.tutoring_outcomes import get_tutor_outcomes_repo
from lemely.web.schemas_tutoring import OutcomesDTO
from tests.test_tutor_outcomes_repo import (
    BASE_BUCKETS,
    DAY,
    HOUR,
    SUBJECT,
    WITH_X_BUCKETS,
    add_attempt,
    add_booking_row,
    add_member,
    add_student_at,
    closed_base,
    execute,
    five_members,
    outcome_world,
    utc_now,
)
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    DbMirror,
    act_as,
    add_block,
    add_tutor,
    add_user,
    emptied_after,
    json_keys,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx import Response
    from sqlalchemy.orm import Session, sessionmaker

    from tests.tutoring_db import SeededTutor

NO_STORE = "private, no-store"
NOT_FOUND = {"detail": {"code": "not_found", "message": "Tutor not found."}}


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


def outcomes_client(sm: sessionmaker[Session]) -> TestClient:
    """SP4, T8 and SP2 on a fresh app, wired to the test database."""
    app = app_with_routers(
        tutoring_outcomes.router, tutor_preview.router, tutoring_directory.router
    )
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(sm)
    app.dependency_overrides[get_tutor_directory_repo] = lambda: TutorDirectoryRepository(sm)
    app.dependency_overrides[get_tutor_outcomes_repo] = lambda: TutorOutcomesRepository(sm)
    app.dependency_overrides[get_user_mirror] = lambda: DbMirror(sm)
    return TestClient(app)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = outcomes_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def sp4(client: TestClient, tutor_id: uuid.UUID, viewer: uuid.UUID, role: Role) -> Response:
    act_as(client, viewer, role)
    return client.get(f"/api/tutors/{tutor_id}/outcomes")


def t8(client: TestClient, tutor: SeededTutor) -> Response:
    act_as(client, tutor.user_id, Role.teacher)
    return client.get("/api/tutor/profile/preview")


def physics(body: dict[str, object]) -> dict[str, object]:
    subjects = body["subjects"]
    assert isinstance(subjects, list)
    [found] = [item for item in subjects if item["subject"]["code"] == SUBJECT]
    assert isinstance(found, dict)
    return found


def bucket_counts(subject: dict[str, object]) -> dict[str, int]:
    distribution = subject["distribution"]
    assert isinstance(distribution, dict)
    return {bucket["grade"]: bucket["count"] for bucket in distribution["buckets"]}


def read_both(client: TestClient, tutor: SeededTutor, viewer: uuid.UUID) -> bytes:
    """SP4's body as bytes, after checking T8 carries the same ``OutcomesDTO``."""
    student_view = sp4(client, tutor.profile_id, viewer, Role.student)
    assert student_view.status_code == 200, student_view.text
    tutor_view = t8(client, tutor)
    assert tutor_view.status_code == 200, tutor_view.text
    assert tutor_view.json()["outcomes"] == student_view.json()
    # The T8 copy, serialised the way SP4 serialises it, is byte-identical too.
    assert (
        json.dumps(tutor_view.json()["outcomes"], separators=(",", ":")).encode()
        == student_view.content
    )
    return student_view.content


# ---------------------------------------------------------------------------
# Byte-identical figures around the tutor's actions (F1, SPEC §e.4)
# ---------------------------------------------------------------------------


def test_outcomes_marking_complete_no_show_changes_nothing(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    tutor = outcome_world(sm)
    # Four base members marked completed; the fifth still awaiting its outcome.
    members = five_members(sm, tutor, states=("completed",) * 4 + ("accepted",))
    # X closes first and is also awaiting an outcome: the published five are X and the
    # first four base members (floor(6 / 5) * 5).
    x = add_member(sm, tutor, start=closed_base() - DAY, before="A*", during="A*", state="accepted")
    viewer = add_user(sm, Role.student)
    before = read_both(client, tutor, viewer)
    assert bucket_counts(physics(json.loads(before))) == WITH_X_BUCKETS  # sufficient, X in it

    service = BookingService(sm)
    tutor_actor = Actor(user_id=tutor.user_id, party="tutor")
    service.transition(booking_id=members[-1].booking, actor=tutor_actor, action="complete")
    assert read_both(client, tutor, viewer) == before
    service.transition(booking_id=x.booking, actor=tutor_actor, action="no_show")
    assert read_both(client, tutor, viewer) == before


def test_late_cancel_leaves_outcomes_unchanged(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """A cancelled booking never enters the cohort, even once its slot is in the past (row 18)."""
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    # Y: eligible, with grades around the instant the cancelled session will be moved to.
    earliest = closed_base() - 2 * DAY
    y = add_student_at(sm, created_at=earliest - 400 * DAY, verified_at=earliest - DAY)
    add_attempt(sm, y, grade="A*", recorded_at=earliest - 30 * DAY)
    add_attempt(sm, y, grade="A*", recorded_at=earliest + 30 * DAY)
    soon = utc_now() + 10 * HOUR  # inside 24 hours: only the tutor may cancel, with a reason
    booking = add_booking_row(sm, tutor, y, starts_at=soon, state="accepted")
    viewer = add_user(sm, Role.student)
    before = read_both(client, tutor, viewer)
    assert bucket_counts(physics(json.loads(before))) == BASE_BUCKETS

    row = BookingService(sm).transition(
        booking_id=booking,
        actor=Actor(user_id=tutor.user_id, party="tutor"),
        action="cancel",
        reason="I am unwell and cannot run the session.",
    )
    assert row.state == "cancelled"
    assert read_both(client, tutor, viewer) == before
    # Time passes: the cancelled slot is now 152 days back and would close first if counted.
    execute(
        sm,
        "UPDATE tutor_bookings SET starts_at = :s, ends_at = :e WHERE id = :b",
        s=earliest,
        e=earliest + HOUR,
        b=booking,
    )
    assert read_both(client, tutor, viewer) == before


# ---------------------------------------------------------------------------
# SP4: visibility (O11), verified email, headers, shape
# ---------------------------------------------------------------------------


def test_sp4_404_for_unlisted_paused_or_blocked_tutor(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """One body for every hidden tutor, and it is SP2's (O11, PP-6)."""
    tutor_kwargs: dict[str, dict[str, object]] = {
        "draft": {"state": "draft"},
        "pending_review": {"state": "pending_review"},
        "rejected": {"state": "rejected"},
        "suspended": {"state": "suspended"},
        "closed": {"state": "closed"},
        "paused": {"paused": True},
    }
    student = add_user(sm, Role.student)
    visible = add_tutor(sm)
    assert sp4(client, visible.profile_id, student, Role.student).status_code == 200
    assert client.get(f"/api/tutors/{visible.profile_id}").status_code == 200

    hidden: dict[str, uuid.UUID] = {
        name: add_tutor(sm, **kwargs).profile_id  # type: ignore[arg-type]
        for name, kwargs in tutor_kwargs.items()
    }
    hidden["unknown"] = uuid.uuid4()
    blocked_by_student = add_tutor(sm)
    add_block(sm, student, blocked_by_student.user_id)
    hidden["student_blocked_tutor"] = blocked_by_student.profile_id
    blocked_by_tutor = add_tutor(sm)
    add_block(sm, blocked_by_tutor.user_id, student)
    hidden["tutor_blocked_student"] = blocked_by_tutor.profile_id

    for name, tutor_id in hidden.items():
        outcomes = sp4(client, tutor_id, student, Role.student)
        profile = client.get(f"/api/tutors/{tutor_id}")
        assert outcomes.status_code == 404, name
        assert outcomes.json() == NOT_FOUND, name
        assert outcomes.content == profile.content, name
        assert outcomes.headers["cache-control"] == NO_STORE, name
    assert len(hidden) == 9

    # A removed block hides nothing.
    removed = add_tutor(sm)
    add_block(sm, student, removed.user_id, removed=True)
    assert sp4(client, removed.profile_id, student, Role.student).status_code == 200


def test_sp4_for_parent_and_student_with_no_store_and_dto_keys(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    student = add_user(sm, Role.student)
    parent = add_user(sm, Role.parent)
    as_student = sp4(client, tutor.profile_id, student, Role.student)
    as_parent = sp4(client, tutor.profile_id, parent, Role.parent)
    for response in (as_student, as_parent):
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == NO_STORE
    assert as_student.content == as_parent.content
    body = as_student.json()
    assert body["tutorId"] == str(tutor.profile_id)
    assert body["ladder"] == ["A*", "A", "B", "C", "D", "E", "U"]
    assert (body["duringWindowDays"], body["beforeLookbackDays"]) == (120, 180)
    assert bucket_counts(physics(body)) == BASE_BUCKETS
    # Every key in the response belongs to OutcomesDTO or a DTO it nests, and every such
    # key is present (both figures are sufficient here, so nothing is null by state).
    assert json_keys(body) == _dto_keys(OutcomesDTO)


def _dto_keys(model: type[BaseModel]) -> set[str]:
    keys: set[str] = set()
    for name, field in model.model_fields.items():
        keys.add(name)
        for nested in _models_in(field.annotation):
            keys |= _dto_keys(nested)
    return keys


def _models_in(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for arg in getattr(annotation, "__args__", ()):
        found.extend(_models_in(arg))
    return found


def test_sp4_refuses_unverified_email(sm: sessionmaker[Session], client: TestClient) -> None:
    tutor = add_tutor(sm)
    unverified = add_user(sm, Role.student, verified=False)
    response = sp4(client, tutor.profile_id, unverified, Role.student)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "email_unverified"
    assert response.headers["cache-control"] == NO_STORE
    # Red case: the same caller once verified gets the figures.
    execute(sm, "UPDATE users SET email_verified_at = now() WHERE id = :u", u=unverified)
    assert sp4(client, tutor.profile_id, unverified, Role.student).status_code == 200


# ---------------------------------------------------------------------------
# T8: the tutor's preview
# ---------------------------------------------------------------------------


def test_t8_404_no_tutor_profile(sm: sessionmaker[Session], client: TestClient) -> None:
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)
    response = client.get("/api/tutor/profile/preview")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_tutor_profile"
    assert response.headers["cache-control"] == NO_STORE


def test_idor_t8_preview_omits_outcomes_when_suspended_or_rejected(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """``outcomes`` only while listed (paused or not) or in review (ID-7, SPEC §a.4b)."""
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    listed = t8(client, tutor)
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == NO_STORE
    shown = listed.json()["outcomes"]
    assert bucket_counts(physics(shown)) == BASE_BUCKETS
    # The profile half is S-34 as students see it: SP2's body for the same tutor.
    student = add_user(sm, Role.student)
    act_as(client, student, Role.student)
    assert listed.json()["profile"] == client.get(f"/api/tutors/{tutor.profile_id}").json()

    def set_state(state: str, *, paused: bool = False) -> None:
        execute(
            sm,
            "UPDATE tutor_profiles SET listing_state = CAST(:s AS tutorlistingstate), "
            "closed_at = CASE WHEN :s = 'closed' THEN now() END, "
            "paused_at = CASE WHEN :p THEN now() END WHERE id = :t",
            s=state,
            p=paused,
            t=tutor.profile_id,
        )

    seen: dict[str, object] = {}
    for state, paused in (
        ("listed", True),
        ("pending_review", False),
        ("draft", False),
        ("rejected", False),
        ("suspended", False),
        ("closed", False),
    ):
        set_state(state, paused=paused)
        response = t8(client, tutor)
        assert response.status_code == 200, (state, response.text)
        assert response.json()["profile"]["tutorId"] == str(tutor.profile_id)
        seen[f"{state}{'_paused' if paused else ''}"] = response.json()["outcomes"]
    assert seen == {
        "listed_paused": shown,
        "pending_review": shown,
        "draft": None,
        "rejected": None,
        "suspended": None,
        "closed": None,
    }


def test_t8_without_a_cohort_shows_every_subject_insufficient(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    tutor = outcome_world(sm)
    response = t8(client, tutor)
    assert response.status_code == 200, response.text
    outcomes = response.json()["outcomes"]
    assert [item["subject"]["code"] for item in outcomes["subjects"]] == ["0620", SUBJECT]
    for item in outcomes["subjects"]:
        assert item["distribution"] == {
            "state": "insufficient",
            "k": 5,
            "nGraded": None,
            "nWithoutGrade": None,
            "buckets": [],
        }
        assert item["change"] == {
            "state": "insufficient",
            "k": 5,
            "nPaired": None,
            "higher": None,
            "same": None,
            "lower": None,
        }
