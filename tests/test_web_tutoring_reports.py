"""R1 ``POST /api/tutoring/reports`` at the route (PLAN T25; SPEC §b.2, §b.4, SC-10, SC-15).

What the route adds to the repository (``tests/test_tutoring_reports_repo.py``): the guard
(``TUTORING_PARTY``: student, parent, teacher; no verified-email gate), the codes (201 with a
receipt and nothing else, 404 with one body for every target the caller may not see, 409
``report_exists``, 422, 429 after 20 a day), ``private, no-store`` on every status, and the
after-commit inbox notice to every platform admin for a ``safety_concern`` (D5.9 §1: a failed
notice never fails the report), including one that upgrades the caller's open report (F7-25
#1). Object-level visibility (O12, O19) is ``tests/test_web_tutoring_authz_reports.py``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import structlog.testing

from lemely.db.models.enums import Role
from tests.test_booking_repo import add_booking, add_student, make_world
from tests.test_tutoring_reports_repo import (
    REPORT_QUOTA,
    frozen,
    report_count,
    reports_client,
)
from tests.test_web_tutoring_blocks import _RaisingInbox, inbox
from tests.tutoring_db import act_as, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

R1 = "/api/tutoring/reports"
NO_STORE = "private, no-store"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = reports_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def body_for(
    target_type: str, target_id: uuid.UUID | str, reason: str = "harassment"
) -> dict[str, str]:
    return {"targetType": target_type, "targetId": str(target_id), "reason": reason}


def test_r1_files_a_report_and_answers_with_a_receipt_only(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)

    response = client.post(R1, json={**body_for("booking", booking), "details": "Rude."})

    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == NO_STORE
    receipt = response.json()
    assert set(receipt) == {"reportId", "createdAt"}
    uuid.UUID(receipt["reportId"])
    assert receipt["createdAt"].endswith("+00:00")
    assert report_count(sm) == 1


def test_report_quota_429_after_20(sm: sessionmaker[Session], client: TestClient) -> None:
    """SC-15: at most 20 reports per reporter per 24 hours; the 21st is 429 and writes nothing."""
    w = make_world(sm)
    act_as(client, w.student, Role.student)
    for number in range(REPORT_QUOTA):
        booking = add_booking(sm, w, state="cancelled")
        response = client.post(R1, json=body_for("booking", booking))
        assert response.status_code == 201, (number, response.text)

    over = client.post(R1, json=body_for("booking", add_booking(sm, w, state="cancelled")))

    assert over.status_code == 429, over.text
    assert over.json()["detail"]["code"] == "too_many_requests"
    assert over.headers["Cache-Control"] == NO_STORE
    assert report_count(sm) == REPORT_QUOTA == 20
    # Another reporter has a quota of their own.
    act_as(client, w.tutor.user_id, Role.teacher)
    assert client.post(R1, json=body_for("booking", add_booking(sm, w))).status_code == 201


def test_r1_second_open_report_on_the_same_target_is_409(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)
    assert client.post(R1, json=body_for("booking", booking)).status_code == 201

    again = client.post(R1, json=body_for("booking", booking, "spam"))

    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "report_exists"
    assert again.headers["Cache-Control"] == NO_STORE
    assert report_count(sm) == 1


def test_r1_safety_re_report_upgrades_the_open_report_and_tells_the_admins(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """F7-25 #1 at the route: a safety concern on a target the caller already reported for
    another reason is 201 with the same receipt (the open report, now a safety concern), the
    notes are frozen and every platform admin is told once. A safety concern on top of that is
    409 ``report_exists`` and tells nobody again."""
    w = make_world(sm)
    admins = [add_user(sm, Role.platform_admin) for _ in range(2)]
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)
    first = client.post(R1, json={**body_for("booking", booking), "details": "Rude."})
    assert first.status_code == 201, first.text
    assert all(inbox(sm, admin) == [] for admin in admins)

    upgraded = client.post(
        R1, json={**body_for("booking", booking, "safety_concern"), "details": "He asked to meet"}
    )

    assert upgraded.status_code == 201, upgraded.text
    assert upgraded.headers["Cache-Control"] == NO_STORE
    assert upgraded.json() == first.json()
    assert report_count(sm) == 1
    assert frozen(sm, booking)
    report_id = first.json()["reportId"]
    notice = (
        "tutoring_report",
        "New safety report",
        "A safety concern was reported. Open the reports queue.",
        f"report:{report_id}",
    )
    for admin in admins:
        assert inbox(sm, admin) == [notice]

    again = client.post(R1, json=body_for("booking", booking, "safety_concern"))
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "report_exists"
    for admin in admins:
        assert inbox(sm, admin) == [notice]


def test_r1_unknown_and_hidden_targets_share_one_404(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """No existence oracle: an unknown id and another student's booking read the same."""
    w = make_world(sm)
    others = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    stranger = add_student(sm)
    act_as(client, stranger, Role.student)

    hidden = client.post(R1, json=body_for("booking", others))
    unknown = client.post(R1, json=body_for("booking", uuid.uuid4()))
    unknown_note = client.post(R1, json=body_for("booking_note", uuid.uuid4()))

    assert hidden.status_code == unknown.status_code == unknown_note.status_code == 404
    assert hidden.json() == unknown.json() == unknown_note.json()
    assert hidden.headers["Cache-Control"] == NO_STORE
    assert report_count(sm) == 0


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"targetId": "not-a-uuid"}, "invalid_target"),
        ({"details": "x" * 1001}, "text_too_long"),
    ],
)
def test_r1_validation_422(
    sm: sessionmaker[Session], client: TestClient, patch: dict[str, str], code: str
) -> None:
    w = make_world(sm)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)

    response = client.post(R1, json={**body_for("booking", booking), **patch})

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code
    assert response.headers["Cache-Control"] == NO_STORE
    assert report_count(sm) == 0


def test_r1_unknown_target_type_or_reason_is_422(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    act_as(client, w.student, Role.student)
    for payload in (
        body_for("class", w.tutor.profile_id),
        body_for("tutor_profile", w.tutor.profile_id, "boring"),
    ):
        response = client.post(R1, json=payload)
        assert response.status_code == 422, payload
        assert response.headers["Cache-Control"] == NO_STORE


def test_r1_safety_concern_notifies_every_platform_admin_after_commit(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    admins = [add_user(sm, Role.platform_admin) for _ in range(2)]
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)

    spam = client.post(R1, json=body_for("tutor_profile", w.tutor.profile_id, "spam"))
    safety = client.post(
        R1, json={**body_for("booking", booking, "safety_concern"), "details": "He asked to meet"}
    )

    assert spam.status_code == safety.status_code == 201
    report_id = safety.json()["reportId"]
    for admin in admins:
        assert inbox(sm, admin) == [
            (
                "tutoring_report",
                "New safety report",
                "A safety concern was reported. Open the reports queue.",
                f"report:{report_id}",
            )
        ]
    # Fixed copy only: neither the details nor any name reaches a notice.
    assert inbox(sm, w.student) == []
    assert inbox(sm, w.tutor.user_id) == []
    assert frozen(sm, booking)


def test_r1_commits_when_the_inbox_write_raises(sm: sessionmaker[Session]) -> None:
    """D5.9 §1: the report and its freeze commit; the failed notice is only logged."""
    w = make_world(sm)
    add_user(sm, Role.platform_admin)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    client = reports_client(sm, notifications=_RaisingInbox())
    act_as(client, w.student, Role.student)

    with structlog.testing.capture_logs() as logs:
        response = client.post(R1, json=body_for("booking", booking, "safety_concern"))

    assert response.status_code == 201, response.text
    assert report_count(sm) == 1
    assert frozen(sm, booking)
    assert [entry for entry in logs if entry["event"] == "notification_create_failed"]


@pytest.mark.parametrize("role", [Role.school_admin, Role.platform_admin])
def test_r1_refuses_roles_outside_tutoring_party(
    sm: sessionmaker[Session], client: TestClient, role: Role
) -> None:
    w = make_world(sm)
    act_as(client, add_user(sm, role), role)
    response = client.post(R1, json=body_for("tutor_profile", w.tutor.profile_id))
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == NO_STORE
    assert report_count(sm) == 0
