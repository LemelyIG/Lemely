"""Review routes SP3, S6, S7, T18, T21 and moderation A6-A8 (SPEC §b.2, §a.3, SC-7, SC-12).

Cross-cutting obligations of PLAN "Global constraints" for these eight routes:
(a) ``no-store`` on each success path, (b) SC-7 for every free-text field (review
text on S6 and S7, reply body on T18), (c) ``email_unverified`` on the **V**
routes (SP3, S6, S7), (d) ``tutor_suspended``/``tutor_closed`` on the one tutor
write route (T18), (f) ``no_tutor_profile`` 404 on T18 and T21. The object-level
rules (O10, O11, O27, IDOR) are in ``test_web_tutoring_authz_reviews.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.enums import NotificationType, Role
from lemely.db.models.ops import Notification
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.db.tutor_review_repo import TutorReviewRepository
from lemely.web.deps import get_notification_service, get_push_transport, get_user_mirror
from lemely.web.deps_tutoring import get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import (
    admin_tutoring_moderation,
    student_reviews,
    tutor_reviews,
    tutoring_reviews,
)
from lemely.web.routers.tutoring_reviews import get_tutor_review_repo
from tests.test_tutor_review_repo import (
    add_booking,
    add_reply_row,
    add_review_row,
    add_student,
    review_row,
    set_review_created,
)
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    DbMirror,
    SeededTutor,
    act_as,
    add_subject,
    add_tutor,
    add_user,
    anonymous,
    emptied_after,
    json_keys,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
EN_DASH = chr(0x2013)  # SPEC §b.3 prints the quarter with an en dash
QUARTER_Q3_2026 = f"Jul{EN_DASH}Sep 2026"
QUARTER_Q1_2026 = f"Jan{EN_DASH}Mar 2026"
QUARTER_Q4_2026 = f"Oct{EN_DASH}Dec 2026"


def review_client(factory: sessionmaker[Session]) -> TestClient:
    """The four T12 routers on a fresh app, wired to the test database."""
    app = app_with_routers(
        tutoring_reviews.router,
        student_reviews.router,
        tutor_reviews.router,
        admin_tutoring_moderation.router,
    )
    app.dependency_overrides[get_tutor_review_repo] = lambda: TutorReviewRepository(factory)
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(factory)
    app.dependency_overrides[get_user_mirror] = lambda: DbMirror(factory)
    service = NotificationService(factory, NotificationPreferencesService(factory))
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[get_push_transport] = lambda: RecordingPushTransport()
    return TestClient(app)


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = review_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


class Setup:
    """A listed tutor, a subject, an old verified student and a spare viewer."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self.sm = sm
        self.subject = add_subject(sm)
        self.tutor: SeededTutor = add_tutor(sm, subjects=(self.subject,))
        self.student = add_student(sm)
        self.viewer = add_user(sm, Role.student)
        self.admin = add_user(sm, Role.platform_admin)

    def booking(self, student: uuid.UUID | None = None, **kwargs: object) -> uuid.UUID:
        return add_booking(
            self.sm,
            student=student or self.student,
            tutor=self.tutor,
            subject=self.subject,
            **kwargs,  # type: ignore[arg-type]
        )

    def seeded_review(self, **kwargs: object) -> uuid.UUID:
        student = add_student(self.sm)
        return add_review_row(
            self.sm,
            booking=self.booking(student),
            tutor_id=self.tutor.profile_id,
            student=student,
            **kwargs,  # type: ignore[arg-type]
        )


@pytest.fixture
def s(sm: sessionmaker[Session]) -> Setup:
    return Setup(sm)


def notifications(sm: sessionmaker[Session], user_id: uuid.UUID) -> list[Notification]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.type == NotificationType.tutor_review,
                )
                .order_by(Notification.created_at, Notification.id)
            )
        )


# ---------------------------------------------------------------------------
# The life of a review text: pending, approved, edited, rejected
# ---------------------------------------------------------------------------


def test_review_text_public_only_after_approval(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    booking = s.booking()
    act_as(client, s.student, Role.student)
    created = client.post(
        f"/api/student/bookings/{booking}/review",
        json={"stars": 4, "text": "Very patient teacher."},
    )
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == NO_STORE
    mine = created.json()
    assert (mine["stars"], mine["text"], mine["textState"]) == (
        4,
        "Very patient teacher.",
        "pending",
    )
    assert mine["bookingId"] == str(booking)
    review_id = mine["reviewId"]
    stored = review_row(sm, uuid.UUID(review_id))
    assert datetime.fromisoformat(mine["editableUntil"]) == stored.created_at + timedelta(hours=336)

    act_as(client, s.viewer, Role.student)
    public = client.get(f"/api/tutors/{s.tutor.profile_id}/reviews")
    assert public.status_code == 200
    assert public.headers["cache-control"] == NO_STORE
    assert [(i["stars"], i["text"]) for i in public.json()["items"]] == [(4, None)]

    act_as(client, s.tutor.user_id, Role.teacher)
    own = client.get("/api/tutor/reviews")
    assert own.status_code == 200
    assert own.headers["cache-control"] == NO_STORE
    assert [(i["text"], i["textState"]) for i in own.json()["items"]] == [(None, "pending")]

    act_as(client, s.admin, Role.platform_admin)
    queue = client.get("/api/admin/tutoring/moderation")
    assert queue.status_code == 200
    assert [(i["kind"], i["itemId"], i["text"]) for i in queue.json()["items"]] == [
        ("review", review_id, "Very patient teacher.")
    ]
    approved = client.post(
        f"/api/admin/tutoring/reviews/{review_id}/moderate", json={"decision": "approved"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.headers["cache-control"] == NO_STORE
    assert (approved.json()["textState"], approved.json()["text"], approved.json()["stars"]) == (
        "approved",
        "Very patient teacher.",
        4,
    )

    act_as(client, s.viewer, Role.student)
    assert [
        i["text"] for i in client.get(f"/api/tutors/{s.tutor.profile_id}/reviews").json()["items"]
    ] == ["Very patient teacher."]
    act_as(client, s.tutor.user_id, Role.teacher)
    assert [
        (i["text"], i["textState"]) for i in client.get("/api/tutor/reviews").json()["items"]
    ] == [("Very patient teacher.", "approved")]

    # An edit pulls the text back down until it is checked again.
    act_as(client, s.student, Role.student)
    edited = client.patch(f"/api/student/reviews/{review_id}", json={"text": "Even better now."})
    assert edited.status_code == 200, edited.text
    assert (edited.json()["text"], edited.json()["textState"]) == ("Even better now.", "pending")
    act_as(client, s.viewer, Role.student)
    assert (
        client.get(f"/api/tutors/{s.tutor.profile_id}/reviews").json()["items"][0]["text"] is None
    )

    act_as(client, s.admin, Role.platform_admin)
    rejected = client.post(
        f"/api/admin/tutoring/reviews/{review_id}/moderate", json={"decision": "rejected"}
    )
    assert rejected.json()["textState"] == "rejected"
    act_as(client, s.viewer, Role.student)
    assert (
        client.get(f"/api/tutors/{s.tutor.profile_id}/reviews").json()["items"][0]["text"] is None
    )


def test_moderation_notifies_the_author_with_a_growing_revision(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    act_as(client, s.student, Role.student)
    review_id = client.post(
        f"/api/student/bookings/{s.booking()}/review", json={"stars": 5, "text": "First words."}
    ).json()["reviewId"]
    act_as(client, s.admin, Role.platform_admin)
    url = f"/api/admin/tutoring/reviews/{review_id}/moderate"
    assert client.post(url, json={"decision": "approved"}).status_code == 200
    assert client.post(url, json={"decision": "approved"}).status_code == 200  # idempotent repeat
    first = notifications(sm, s.student)
    assert [n.dedupe_key for n in first] == [f"review:{review_id}:approved:0"]
    assert first[0].payload == {"reviewId": review_id}

    act_as(client, s.student, Role.student)
    client.patch(f"/api/student/reviews/{review_id}", json={"text": "Second words."})
    act_as(client, s.admin, Role.platform_admin)
    assert client.post(url, json={"decision": "approved"}).status_code == 200
    assert [n.dedupe_key for n in notifications(sm, s.student)] == [
        f"review:{review_id}:approved:0",
        f"review:{review_id}:approved:1",
    ]
    assert notifications(sm, s.tutor.user_id) == []  # no "new review" notice to the tutor (SC-12)


def test_reply_moderated_before_public(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    review_id = s.seeded_review(stars=5)
    act_as(client, s.tutor.user_id, Role.teacher)
    created = client.post(
        f"/api/tutor/reviews/{review_id}/reply", json={"body": "  Thank you for the kind words.  "}
    )
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == NO_STORE
    reply = created.json()
    assert (reply["body"], reply["textState"]) == ("Thank you for the kind words.", "pending")
    assert datetime.fromisoformat(reply["createdAt"]).tzinfo is not None

    act_as(client, s.viewer, Role.student)
    assert (
        client.get(f"/api/tutors/{s.tutor.profile_id}/reviews").json()["items"][0]["reply"] is None
    )
    act_as(client, s.tutor.user_id, Role.teacher)
    own_reply = client.get("/api/tutor/reviews").json()["items"][0]["reply"]
    assert (own_reply["replyId"], own_reply["textState"]) == (reply["replyId"], "pending")

    act_as(client, s.admin, Role.platform_admin)
    queue = client.get("/api/admin/tutoring/moderation", params={"kind": "reply"}).json()
    assert [(i["kind"], i["itemId"], i["text"]) for i in queue["items"]] == [
        ("reply", reply["replyId"], "Thank you for the kind words.")
    ]
    approved = client.post(
        f"/api/admin/tutoring/replies/{reply['replyId']}/moderate", json={"decision": "approved"}
    )
    assert approved.status_code == 200, approved.text
    assert (approved.json()["replyId"], approved.json()["textState"]) == (
        reply["replyId"],
        "approved",
    )

    act_as(client, s.viewer, Role.student)
    shown = client.get(f"/api/tutors/{s.tutor.profile_id}/reviews").json()["items"][0]["reply"]
    assert (shown["body"], shown["textState"]) == ("Thank you for the kind words.", "approved")

    notice = notifications(sm, s.tutor.user_id)
    assert [n.dedupe_key for n in notice] == [f"reply:{reply['replyId']}:approved:0"]
    assert notice[0].payload == {"replyId": reply["replyId"]}
    assert str(review_id) not in str(
        notice[0].payload
    )  # SC-12: nothing that identifies the reviewer

    act_as(client, s.tutor.user_id, Role.teacher)
    again = client.post(f"/api/tutor/reviews/{review_id}/reply", json={"body": "A second reply"})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "reply_exists"


def test_t21_own_reply_any_state_text_only_when_approved(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    rows = {
        "none": s.seeded_review(stars=1),
        "pending": s.seeded_review(stars=2, text="pending text", text_state="pending"),
        "approved": s.seeded_review(stars=3, text="approved text", text_state="approved"),
        "rejected": s.seeded_review(stars=4, text="rejected text", text_state="rejected"),
    }
    for review, state in ((rows["none"], "pending"), (rows["pending"], "rejected")):
        add_reply_row(
            sm, review=review, tutor_id=s.tutor.profile_id, body=f"{state} reply", state=state
        )
    act_as(client, s.tutor.user_id, Role.teacher)
    page = client.get("/api/tutor/reviews")
    assert page.status_code == 200
    by_stars = {item["stars"]: item for item in page.json()["items"]}
    assert len(by_stars) == 4
    assert {stars: (item["text"], item["textState"]) for stars, item in by_stars.items()} == {
        1: (None, "none"),
        2: (None, "pending"),
        3: ("approved text", "approved"),
        4: (None, "rejected"),
    }
    assert (by_stars[1]["reply"]["body"], by_stars[1]["reply"]["textState"]) == (
        "pending reply",
        "pending",
    )
    assert (by_stars[2]["reply"]["body"], by_stars[2]["reply"]["textState"]) == (
        "rejected reply",
        "rejected",
    )
    assert by_stars[3]["reply"] is None


def test_reviews_show_quarter_and_a_student(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    q3 = s.seeded_review(stars=5, created_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC))
    q1 = s.seeded_review(stars=3, created_at=datetime(2026, 1, 10, 10, 0, tzinfo=UTC))
    # 30 September 22:30 UTC is already 1 October in Cairo (UTC+3 in summer): the zone decides.
    edge = s.seeded_review(stars=4, created_at=datetime(2026, 9, 30, 22, 30, tzinfo=UTC))
    act_as(client, s.viewer, Role.student)
    page = client.get(f"/api/tutors/{s.tutor.profile_id}/reviews").json()
    periods = {item["reviewId"]: item["period"] for item in page["items"]}
    assert periods == {
        str(q3): QUARTER_Q3_2026,
        str(q1): QUARTER_Q1_2026,
        str(edge): QUARTER_Q4_2026,
    }
    act_as(client, s.tutor.user_id, Role.teacher)
    own = client.get("/api/tutor/reviews").json()
    assert {i["reviewId"]: i["period"] for i in own["items"]} == periods

    allowed = {
        "items", "nextCursor", "reviewId", "stars", "text", "period", "reply", "textState",
        "replyId", "body", "createdAt",
    }  # fmt: skip
    for body in (page, own):
        keys = json_keys(body)
        assert keys <= allowed, keys - allowed
        assert {"reviewId", "stars", "period"} <= keys  # non-vacuity: the pages carry real items
    raw = client.get("/api/tutor/reviews").text
    with sm() as session:
        identifiers = [
            str(value)
            for row in session.execute(sa.text("SELECT student_id, booking_id FROM tutor_reviews"))
            for value in row
        ]
    assert len(identifiers) == 6
    assert not any(identifier in raw for identifier in identifiers)


# ---------------------------------------------------------------------------
# S6, S7 refusals
# ---------------------------------------------------------------------------


def test_s6_refusal_codes(client: TestClient, sm: sessionmaker[Session], s: Setup) -> None:
    act_as(client, s.student, Role.student)

    def post(booking: uuid.UUID | str, **body: object) -> tuple[int, str | None]:
        response = client.post(f"/api/student/bookings/{booking}/review", json={"stars": 5, **body})
        assert response.headers["cache-control"] == NO_STORE
        detail = response.json().get("detail")
        return response.status_code, detail.get("code") if isinstance(detail, dict) else None

    assert post(uuid.uuid4()) == (404, "not_found")
    assert post(s.booking(state="accepted", ended_ago=timedelta(days=30))) == (409, "not_completed")
    assert post(s.booking(ended_ago=timedelta(days=6))) == (409, "review_not_open_yet")
    other = add_student(sm)
    assert post(s.booking(other)) == (404, "not_found")  # someone else's booking
    ok = s.booking(ended_ago=timedelta(days=10))
    assert post(ok)[0] == 201
    assert post(ok) == (409, "review_exists")

    newcomer = add_student(sm, age=timedelta(days=3))
    act_as(client, newcomer, Role.student)
    assert post(s.booking(newcomer)) == (409, "account_too_new")


def test_account_too_new_409_over_http(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    newcomer = add_student(sm, age=timedelta(days=13, hours=23))
    booking = s.booking(newcomer)
    act_as(client, newcomer, Role.student)
    response = client.post(f"/api/student/bookings/{booking}/review", json={"stars": 5})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_too_new"


@pytest.mark.parametrize("stars", [0, 6, -3])
def test_s6_stars_out_of_range_is_422(client: TestClient, s: Setup, stars: int) -> None:
    act_as(client, s.student, Role.student)
    response = client.post(f"/api/student/bookings/{s.booking()}/review", json={"stars": stars})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_stars"
    assert response.headers["cache-control"] == NO_STORE


def test_s6_malformed_bodies_are_422(client: TestClient, s: Setup) -> None:
    act_as(client, s.student, Role.student)
    url = f"/api/student/bookings/{s.booking()}/review"
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"stars": "five"}).status_code == 422
    assert client.post(url, json={"stars": 5, "surprise": 1}).status_code == 422
    assert (
        client.post("/api/student/bookings/not-a-uuid/review", json={"stars": 5}).status_code == 422
    )


def test_s7_refusals(client: TestClient, sm: sessionmaker[Session], s: Setup) -> None:
    act_as(client, s.student, Role.student)
    review_id = client.post(
        f"/api/student/bookings/{s.booking()}/review", json={"stars": 4, "text": "Good."}
    ).json()["reviewId"]
    url = f"/api/student/reviews/{review_id}"

    assert client.patch(url, json={}).json()["detail"]["code"] == "empty_update"
    assert client.patch(url, json={"stars": 7}).json()["detail"]["code"] == "invalid_stars"
    conflict = client.patch(url, json={"text": "x", "clearText": True})
    assert (conflict.status_code, conflict.json()["detail"]["code"]) == (422, "text_conflict")
    assert (
        client.patch(f"/api/student/reviews/{uuid.uuid4()}", json={"stars": 1}).status_code == 404
    )

    cleared = client.patch(url, json={"clearText": True})
    assert (cleared.status_code, cleared.json()["text"], cleared.json()["textState"]) == (
        200,
        None,
        "none",
    )
    assert cleared.headers["cache-control"] == NO_STORE

    set_review_created(sm, uuid.UUID(review_id), timedelta(days=14, minutes=5))
    closed = client.patch(url, json={"stars": 1})
    assert (closed.status_code, closed.json()["detail"]["code"]) == (409, "edit_window_closed")
    assert closed.headers["cache-control"] == NO_STORE
    assert review_row(sm, uuid.UUID(review_id)).stars == 4


# ---------------------------------------------------------------------------
# (b) SC-7 on every free-text field
# ---------------------------------------------------------------------------

CONTACT_TEXT = "ring me on 0100 123 4567"


def test_sc7_contact_details_refused_on_review_text_edit_and_reply(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    act_as(client, s.student, Role.student)
    booking = s.booking()
    refused = client.post(
        f"/api/student/bookings/{booking}/review", json={"stars": 5, "text": CONTACT_TEXT}
    )
    assert (refused.status_code, refused.json()["detail"]["code"]) == (
        422,
        "contact_details_not_allowed",
    )
    assert refused.headers["cache-control"] == NO_STORE
    review_id = client.post(
        f"/api/student/bookings/{booking}/review", json={"stars": 5, "text": "Fine."}
    ).json()["reviewId"]
    edit = client.patch(f"/api/student/reviews/{review_id}", json={"text": CONTACT_TEXT})
    assert (edit.status_code, edit.json()["detail"]["code"]) == (422, "contact_details_not_allowed")
    assert review_row(sm, uuid.UUID(review_id)).body == "Fine."

    act_as(client, s.tutor.user_id, Role.teacher)
    reply = client.post(f"/api/tutor/reviews/{review_id}/reply", json={"body": "email me: a@b.co"})
    assert (reply.status_code, reply.json()["detail"]["code"]) == (
        422,
        "contact_details_not_allowed",
    )
    assert reply.headers["cache-control"] == NO_STORE
    with sm() as session:
        assert (
            session.execute(sa.text("SELECT count(*) FROM tutor_review_replies")).scalar_one() == 0
        )


# ---------------------------------------------------------------------------
# (c) email_unverified on the V routes
# ---------------------------------------------------------------------------


def test_v_routes_require_a_verified_email(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    unverified = add_student(sm, verified=False)
    own_review = add_review_row(
        sm,
        booking=s.booking(unverified),
        tutor_id=s.tutor.profile_id,
        student=unverified,
        stars=4,
    )
    act_as(client, unverified, Role.student)
    calls = [
        client.get(f"/api/tutors/{s.tutor.profile_id}/reviews"),
        client.post(f"/api/student/bookings/{s.booking(unverified)}/review", json={"stars": 5}),
        client.patch(f"/api/student/reviews/{own_review}", json={"stars": 1}),
    ]
    for response in calls:
        assert response.status_code == 403
        assert response.json()["detail"] == {"code": "email_unverified"}
        assert response.headers["cache-control"] == NO_STORE
    assert review_row(sm, own_review).stars == 4


# ---------------------------------------------------------------------------
# (d) T18 on a suspended or closed profile, (f) no profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
def test_t18_refused_for_suspended_or_closed_tutor_but_t21_still_reads(
    client: TestClient, sm: sessionmaker[Session], state: str, code: str
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, state=state, subjects=(subject,))
    student = add_student(sm)
    review = add_review_row(
        sm,
        booking=add_booking(sm, student=student, tutor=tutor, subject=subject),
        tutor_id=tutor.profile_id,
        student=student,
    )
    act_as(client, tutor.user_id, Role.teacher)
    refused = client.post(f"/api/tutor/reviews/{review}/reply", json={"body": "Thank you"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, code)
    assert refused.headers["cache-control"] == NO_STORE
    readable = client.get("/api/tutor/reviews")
    assert readable.status_code == 200
    assert len(readable.json()["items"]) == 1


def test_t18_t21_404_no_tutor_profile(client: TestClient, sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)
    for response in (
        client.post(f"/api/tutor/reviews/{uuid.uuid4()}/reply", json={"body": "Thank you"}),
        client.get("/api/tutor/reviews"),
    ):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "no_tutor_profile"
        assert response.headers["cache-control"] == NO_STORE


def test_t18_unknown_review_and_malformed_bodies(client: TestClient, s: Setup) -> None:
    act_as(client, s.tutor.user_id, Role.teacher)
    missing = client.post(f"/api/tutor/reviews/{uuid.uuid4()}/reply", json={"body": "Thank you"})
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "not_found")
    review = s.seeded_review()
    blank = client.post(f"/api/tutor/reviews/{review}/reply", json={"body": "   "})
    assert (blank.status_code, blank.json()["detail"]["code"]) == (422, "reply_empty")
    long_body = client.post(f"/api/tutor/reviews/{review}/reply", json={"body": "x" * 1001})
    assert (long_body.status_code, long_body.json()["detail"]["code"]) == (422, "text_too_long")
    assert client.post(f"/api/tutor/reviews/{review}/reply", json={}).status_code == 422
    assert client.post("/api/tutor/reviews/nope/reply", json={"body": "Thanks"}).status_code == 422


# ---------------------------------------------------------------------------
# Paging (SP3, T21, A6)
# ---------------------------------------------------------------------------


def test_sp3_pages_newest_first_with_an_opaque_cursor(client: TestClient, s: Setup) -> None:
    now = datetime.now(UTC)
    ids = [
        s.seeded_review(stars=1 + i % 5, created_at=now - timedelta(days=i + 1)) for i in range(5)
    ]
    act_as(client, s.viewer, Role.student)
    url = f"/api/tutors/{s.tutor.profile_id}/reviews"
    first = client.get(url, params={"limit": 2}).json()
    assert [i["reviewId"] for i in first["items"]] == [str(ids[0]), str(ids[1])]
    assert first["nextCursor"] is not None
    second = client.get(url, params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert [i["reviewId"] for i in second["items"]] == [str(ids[2]), str(ids[3])]
    last = client.get(url, params={"limit": 2, "cursor": second["nextCursor"]}).json()
    assert ([i["reviewId"] for i in last["items"]], last["nextCursor"]) == ([str(ids[4])], None)
    default = client.get(url).json()
    assert len(default["items"]) == 5

    for bad in ({"limit": 0}, {"limit": 51}, {"cursor": "junk"}, {"cursor": ""}):
        refused = client.get(url, params=bad)
        assert refused.status_code == 422, bad
        assert refused.headers["cache-control"] == NO_STORE


def test_a6_filters_by_kind_and_pages_oldest_first(
    client: TestClient, sm: sessionmaker[Session], s: Setup
) -> None:
    now = datetime.now(UTC)
    old = s.seeded_review(text="old text", text_state="pending", created_at=now - timedelta(days=5))
    new = s.seeded_review(text="new text", text_state="pending", created_at=now - timedelta(days=1))
    add_reply_row(
        sm,
        review=s.seeded_review(created_at=now - timedelta(days=9)),
        tutor_id=s.tutor.profile_id,
        body="a reply",
        created_at=now - timedelta(days=3),
    )
    act_as(client, s.admin, Role.platform_admin)
    url = "/api/admin/tutoring/moderation"
    everything = client.get(url)
    assert everything.status_code == 200
    assert everything.headers["cache-control"] == NO_STORE
    assert [(i["kind"], i["text"]) for i in everything.json()["items"]] == [
        ("review", "old text"),
        ("reply", "a reply"),
        ("review", "new text"),
    ]
    assert [i["itemId"] for i in client.get(url, params={"kind": "review"}).json()["items"]] == [
        str(old),
        str(new),
    ]
    assert [i["kind"] for i in client.get(url, params={"kind": "reply"}).json()["items"]] == [
        "reply"
    ]
    page = client.get(url, params={"limit": 2}).json()
    assert len(page["items"]) == 2
    rest = client.get(url, params={"limit": 2, "cursor": page["nextCursor"]}).json()
    assert [i["text"] for i in rest["items"]] == ["new text"]
    assert rest["nextCursor"] is None
    assert client.get(url, params={"kind": "everything"}).status_code == 422
    assert client.get(url, params={"cursor": "junk"}).status_code == 422


def test_a7_a8_refusals(client: TestClient, sm: sessionmaker[Session], s: Setup) -> None:
    review = s.seeded_review(text="text", text_state="pending")
    stars_only = s.seeded_review(stars=3)
    reply = add_reply_row(sm, review=review, tutor_id=s.tutor.profile_id, state="pending")
    act_as(client, s.admin, Role.platform_admin)

    def moderate(kind: str, item: uuid.UUID, decision: str) -> tuple[int, object]:
        response = client.post(
            f"/api/admin/tutoring/{kind}/{item}/moderate", json={"decision": decision}
        )
        assert response.headers["cache-control"] == NO_STORE
        detail = response.json().get("detail")
        return response.status_code, detail.get("code") if isinstance(detail, dict) else detail

    assert moderate("reviews", uuid.uuid4(), "approved") == (404, "not_found")
    assert moderate("replies", uuid.uuid4(), "approved") == (404, "not_found")
    assert moderate("reviews", stars_only, "approved") == (409, "not_pending")
    assert (
        client.post(
            f"/api/admin/tutoring/reviews/{review}/moderate", json={"decision": "maybe"}
        ).status_code
        == 422
    )
    assert client.post(f"/api/admin/tutoring/reviews/{review}/moderate", json={}).status_code == 422
    assert moderate("reviews", review, "rejected")[0] == 200
    assert moderate("reviews", review, "approved") == (409, "not_pending")
    assert moderate("replies", reply, "approved")[0] == 200
    assert moderate("replies", reply, "rejected") == (409, "not_pending")
    assert review_row(sm, review).text_state == "rejected"


def test_anonymous_callers_are_401(client: TestClient, s: Setup) -> None:
    anonymous(client)
    for response in (
        client.get(f"/api/tutors/{s.tutor.profile_id}/reviews"),
        client.get("/api/tutor/reviews"),
        client.get("/api/admin/tutoring/moderation"),
        client.post(f"/api/student/bookings/{uuid.uuid4()}/review", json={"stars": 5}),
    ):
        assert response.status_code == 401
