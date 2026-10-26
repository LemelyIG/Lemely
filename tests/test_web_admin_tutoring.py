"""Platform-admin tutor approval routes A1-A4 (SPEC §b.2 "Platform admin", §a.3, SC-6, SC-22/23).

A1 lists the queue and reports the email delivery mode; A2 is the only route
that issues evidence URLs (300 s, ``attachment``), and writes one
``tutoring_admin_access`` ``evidence_open`` row per URL it issues, failing the
request when that write fails; A3 approves or reinstates; A4 rejects. Every
route is ``private, no-store`` on every status (``TutoringRoute``). Apps are
built with ``tests.tutoring_app.app_with_routers`` (a lane never edits
``lemely/web/app.py``).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from lemely.db.models.enums import NotificationType, Role, TutorListingState
from lemely.db.models.ops import Notification
from lemely.db.models.tutoring import EmailOutbox, TutorEvidenceFile, TutorProfile
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.tutor_approval_repo import TutorApprovalRepository
from lemely.db.tutor_evidence_repo import TutorEvidenceRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.runtime.errors import ExternalServiceError
from lemely.web.deps import (
    get_notification_service,
    get_push_transport,
    get_settings,
    get_storage_backend,
)
from lemely.web.deps_tutoring import get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import admin_tutors, tutor_evidence, tutor_profile
from lemely.web.routers.admin_tutors import get_tutor_approval_repo
from lemely.web.routers.tutor_evidence import get_tutor_evidence_repo
from tests.storage_fakes import FakeStorageBackend
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import NOW, act_as, add_subject, add_tutor, add_user, emptied_after
from tests.tutoring_db import tutoring_database as _tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.storage import StorageBackend

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
NO_STORE = "private, no-store"


def evidence_bucket() -> str:
    return get_settings().storage.tutor_evidence_bucket


def admin_tutoring_client(
    sm: sessionmaker[Session],
    storage: StorageBackend,
    transport: RecordingPushTransport | None = None,
) -> TestClient:
    """The T1-T5, T6-T7 and A1-A4 routers on a fresh app, wired to the test database."""
    app = app_with_routers(tutor_profile.router, tutor_evidence.router, admin_tutors.router)
    push = transport if transport is not None else RecordingPushTransport()
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(sm)
    app.dependency_overrides[get_tutor_evidence_repo] = lambda: TutorEvidenceRepository(sm)
    app.dependency_overrides[get_tutor_approval_repo] = lambda: TutorApprovalRepository(sm)
    app.dependency_overrides[get_storage_backend] = lambda: storage
    app.dependency_overrides[get_notification_service] = lambda: NotificationService(
        sm, NotificationPreferencesService(sm)
    )
    app.dependency_overrides[get_push_transport] = lambda: push
    return TestClient(app)


def seed_evidence(
    sm: sessionmaker[Session],
    storage: StorageBackend,
    profile_id: uuid.UUID,
    *,
    filename: str = "degree.pdf",
) -> uuid.UUID:
    """An evidence row and its stored object, bypassing the upload route."""
    evidence_id = uuid.uuid4()
    path = f"tutor-evidence/{profile_id}/{evidence_id}.pdf"
    storage.upload(evidence_bucket(), path, PDF, "application/pdf")
    with sm.begin() as session:
        session.add(
            TutorEvidenceFile(
                id=evidence_id,
                tutor_profile_id=profile_id,
                storage_path=path,
                original_filename=filename,
                content_type="application/pdf",
                size_bytes=len(PDF),
                description="Degree certificate",
            )
        )
    return evidence_id


def access_rows(sm: sessionmaker[Session]) -> list[tuple[object, ...]]:
    with sm() as session:
        return [
            tuple(row)
            for row in session.execute(
                sa.text(
                    "SELECT admin_user_id, action::text, tutor_profile_id, evidence_id, "
                    "report_id, booking_id FROM tutoring_admin_access ORDER BY created_at, id"
                )
            )
        ]


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with _tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def storage() -> FakeStorageBackend:
    return FakeStorageBackend()


@pytest.fixture
def transport() -> RecordingPushTransport:
    return RecordingPushTransport()


@pytest.fixture
def client(
    sm: sessionmaker[Session], storage: FakeStorageBackend, transport: RecordingPushTransport
) -> Iterator[TestClient]:
    test_client = admin_tutoring_client(sm, storage, transport)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def admin(sm: sessionmaker[Session], client: TestClient) -> uuid.UUID:
    admin_id = add_user(sm, Role.platform_admin)
    act_as(client, admin_id, Role.platform_admin)
    return admin_id


def _set(sm: sessionmaker[Session], profile_id: uuid.UUID, **columns: object) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(TutorProfile).where(TutorProfile.id == profile_id).values(**columns)
        )


# ---------------------------------------------------------------------------
# A1 queue
# ---------------------------------------------------------------------------


def test_a1_lists_the_pending_queue_oldest_first_with_keyset_pages(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    subject = add_subject(sm, name="Biology")
    tutors = [add_tutor(sm, state="pending_review", subjects=[subject]) for _ in range(3)]
    for days, tutor in zip((5, 3, 4), tutors, strict=True):
        _set(sm, tutor.profile_id, submitted_at=NOW - timedelta(days=days))
    add_tutor(sm, state="listed", subjects=[subject])

    first = client.get("/api/admin/tutors", params={"limit": 2})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert set(page) == {"items", "nextCursor", "emailDelivery"}
    assert [item["tutorId"] for item in page["items"]] == [
        str(tutors[0].profile_id),
        str(tutors[2].profile_id),
    ]
    item = page["items"][0]
    assert set(item) == {"tutorId", "publicName", "subjects", "submittedAt"}
    assert item["publicName"] == "Sara M."
    assert item["subjects"] == [{"code": subject, "name": "Biology"}]
    assert item["submittedAt"].startswith(str((NOW - timedelta(days=5)).date()))

    second = client.get("/api/admin/tutors", params={"limit": 2, "cursor": page["nextCursor"]})
    assert second.status_code == 200
    assert [i["tutorId"] for i in second.json()["items"]] == [str(tutors[1].profile_id)]
    assert second.json()["nextCursor"] is None


def test_a1_state_filter_and_cursor_bound_to_its_state(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    for _ in range(2):
        add_tutor(sm, state="pending_review")
    listed = add_tutor(sm, state="listed")

    only_listed = client.get("/api/admin/tutors", params={"state": "listed"})
    assert [i["tutorId"] for i in only_listed.json()["items"]] == [str(listed.profile_id)]

    cursor = client.get("/api/admin/tutors", params={"limit": 1}).json()["nextCursor"]
    assert cursor is not None
    replayed = client.get("/api/admin/tutors", params={"state": "listed", "cursor": cursor})
    assert replayed.status_code == 422
    assert replayed.json()["detail"]["code"] == "invalid_cursor"
    assert replayed.headers["cache-control"] == NO_STORE

    assert client.get("/api/admin/tutors", params={"state": "approved"}).status_code == 422
    assert client.get("/api/admin/tutors", params={"limit": 51}).status_code == 422


@pytest.mark.parametrize(("api_key", "mode"), [(None, "mock"), ("re_test_key", "provider")])
def test_a1_reports_email_delivery_mode(
    client: TestClient, admin: uuid.UUID, api_key: str | None, mode: str
) -> None:
    """SC-6: X-04 shows "Email delivery: mock" when no provider key is configured."""
    base = get_settings()
    configured = base.model_copy(
        update={
            "email": base.email.model_copy(
                update={"api_key": SecretStr(api_key) if api_key else None}
            )
        }
    )
    client.app.dependency_overrides[get_settings] = lambda: configured  # type: ignore[attr-defined]

    response = client.get("/api/admin/tutors")

    assert response.status_code == 200
    assert response.json()["emailDelivery"] == mode


# ---------------------------------------------------------------------------
# A2 detail: evidence URLs (SC-22) and the admin access log (SC-23)
# ---------------------------------------------------------------------------


def test_idor_a2_evidence_url_ttl_300_and_attachment(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend, admin: uuid.UUID
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    evidence_id = seed_evidence(sm, storage, tutor.profile_id, filename="degree.pdf")

    response = client.get(f"/api/admin/tutors/{tutor.profile_id}")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    [item] = response.json()["evidence"]
    assert item["evidenceId"] == str(evidence_id)
    url = urlsplit(item["signedUrl"])
    query = parse_qs(url.query)
    # SPEC §i.2 / SC-22: links are valid 300 s, from the dedicated setting, not the avatar TTL.
    assert query["expires_in"] == ["300"]
    assert get_settings().storage.tutor_evidence_signed_url_ttl_seconds == 300
    assert get_settings().storage.signed_url_ttl_seconds != 300
    assert url.netloc == evidence_bucket()
    [disposition] = query["disposition"]
    assert disposition.startswith('attachment; filename="degree.pdf"')
    assert "filename*=UTF-8''degree.pdf" in disposition

    # Only a platform admin reaches A2: the profile's own tutor and a student are refused.
    for role, user in ((Role.teacher, tutor.user_id), (Role.student, add_user(sm, Role.student))):
        act_as(client, user, role)
        refused = client.get(f"/api/admin/tutors/{tutor.profile_id}")
        assert refused.status_code == 403
        assert "signedUrl" not in refused.text


def test_a2_writes_one_evidence_open_row_per_url_and_fails_closed(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend, admin: uuid.UUID
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    first = seed_evidence(sm, storage, tutor.profile_id, filename="a.pdf")
    second = seed_evidence(sm, storage, tutor.profile_id, filename="b.pdf")

    assert client.get(f"/api/admin/tutors/{tutor.profile_id}").status_code == 200
    rows = access_rows(sm)
    assert sorted(rows, key=str) == sorted(
        [
            (admin, "evidence_open", tutor.profile_id, first, None, None),
            (admin, "evidence_open", tutor.profile_id, second, None, None),
        ],
        key=str,
    )

    # Every read is logged again: two more URLs, two more rows.
    client.get(f"/api/admin/tutors/{tutor.profile_id}")
    assert len(access_rows(sm)) == 4

    # Fail closed (SC-23): when the log write fails, the request fails and no URL leaves.
    with sm.begin() as session:
        session.execute(
            sa.text(
                "CREATE FUNCTION t10_refuse_admin_access() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'access log unavailable'; END $$"
            )
        )
        session.execute(
            sa.text(
                "CREATE TRIGGER t10_refuse BEFORE INSERT ON tutoring_admin_access "
                "FOR EACH ROW EXECUTE FUNCTION t10_refuse_admin_access()"
            )
        )
    try:
        quiet = TestClient(client.app, raise_server_exceptions=False)
        failed = quiet.get(f"/api/admin/tutors/{tutor.profile_id}")
    finally:
        with sm.begin() as session:
            session.execute(sa.text("DROP TRIGGER t10_refuse ON tutoring_admin_access"))
            session.execute(sa.text("DROP FUNCTION t10_refuse_admin_access()"))
    assert failed.status_code == 500
    assert "fake://" not in failed.text
    assert "signedUrl" not in failed.text
    assert len(access_rows(sm)) == 4


class _SigningFailsFor(FakeStorageBackend):
    """Signs every object except one, like a backend refusing a single key."""

    def __init__(self, failing_path: str) -> None:
        super().__init__()
        self.failing_path = failing_path

    def create_signed_url(
        self, bucket: str, object_path: str, expires_in: int, *, disposition: str | None = None
    ) -> str:
        if object_path == self.failing_path:
            raise ExternalServiceError("cannot sign")
        return super().create_signed_url(bucket, object_path, expires_in, disposition=disposition)


def test_a2_unsigned_file_has_no_url_and_no_access_row(
    sm: sessionmaker[Session], admin: uuid.UUID, client: TestClient
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    storage = FakeStorageBackend()
    ok = seed_evidence(sm, storage, tutor.profile_id, filename="ok.pdf")
    broken = seed_evidence(sm, storage, tutor.profile_id, filename="broken.pdf")
    with sm() as session:
        broken_path = session.get(TutorEvidenceFile, broken).storage_path  # type: ignore[union-attr]
    signing = _SigningFailsFor(broken_path)
    client.app.dependency_overrides[get_storage_backend] = lambda: signing  # type: ignore[attr-defined]

    body = client.get(f"/api/admin/tutors/{tutor.profile_id}").json()

    urls = {item["evidenceId"]: item["signedUrl"] for item in body["evidence"]}
    assert urls[str(broken)] is None
    assert urls[str(ok)] is not None
    assert [row[3] for row in access_rows(sm)] == [ok]


def test_a2_detail_fields(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend, admin: uuid.UUID
) -> None:
    subject = add_subject(sm, name="Mathematics")
    tutor = add_tutor(sm, state="pending_review", subjects=[subject], bio="Patient.")
    seed_evidence(sm, storage, tutor.profile_id)
    TutorApprovalRepository(sm).reject(tutor.profile_id, admin_user_id=admin, note="Add a photo.")

    body = client.get(f"/api/admin/tutors/{tutor.profile_id}").json()

    assert body["tutorId"] == str(tutor.profile_id)
    assert body["listingState"] == "rejected"
    assert body["accountEmail"] == f"{tutor.user_id}@example.com"
    assert body["reviewNote"] == "Add a photo."
    assert body["openReports"] == 0
    assert body["reReviewRequired"] is False
    assert body["bio"] == "Patient."
    assert body["subjects"] == [{"code": subject, "name": "Mathematics"}]
    assert [h["decision"] for h in body["history"]] == ["rejected"]
    assert set(body["history"][0]) == {"decision", "documentsSeen", "note", "createdAt"}
    assert set(body["evidence"][0]) == {
        "evidenceId",
        "filename",
        "contentType",
        "sizeBytes",
        "description",
        "uploadedAt",
        "signedUrl",
    }


def test_a2_unknown_404_and_malformed_422(client: TestClient, admin: uuid.UUID) -> None:
    missing = client.get(f"/api/admin/tutors/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "not_found"
    assert missing.headers["cache-control"] == NO_STORE
    malformed = client.get("/api/admin/tutors/not-a-uuid")
    assert malformed.status_code == 422
    assert malformed.headers["cache-control"] == NO_STORE


# ---------------------------------------------------------------------------
# A3 approve / reinstate, A4 reject
# ---------------------------------------------------------------------------


def _notifications(sm: sessionmaker[Session], user_id: uuid.UUID) -> list[Notification]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.type == NotificationType.tutor_listing,
                )
            )
        )


def test_a3_approves_and_tells_the_tutor_after_commit(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend, admin: uuid.UUID
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    seed_evidence(sm, storage, tutor.profile_id)

    response = client.post(
        f"/api/admin/tutors/{tutor.profile_id}/approve",
        json={"documentsSeen": True, "note": "Degree checked."},
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert body["listingState"] == "listed"
    assert body["documentsSeen"] is True
    assert body["listedSince"] is not None
    assert [item["signedUrl"] for item in body["evidence"]] == [None]  # only A2 issues URLs
    assert access_rows(sm) == []
    assert body["history"][0]["decision"] == "approved"
    assert body["history"][0]["note"] == "Degree checked."

    [notice] = _notifications(sm, tutor.user_id)
    assert notice.title == "Your tutor profile is listed"
    assert "Degree checked" not in (notice.body or "")
    with sm() as session:
        [mail] = session.scalars(sa.select(EmailOutbox)).all()
    assert notice.dedupe_key == mail.dedupe_key
    assert mail.context["decision"] == "approved"


def test_a3_reinstates_by_the_lead_ruling(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    never_approved = add_tutor(sm, state="suspended", first_listed_at=None)
    was_listed = add_tutor(sm, state="suspended", first_listed_at=NOW - timedelta(days=60))

    queued = client.post(
        f"/api/admin/tutors/{never_approved.profile_id}/approve", json={"documentsSeen": False}
    )
    relisted = client.post(
        f"/api/admin/tutors/{was_listed.profile_id}/approve", json={"documentsSeen": False}
    )

    assert queued.status_code == 200
    assert queued.json()["listingState"] == "pending_review"
    assert queued.json()["history"][0]["decision"] == "reinstated"
    assert _notifications(sm, never_approved.user_id) == []
    assert relisted.status_code == 200
    assert relisted.json()["listingState"] == "listed"
    assert relisted.json()["history"][0]["decision"] == "reinstated"
    [notice] = _notifications(sm, was_listed.user_id)
    assert notice.title == "Your tutor profile is listed again"


def test_a3_refusals(client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    listed = add_tutor(sm, state="listed")
    conflict = client.post(
        f"/api/admin/tutors/{listed.profile_id}/approve", json={"documentsSeen": True}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "illegal_transition"
    assert conflict.headers["cache-control"] == NO_STORE

    pending = add_tutor(sm, state="pending_review")
    missing_field = client.post(f"/api/admin/tutors/{pending.profile_id}/approve", json={})
    assert missing_field.status_code == 422
    assert missing_field.headers["cache-control"] == NO_STORE
    long_note = client.post(
        f"/api/admin/tutors/{pending.profile_id}/approve",
        json={"documentsSeen": True, "note": "x" * 2001},
    )
    assert long_note.status_code == 422
    assert long_note.json()["detail"]["code"] == "note_too_long"

    unknown = client.post(f"/api/admin/tutors/{uuid.uuid4()}/approve", json={"documentsSeen": True})
    assert unknown.status_code == 404
    assert unknown.headers["cache-control"] == NO_STORE


def test_a4_rejects_with_a_note_the_tutor_reads(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    note = "Please upload a clearer certificate."

    response = client.post(f"/api/admin/tutors/{tutor.profile_id}/reject", json={"note": note})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    assert response.json()["listingState"] == "rejected"
    assert response.json()["reviewNote"] == note
    [notice] = _notifications(sm, tutor.user_id)
    assert note not in (notice.body or "")

    act_as(client, tutor.user_id, Role.teacher)
    own = client.get("/api/tutor/profile").json()
    assert own["listingState"] == "rejected"
    assert own["reviewNote"] == note


def test_a4_without_note_422_note_required(
    client: TestClient, sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    for body in ({}, {"note": None}, {"note": "   "}):
        response = client.post(f"/api/admin/tutors/{tutor.profile_id}/reject", json=body)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "note_required"
        assert response.headers["cache-control"] == NO_STORE
    with sm() as session:
        assert session.get(TutorProfile, tutor.profile_id).listing_state is (  # type: ignore[union-attr]
            TutorListingState.pending_review
        )

    listed = add_tutor(sm, state="listed")
    conflict = client.post(f"/api/admin/tutors/{listed.profile_id}/reject", json={"note": "No."})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "illegal_transition"
