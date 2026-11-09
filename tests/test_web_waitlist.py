"""The waitlist at the HTTP boundary: public two-step flow, admin queue, CSV and digest.

Hermetic: a throwaway ``create_all`` Postgres, a recording email provider, limiters on an
injected clock, and a repository clock the tests can advance past the token's expiry.
"""

from __future__ import annotations

import csv
import io
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core.waitlist import (
    CONSENT_VERSIONS,
    CURRENT_CONSENT_VERSION,
    exam_session_options,
)
from lemely.db.models.enums import Role
from lemely.db.models.waitlist import WaitlistApplicant
from lemely.db.waitlist_repo import WaitlistRepository
from lemely.runtime.config import EdgeSettings, WaitlistSettings
from lemely.web.app import create_app
from lemely.web.deps import (
    WaitlistLimiters,
    get_email_provider,
    get_settings,
    get_turnstile_verifier,
    get_waitlist_limiters,
    reset_singletons,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers.waitlist import get_waitlist_repo
from tests.auth_fakes import FakeEmailProvider
from tests.tutoring_db import act_as, anonymous, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx2 import Response
    from sqlalchemy.orm import Session, sessionmaker

CONSENT_VERSION = CURRENT_CONSENT_VERSION
CONSENT = CONSENT_VERSIONS[CURRENT_CONSENT_VERSION]
SECRET = "digest-secret-for-tests"
NEXT_SESSION = exam_session_options(datetime.now(UTC).date())[0][0]


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


class LimiterClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def database() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield database
    with database.begin() as session:
        session.execute(sa.text("TRUNCATE waitlist_applicants, waitlist_digest_log"))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def provider() -> FakeEmailProvider:
    return FakeEmailProvider()


@pytest.fixture
def limiter_clock() -> LimiterClock:
    return LimiterClock()


class FakeTurnstile:
    """Records calls; ``ok`` is what Cloudflare would say."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, str | None]] = []

    def verify(self, token: str, remote_ip: str | None) -> bool:
        self.calls.append((token, remote_ip))
        return self.ok and token == "good-token"


@contextmanager
def build_client(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
    *,
    edge_secret: str | None = None,
    turnstile: FakeTurnstile | None = None,
    turnstile_site_key: str | None = None,
    per_client_limit: int = 50,
    global_limit: int = 500,
    edge_previous: str | None = None,
) -> Iterator[TestClient]:
    reset_singletons()
    app = create_app()
    limiters = WaitlistLimiters(
        per_client=SlidingWindowLimiter(
            limit=per_client_limit, window_seconds=600.0, clock=limiter_clock
        ),
        global_=SlidingWindowLimiter(
            limit=global_limit, window_seconds=86400.0, clock=limiter_clock
        ),
    )
    settings = get_settings().model_copy(
        update={
            "waitlist": WaitlistSettings(
                digest_secret=SECRET,
                turnstile_secret_key="turnstile-secret" if turnstile else None,
                turnstile_site_key=turnstile_site_key,
            ),
            "edge": EdgeSettings(origin_secret=edge_secret, origin_secret_previous=edge_previous),
        }
    )
    app.dependency_overrides.update(
        {
            get_waitlist_repo: lambda: WaitlistRepository(sm, now=clock),
            get_waitlist_limiters: lambda: limiters,
            get_email_provider: lambda: provider,
            get_settings: lambda: settings,
            get_turnstile_verifier: lambda: turnstile,
        }
    )
    with TestClient(app) as test_client:
        yield test_client
    reset_singletons()


@pytest.fixture
def client(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> Iterator[TestClient]:
    with build_client(sm, clock, provider, limiter_clock) as test_client:
        yield test_client


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    act_as(client, uuid.uuid4(), Role.platform_admin)
    return client


def step1(
    client: TestClient, email: str = "sara@example.com", role: str = "student", **extra: object
) -> Response:
    body = {"email": email, "role": role, "consentVersion": CONSENT_VERSION, **extra}
    return client.post("/api/waitlist", json=body)


def step2(client: TestClient, token: str, **overrides: object) -> Response:
    body: dict[str, object] = {"token": token, "subjects": ["biology"], **overrides}
    return client.patch("/api/waitlist", json=body)


def join(
    client: TestClient, email: str, role: str = "student", *, full: bool = True, **detail: object
) -> None:
    token = step1(client, email, role).json()["token"]
    if full:
        assert step2(client, token, **detail).status_code == 200


def row_for(sm: sessionmaker[Session], email: str) -> WaitlistApplicant:
    with sm() as session:
        return session.execute(
            sa.select(WaitlistApplicant).where(WaitlistApplicant.email == email)
        ).scalar_one()


def count_rows(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return session.execute(
            sa.select(sa.func.count()).select_from(WaitlistApplicant)
        ).scalar_one()


# ---------------------------------------------------------------------------
# Step 1
# ---------------------------------------------------------------------------


def test_step1_creates_a_partial_row_and_returns_a_token(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    response = step1(client, "  Sara@Example.com ", utmSource="waitlist_share", utmMedium="social")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    token = body["token"]
    row = row_for(sm, "sara@example.com")
    assert row.completed_at is None
    assert row.role.value == "student"
    assert row.status.value == "new"
    assert row.consent_text == CONSENT  # the server's canonical wording
    assert row.consent_version == CONSENT_VERSION
    assert row.consent_at is not None
    assert row.utm_source == "waitlist_share"
    assert row.utm_medium == "social"
    # Only the digest is stored, never the token.
    assert row.completion_token_hash is not None
    assert row.completion_token_hash != token
    assert token not in str(row.completion_token_hash)


def test_duplicate_email_gets_no_token_and_changes_nothing(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    first = step1(client, "dup@example.com", role="student").json()
    before = row_for(sm, "dup@example.com")

    again = step1(client, "DUP@example.com", role="teacher", utmSource="other")

    assert again.status_code == 200
    assert again.json() == {"status": "already_listed"}
    assert "token" not in again.text
    after = row_for(sm, "dup@example.com")
    assert count_rows(sm) == 1
    assert after.role == before.role
    assert after.utm_source == before.utm_source
    assert after.completion_token_hash == before.completion_token_hash
    assert after.updated_at == before.updated_at
    # The original token still works: the duplicate did not rotate it.
    assert step2(client, first["token"]).status_code == 200


def test_step1_validation(client: TestClient) -> None:
    assert step1(client, "not-an-email").status_code == 422
    assert step1(client, "a@b.co", role="wizard").status_code == 422
    assert (
        client.post("/api/waitlist", json={"email": "a@b.co", "role": "student"}).status_code == 422
    )
    assert step1(client, "a@b.co", extra_field="x").status_code == 422


def test_honeypot_looks_like_success_but_stores_nothing(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    response = step1(client, "bot@example.com", website="http://spam.example")

    assert response.status_code == 200
    assert response.json()["status"] == "created"
    assert response.json()["token"]
    assert count_rows(sm) == 0


def test_oversized_body_is_413(client: TestClient) -> None:
    response = client.post(
        "/api/waitlist",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "9000"},
    )
    assert response.status_code == 413


def test_rate_limit_429_with_retry_after(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    reset_singletons()
    app = create_app()
    tight = WaitlistLimiters(
        per_client=SlidingWindowLimiter(limit=2, window_seconds=600.0, clock=limiter_clock),
        global_=SlidingWindowLimiter(limit=100, window_seconds=86400.0, clock=limiter_clock),
    )
    app.dependency_overrides[get_waitlist_repo] = lambda: WaitlistRepository(sm, now=clock)
    app.dependency_overrides[get_waitlist_limiters] = lambda: tight
    with TestClient(app) as tc:
        assert step1(tc, "a1@example.com").status_code == 200
        assert step1(tc, "a2@example.com").status_code == 200
        blocked = step1(tc, "a3@example.com")
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
        assert count_rows(sm) == 2
        limiter_clock.now += 601
        assert step1(tc, "a3@example.com").status_code == 200
    reset_singletons()


# ---------------------------------------------------------------------------
# Step 2
# ---------------------------------------------------------------------------


def test_step2_completes_the_row(client: TestClient, sm: sessionmaker[Session]) -> None:
    token = step1(client, "kid@example.com").json()["token"]

    response = step2(
        client,
        token,
        levels=["o_level", "o_level", "as_level"],
        subjects=["biology", "physics", "biology"],
        otherSubjects=["  Drama ", "drama", "", "Film Studies"],
        examBoards=["caie", "edexcel"],
        examSession=NEXT_SESSION,
        phone="0100 123 4567",
        phoneHasWhatsapp=True,
        centreName="Ignored Centre",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "completed"}
    row = row_for(sm, "kid@example.com")
    assert row.completed_at is not None
    assert row.levels == ["o_level", "as_level"]
    assert row.subjects == ["biology", "physics"]
    assert row.other_subjects == ["Drama", "Film Studies"]  # trimmed, blanks and repeats dropped
    assert row.exam_boards == ["caie", "edexcel"]
    assert row.exam_session == NEXT_SESSION
    assert row.phone == "+201001234567"
    assert row.phone_has_whatsapp is True
    assert row.centre_name is None  # only a centre administrator keeps one
    assert row.completion_token_hash is None  # single use: the digest is gone


def test_a_token_cannot_be_reused(client: TestClient, sm: sessionmaker[Session]) -> None:
    token = step1(client, "once@example.com").json()["token"]
    assert step2(client, token, subjects=["biology"]).status_code == 200

    replay = step2(client, token, subjects=["physics"], phone="01001234567")

    assert replay.status_code == 400
    row = row_for(sm, "once@example.com")
    assert row.subjects == ["biology"]
    assert row.phone is None


def test_an_expired_token_is_refused(
    client: TestClient, sm: sessionmaker[Session], clock: Clock
) -> None:
    token = step1(client, "late@example.com").json()["token"]
    clock.now += timedelta(hours=25)

    assert step2(client, token).status_code == 400
    assert row_for(sm, "late@example.com").completed_at is None


def test_a_token_still_works_inside_the_window(client: TestClient, clock: Clock) -> None:
    token = step1(client, "ontime@example.com").json()["token"]
    clock.now += timedelta(hours=23)
    assert step2(client, token).status_code == 200


def test_an_unknown_token_is_refused(client: TestClient) -> None:
    assert step2(client, "x" * 43).status_code == 400


def test_centre_admin_keeps_centre_name_and_session_is_ignored(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    token = step1(client, "head@example.com", role="centre_admin").json()["token"]

    response = step2(
        client,
        token,
        centreName="  Nile Learning Centre ",
        examSession=NEXT_SESSION,
        levels=["o_level", "a_level"],
    )

    assert response.status_code == 200
    row = row_for(sm, "head@example.com")
    assert row.centre_name == "Nile Learning Centre"
    assert row.exam_session is None
    assert row.levels == ["o_level", "a_level"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"phone": "12345"},
        {"phone": "01301234567"},
        {"subjects": ["underwater_basket_weaving"]},
        {"examSession": "2020-mj"},
        {"examSession": "2099-mj"},
        {"examSession": "next summer"},
        {"levels": ["igcse"]},  # IGCSE is not a waitlist level
        {"subjects": [], "otherSubjects": []},  # nothing named at all
        {"subjects": ["other"]},  # "other" is not a subject value; use otherSubjects
        {"otherSubjects": ["a", "b", "c", "d", "e", "f"]},  # more than 5
        {"otherSubjects": ["x" * 61]},  # over 60 characters
        {"levels": ["gcse"]},
        {"examBoards": ["ocr"]},
    ],
)
def test_step2_validation_failures_are_422_and_do_not_burn_the_token(
    client: TestClient, sm: sessionmaker[Session], overrides: dict[str, object]
) -> None:
    token = step1(client, "val@example.com").json()["token"]

    assert step2(client, token, **overrides).status_code == 422

    assert row_for(sm, "val@example.com").completed_at is None
    assert step2(client, token).status_code == 200  # still redeemable


def test_step2_honeypot_succeeds_silently(client: TestClient, sm: sessionmaker[Session]) -> None:
    token = step1(client, "hp@example.com").json()["token"]

    response = step2(client, token, website="spam", phone="01001234567")

    assert response.status_code == 200
    assert row_for(sm, "hp@example.com").completed_at is None
    assert step2(client, token).status_code == 200  # the real token was not consumed


# ---------------------------------------------------------------------------
# Admin: RBAC
# ---------------------------------------------------------------------------

ADMIN_ROUTES = [
    ("GET", "/api/admin/waitlist"),
    ("GET", "/api/admin/waitlist/export.csv"),
    ("GET", f"/api/admin/waitlist/{uuid.uuid4()}"),
    ("PATCH", f"/api/admin/waitlist/{uuid.uuid4()}"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_anonymous_is_refused_on_every_admin_route(
    client: TestClient, method: str, path: str
) -> None:
    anonymous(client)
    response = client.request(method, path, json={"status": "contacted"})
    assert response.status_code == 401


@pytest.mark.parametrize("role", [Role.student, Role.teacher, Role.parent, Role.school_admin])
@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_non_platform_admin_roles_are_forbidden(
    client: TestClient, role: Role, method: str, path: str
) -> None:
    act_as(client, uuid.uuid4(), role)
    response = client.request(method, path, json={"status": "contacted"})
    assert response.status_code == 403


def test_a_refused_caller_changes_nothing(client: TestClient, sm: sessionmaker[Session]) -> None:
    join(client, "keep@example.com", full=False)
    applicant_id = str(row_for(sm, "keep@example.com").id)
    act_as(client, uuid.uuid4(), Role.teacher)

    assert (
        client.patch(f"/api/admin/waitlist/{applicant_id}", json={"status": "declined"}).status_code
        == 403
    )

    assert row_for(sm, "keep@example.com").status.value == "new"


# ---------------------------------------------------------------------------
# Admin: queue
# ---------------------------------------------------------------------------


def seed_queue(client: TestClient) -> None:
    join(
        client,
        "stu1@example.com",
        "student",
        levels=["o_level"],
        subjects=["biology", "physics"],
        examBoards=["caie"],
        examSession=NEXT_SESSION,
        phone="01001234567",
    )
    join(
        client,
        "stu2@example.com",
        "student",
        levels=["a_level"],
        subjects=["chemistry"],
        examBoards=["edexcel"],
    )
    join(
        client,
        "tea1@example.com",
        "teacher",
        levels=["o_level", "a_level"],
        subjects=["physics"],
        examBoards=["caie", "oxford_aqa"],
    )
    join(client, "par1@example.com", "parent", full=False)
    join(client, "cen1@example.com", "centre_admin", subjects=["mathematics"], centreName="Nile")


def emails(response: object) -> list[str]:
    return [item["email"] for item in response.json()["items"]]  # type: ignore[attr-defined]


def test_list_returns_every_field_counts_and_defaults(admin: TestClient) -> None:
    seed_queue(admin)

    response = admin.get("/api/admin/waitlist")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    body = response.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["pageSize"] == 50
    assert body["counts"] == {
        "all": 5,
        "new": 5,
        "contacted": 0,
        "invited": 0,
        "declined": 0,
        "partial": 1,
    }
    first = next(i for i in body["items"] if i["email"] == "stu1@example.com")
    assert first["phone"] == "+201001234567"
    assert first["subjects"] == ["biology", "physics"]
    assert first["partial"] is False
    assert first["consentText"] == CONSENT
    assert "completionTokenHash" not in first
    assert emails(response)[0] == "cen1@example.com"  # newest first by default


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"role": "student"}, {"stu1@example.com", "stu2@example.com"}),
        ({"role": "centre_admin"}, {"cen1@example.com"}),
        ({"level": "o_level"}, {"stu1@example.com", "tea1@example.com"}),
        ({"level": "a_level"}, {"stu2@example.com", "tea1@example.com"}),
        ({"subject": "physics"}, {"stu1@example.com", "tea1@example.com"}),
        ({"subject": "biology"}, {"stu1@example.com"}),
        ({"board": "caie"}, {"stu1@example.com", "tea1@example.com"}),
        ({"board": "oxford_aqa"}, {"tea1@example.com"}),
        ({"session": NEXT_SESSION}, {"stu1@example.com"}),
        ({"status": "partial"}, {"par1@example.com"}),
        ({"q": "TEA1"}, {"tea1@example.com"}),
        ({"q": "@example.com", "role": "parent"}, {"par1@example.com"}),
        ({"role": "student", "subject": "physics"}, {"stu1@example.com"}),
        ({"q": "%"}, set()),  # a wildcard is a literal, not "match everything"
        ({"q": "_"}, set()),
    ],
)
def test_list_filters(admin: TestClient, params: dict[str, str], expected: set[str]) -> None:
    seed_queue(admin)
    response = admin.get("/api/admin/waitlist", params=params)
    assert response.status_code == 200
    assert set(emails(response)) == expected
    assert response.json()["total"] == len(expected)


def test_date_range_filter_is_inclusive(admin: TestClient, sm: sessionmaker[Session]) -> None:
    seed_queue(admin)
    old = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant)
            .where(WaitlistApplicant.email == "stu2@example.com")
            .values(created_at=old)
        )

    on_day = admin.get(
        "/api/admin/waitlist", params={"createdFrom": "2026-01-10", "createdTo": "2026-01-10"}
    )
    before = admin.get("/api/admin/waitlist", params={"createdTo": "2026-01-09"})
    recent = admin.get("/api/admin/waitlist", params={"createdFrom": "2026-01-11"})

    assert emails(on_day) == ["stu2@example.com"]
    assert emails(before) == []
    assert "stu2@example.com" not in emails(recent)
    assert recent.json()["total"] == 4


def test_status_chips_ignore_the_status_filter_but_respect_the_rest(admin: TestClient) -> None:
    seed_queue(admin)
    applicant = admin.get("/api/admin/waitlist", params={"q": "stu1"}).json()["items"][0]
    admin.patch(f"/api/admin/waitlist/{applicant['id']}", json={"status": "invited"})

    only_students = admin.get(
        "/api/admin/waitlist", params={"role": "student", "status": "invited"}
    )

    assert emails(only_students) == ["stu1@example.com"]
    assert only_students.json()["counts"] == {
        "all": 2,
        "new": 1,
        "contacted": 0,
        "invited": 1,
        "declined": 0,
        "partial": 0,
    }


def test_sort_and_pagination(admin: TestClient) -> None:
    seed_queue(admin)

    asc = admin.get("/api/admin/waitlist", params={"sort": "email", "order": "asc"})
    desc = admin.get("/api/admin/waitlist", params={"sort": "email", "order": "desc"})
    page2 = admin.get(
        "/api/admin/waitlist", params={"sort": "email", "order": "asc", "page": 2, "pageSize": 2}
    )

    assert emails(asc) == sorted(emails(asc))
    assert emails(desc) == sorted(emails(desc), reverse=True)
    assert emails(page2) == emails(asc)[2:4]
    assert page2.json()["total"] == 5
    assert admin.get("/api/admin/waitlist", params={"sort": "phone"}).status_code == 422
    assert admin.get("/api/admin/waitlist", params={"pageSize": 500}).status_code == 422
    assert admin.get("/api/admin/waitlist", params={"status": "bogus"}).status_code == 422


def test_get_one_and_update_status_and_note(admin: TestClient, sm: sessionmaker[Session]) -> None:
    seed_queue(admin)
    applicant_id = str(row_for(sm, "tea1@example.com").id)

    one = admin.get(f"/api/admin/waitlist/{applicant_id}")
    assert one.status_code == 200
    assert one.json()["email"] == "tea1@example.com"

    both = admin.patch(
        f"/api/admin/waitlist/{applicant_id}",
        json={"status": "contacted", "adminNote": "Emailed Tue"},
    )
    assert both.status_code == 200
    assert both.json()["status"] == "contacted"
    assert both.json()["adminNote"] == "Emailed Tue"

    status_only = admin.patch(f"/api/admin/waitlist/{applicant_id}", json={"status": "invited"})
    assert status_only.json()["status"] == "invited"
    assert status_only.json()["adminNote"] == "Emailed Tue"  # untouched

    cleared = admin.patch(f"/api/admin/waitlist/{applicant_id}", json={"adminNote": None})
    assert cleared.json()["adminNote"] is None
    assert cleared.json()["status"] == "invited"

    assert admin.patch(f"/api/admin/waitlist/{applicant_id}", json={}).status_code == 422
    assert (
        admin.patch(f"/api/admin/waitlist/{applicant_id}", json={"status": "partial"}).status_code
        == 422
    )
    assert (
        admin.patch(
            f"/api/admin/waitlist/{applicant_id}", json={"adminNote": "x" * 2001}
        ).status_code
        == 422
    )
    missing = uuid.uuid4()
    assert admin.get(f"/api/admin/waitlist/{missing}").status_code == 404
    assert admin.patch(f"/api/admin/waitlist/{missing}", json={"status": "new"}).status_code == 404


# ---------------------------------------------------------------------------
# Admin: CSV
# ---------------------------------------------------------------------------


def parse_csv(response: object) -> list[dict[str, str]]:
    text = response.content.decode("utf-8-sig")  # type: ignore[attr-defined]
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_has_every_column_and_respects_filters(admin: TestClient) -> None:
    seed_queue(admin)

    response = admin.get(
        "/api/admin/waitlist/export.csv",
        params={"role": "student", "sort": "email", "order": "asc"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["Cache-Control"] == "private, no-store"
    rows = parse_csv(response)
    assert [r["email"] for r in rows] == ["stu1@example.com", "stu2@example.com"]
    expected_columns = {
        "id",
        "email",
        "role",
        "status",
        "centre_name",
        "levels",
        "subjects",
        "other_subjects",
        "exam_boards",
        "exam_session",
        "phone",
        "phone_has_whatsapp",
        "email_confirmed",
        "consent_version",
        "consent_text",
        "consent_at",
        "admin_note",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "completed_at",
        "created_at",
        "updated_at",
    }
    assert set(rows[0]) == expected_columns
    assert rows[0]["subjects"] == "biology; physics"
    assert rows[0]["phone"] == "+20 100 123 4567"  # spaced so spreadsheets keep it as text
    assert "completion_token_hash" not in rows[0]


def test_csv_neutralises_formula_injection(admin: TestClient, sm: sessionmaker[Session]) -> None:
    join(admin, "evil@example.com", full=False, utmSource="=HYPERLINK(1)")
    seed_evil = {
        "utm_source": '=HYPERLINK("http://evil","x")',
        "utm_medium": "+SUM(1+1)",
        "utm_campaign": "-2+3",
        "utm_content": "@cmd",
        "utm_term": "\tTAB",
        "admin_note": "\r=1+1",
        "centre_name": "=1+1",
    }
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant)
            .where(WaitlistApplicant.email == "evil@example.com")
            .values(**seed_evil)
        )

    rows = parse_csv(admin.get("/api/admin/waitlist/export.csv"))

    assert len(rows) == 1
    row = rows[0]
    for column, raw in seed_evil.items():
        assert row[column] == "'" + raw, column
        assert not row[column].startswith(("=", "+", "-", "@", "\t", "\r"))


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def digest(client: TestClient, secret: str | None = SECRET) -> Response:
    headers = {} if secret is None else {"X-Cron-Secret": secret}
    return client.post("/api/internal/waitlist/digest", headers=headers)


def test_digest_with_no_new_applicants_sends_nothing(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    response = digest(client)

    assert response.status_code == 200
    assert response.json() == {"newApplicants": 0, "sent": False, "alreadySent": False}
    assert provider.sent_team_digests == []


def test_digest_reports_aggregates_and_leaks_no_personal_data(
    client: TestClient, provider: FakeEmailProvider, sm: sessionmaker[Session]
) -> None:
    seed_queue(client)
    with sm.begin() as session:  # an applicant from last week must not count
        session.execute(
            sa.update(WaitlistApplicant)
            .where(WaitlistApplicant.email == "stu2@example.com")
            .values(created_at=datetime.now(UTC) - timedelta(days=3))
        )

    response = digest(client)

    assert response.json() == {"newApplicants": 4, "sent": True, "alreadySent": False}
    ((subject, body),) = provider.sent_team_digests
    assert "4 new applicants" in subject
    assert "Students: 1" in body
    assert "Teachers: 1" in body
    assert "Parents: 1" in body
    assert "Centre administrators: 1" in body
    assert "Completed the full form: 3" in body
    assert "Email and role only (partial): 1" in body
    assert "Physics: 2" in body  # top subjects, labelled
    assert "CAIE: 2" in body
    assert "Oxford AQA: 1" in body
    assert "Chemistry" not in body  # belonged to the old applicant
    combined = subject + body
    for private in ("@example.com", "+2010", "01001234567", "stu1", "tea1", "Nile"):
        assert private not in combined


def test_digest_requires_the_secret(client: TestClient, provider: FakeEmailProvider) -> None:
    step1(client, "someone@example.com")

    assert digest(client, None).status_code == 403
    assert digest(client, "wrong").status_code == 403
    assert provider.sent_team_digests == []


def test_digest_is_disabled_without_a_configured_secret(
    sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    reset_singletons()
    app = create_app()
    app.dependency_overrides[get_waitlist_repo] = lambda: WaitlistRepository(sm)
    app.dependency_overrides[get_email_provider] = lambda: provider
    with TestClient(app) as tc:
        assert (
            tc.post("/api/internal/waitlist/digest", headers={"X-Cron-Secret": ""}).status_code
            == 404
        )
        assert tc.post("/api/internal/waitlist/digest").status_code == 404
    reset_singletons()


def test_digest_provider_failure_is_a_502(client: TestClient, provider: FakeEmailProvider) -> None:
    step1(client, "someone@example.com")
    provider.raise_on_send = True

    response = digest(client)

    assert response.status_code == 502
    assert "someone@example.com" not in response.text


def test_explicit_nulls_for_optional_fields_are_accepted(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    created = client.post(
        "/api/waitlist",
        json={
            "email": "nulls@example.com",
            "role": "student",
            "consentVersion": CONSENT_VERSION,
            "utmSource": None,
            "utmTerm": None,
            "website": None,
        },
    )
    assert created.status_code == 200
    done = client.patch(
        "/api/waitlist",
        json={
            "token": created.json()["token"],
            "subjects": ["biology"],
            "otherSubjects": [],
            "examSession": None,
            "phone": None,
            "centreName": None,
            "website": None,
        },
    )
    assert done.status_code == 200
    assert row_for(sm, "nulls@example.com").phone is None


def test_only_free_text_subjects_is_enough_and_filterable_as_other(
    admin: TestClient, sm: sessionmaker[Session]
) -> None:
    token = step1(admin, "free@example.com").json()["token"]
    assert step2(admin, token, subjects=[], otherSubjects=["Film Studies"]).status_code == 200
    join(admin, "listed@example.com", subjects=["biology"])

    row = row_for(sm, "free@example.com")
    assert row.subjects == []
    assert row.other_subjects == ["Film Studies"]
    response = admin.get("/api/admin/waitlist", params={"subject": "other"})
    assert emails(response) == ["free@example.com"]
    assert response.json()["items"][0]["otherSubjects"] == ["Film Studies"]
    csv_rows = parse_csv(admin.get("/api/admin/waitlist/export.csv", params={"subject": "other"}))
    assert csv_rows[0]["other_subjects"] == "Film Studies"


def test_digest_counts_free_text_subjects_as_other(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    for i in range(2):
        token = step1(client, f"free{i}@example.com").json()["token"]
        step2(client, token, subjects=["biology"], otherSubjects=["Film Studies", "Dance"])

    digest(client)

    ((_subject, body),) = provider.sent_team_digests
    assert "Biology: 2" in body
    assert "Other: 2" in body  # once per applicant, not once per entry
    assert "Film Studies" not in body


def test_digest_is_sent_once_per_utc_day(client: TestClient, provider: FakeEmailProvider) -> None:
    step1(client, "one@example.com")

    first = digest(client)
    nothing_new = digest(client)
    step1(client, "two@example.com")  # someone joins after the digest, same UTC day
    same_day = digest(client)

    assert first.json()["sent"] is True
    assert nothing_new.json() == {"newApplicants": 0, "sent": False, "alreadySent": False}
    assert same_day.json() == {"newApplicants": 1, "sent": False, "alreadySent": True}
    assert len(provider.sent_team_digests) == 1


def test_digest_goes_out_again_the_next_utc_day(
    sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    from lemely.web.waitlist_digest import send_waitlist_digest

    repo = WaitlistRepository(sm)
    repo.create(
        email="a@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    evening = datetime(2030, 1, 1, 23, 0, tzinfo=UTC)
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant).values(created_at=evening - timedelta(hours=1))
        )

    assert send_waitlist_digest(repo, provider, now=evening).sent
    repo.create(
        email="b@example.com",
        role="teacher",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant)
            .where(WaitlistApplicant.email == "b@example.com")
            .values(created_at=evening + timedelta(minutes=10))
        )
    same_day = send_waitlist_digest(repo, provider, now=evening + timedelta(minutes=30))
    assert same_day.already_sent
    assert not same_day.sent
    # 01:00 the next UTC day: a new day, and B (missed by the claimed day) is picked up.
    assert send_waitlist_digest(repo, provider, now=evening + timedelta(hours=2)).sent
    assert len(provider.sent_team_digests) == 2


def test_a_failed_send_does_not_use_up_the_day(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    step1(client, "retry@example.com")
    provider.raise_on_send = True
    assert digest(client).status_code == 502

    provider.raise_on_send = False
    retry = digest(client)

    assert retry.json()["sent"] is True
    assert len(provider.sent_team_digests) == 1


def test_a_quiet_day_does_not_use_up_the_day(
    client: TestClient, provider: FakeEmailProvider
) -> None:
    assert digest(client).json()["sent"] is False
    step1(client, "late@example.com")
    assert digest(client).json()["sent"] is True


def test_every_option_shown_to_a_browser_a_day_either_side_is_accepted(
    client: TestClient,
) -> None:
    today = datetime.now(UTC).date()
    shown = {
        value
        for offset in (-1, 0, 1)
        for value, _ in exam_session_options(today + timedelta(days=offset))
    }
    assert shown
    for i, value in enumerate(sorted(shown)):
        token = step1(client, f"tz{i}@example.com").json()["token"]
        assert step2(client, token, examSession=value).status_code == 200, value


def test_a_late_then_early_digest_neither_repeats_nor_misses_an_applicant(
    sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    from lemely.web.waitlist_digest import send_waitlist_digest

    repo = WaitlistRepository(sm)
    repo.create(
        email="a@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    repo.create(
        email="b@example.com",
        role="teacher",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    late = datetime(2030, 1, 1, 23, 50, tzinfo=UTC)
    early = datetime(2030, 1, 2, 0, 10, tzinfo=UTC)
    with sm.begin() as session:
        for email, at in (
            ("a@example.com", late - timedelta(hours=1)),
            ("b@example.com", late + timedelta(minutes=5)),
        ):
            session.execute(
                sa.update(WaitlistApplicant)
                .where(WaitlistApplicant.email == email)
                .values(created_at=at)
            )

    assert send_waitlist_digest(repo, provider, now=late).sent  # sees A only
    assert send_waitlist_digest(repo, provider, now=early).sent  # B arrived after the first

    (_s1, first), (_s2, second) = provider.sent_team_digests
    assert "Students: 1" in first
    assert "Teachers" not in first
    assert "Teachers: 1" in second
    assert "Students" not in second  # A is not repeated


def test_the_first_digest_ever_covers_the_last_24_hours(
    sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    from lemely.web.waitlist_digest import send_waitlist_digest

    repo = WaitlistRepository(sm)
    repo.create(
        email="old@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    now = datetime(2030, 1, 5, 12, 0, tzinfo=UTC)
    with sm.begin() as session:
        session.execute(sa.update(WaitlistApplicant).values(created_at=now - timedelta(hours=30)))

    assert not send_waitlist_digest(repo, provider, now=now).sent


# ---------------------------------------------------------------------------
# Review round: consent, 422 locations, email_confirmed, notes, CSV, body cap
# ---------------------------------------------------------------------------


def test_consent_text_is_owned_by_the_server(client: TestClient, sm: sessionmaker[Session]) -> None:
    ok = step1(client, "c1@example.com")
    assert ok.status_code == 200
    row = row_for(sm, "c1@example.com")
    assert row.consent_version == CURRENT_CONSENT_VERSION
    assert row.consent_text == CONSENT_VERSIONS[CURRENT_CONSENT_VERSION]

    unknown = client.post(
        "/api/waitlist",
        json={"email": "c2@example.com", "role": "student", "consentVersion": "1999-01-v0"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"][0]["loc"] == ["body", "consentVersion"]
    # Wording a client sends is refused outright, never stored.
    sent_text = client.post(
        "/api/waitlist",
        json={
            "email": "c3@example.com",
            "role": "student",
            "consentVersion": CONSENT_VERSION,
            "consentText": "I agree to anything",
        },
    )
    assert sent_text.status_code == 422
    assert count_rows(sm) == 1


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"phone": "12345"}, "phone"),
        ({"subjects": ["nope"]}, "subjects"),
        ({"subjects": [], "otherSubjects": []}, "subjects"),
        ({"examSession": "2020-mj"}, "examSession"),
        ({"otherSubjects": ["a", "b", "c", "d", "e", "f"]}, "otherSubjects"),
        ({"levels": ["igcse"]}, "levels"),
        ({"examBoards": ["ocr"]}, "examBoards"),
    ],
)
def test_step2_422_names_the_camel_case_field(
    client: TestClient, overrides: dict[str, object], field: str
) -> None:
    token = step1(client, "loc@example.com").json()["token"]

    response = step2(client, token, **overrides)

    assert response.status_code == 422
    locs = [error["loc"] for error in response.json()["detail"]]
    assert ["body", field] in [loc[:2] for loc in locs], locs
    phone_error = (
        next(e for e in response.json()["detail"] if e["loc"][:2] == ["body", "phone"])
        if field == "phone"
        else None
    )
    if phone_error is not None:
        assert "Enter a mobile number" in phone_error["msg"]


def test_email_confirmed_is_false_exposed_and_filterable(
    admin: TestClient, sm: sessionmaker[Session]
) -> None:
    seed_queue(admin)
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant)
            .where(WaitlistApplicant.email == "stu1@example.com")
            .values(email_confirmed=True)
        )

    everyone = admin.get("/api/admin/waitlist").json()["items"]
    assert all("emailConfirmed" in item for item in everyone)
    assert next(i for i in everyone if i["email"] == "tea1@example.com")["emailConfirmed"] is False
    confirmed = admin.get("/api/admin/waitlist", params={"emailConfirmed": "true"})
    unconfirmed = admin.get("/api/admin/waitlist", params={"emailConfirmed": "false"})
    assert emails(confirmed) == ["stu1@example.com"]
    assert "stu1@example.com" not in emails(unconfirmed)
    assert unconfirmed.json()["total"] == 4
    one = admin.get(f"/api/admin/waitlist/{confirmed.json()['items'][0]['id']}").json()
    assert one["emailConfirmed"] is True
    assert one["consentVersion"] == CONSENT_VERSION
    rows = parse_csv(admin.get("/api/admin/waitlist/export.csv"))
    by_email = {r["email"]: r for r in rows}
    assert by_email["stu1@example.com"]["email_confirmed"] == "yes"
    assert by_email["tea1@example.com"]["email_confirmed"] == "no"
    assert by_email["tea1@example.com"]["consent_version"] == CONSENT_VERSION


def test_admin_note_keeps_line_breaks(admin: TestClient, sm: sessionmaker[Session]) -> None:
    seed_queue(admin)
    applicant_id = str(row_for(sm, "tea1@example.com").id)

    saved = admin.patch(
        f"/api/admin/waitlist/{applicant_id}",
        json={"adminNote": "Called Tue\r\nNo answer\rTry Thu\n\n  two blank lines above\x00 "},
    )

    note = saved.json()["adminNote"]
    assert note == "Called Tue\nNo answer\nTry Thu\n\n  two blank lines above"
    assert row_for(sm, "tea1@example.com").admin_note == note
    assert (
        admin.patch(
            f"/api/admin/waitlist/{applicant_id}", json={"adminNote": "x" * 2001}
        ).status_code
        == 422
    )
    # The cap counts the stored text: 3000 raw characters that normalise to 1999 are fine.
    fits = admin.patch(
        f"/api/admin/waitlist/{applicant_id}", json={"adminNote": "a\r\n" * 999 + "a"}
    )
    assert fits.status_code == 200
    assert (
        admin.patch(
            f"/api/admin/waitlist/{applicant_id}", json={"adminNote": "a\r\n" * 1100}
        ).status_code
        == 422
    )


def test_csv_quotes_every_cell_and_still_guards_formulas(
    admin: TestClient, sm: sessionmaker[Session]
) -> None:
    join(admin, "q@example.com", full=False)
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant)
            .where(WaitlistApplicant.email == "q@example.com")
            .values(admin_note="=1+1", centre_name="Has, comma")
        )

    raw = admin.get("/api/admin/waitlist/export.csv").content.decode("utf-8-sig")

    for line in raw.strip().split("\r\n"):
        assert line.startswith('"') and line.endswith('"'), line
        assert '","' in line
    row = parse_csv(admin.get("/api/admin/waitlist/export.csv"))[0]
    assert row["admin_note"] == "'=1+1"
    assert row["centre_name"] == "Has, comma"


def test_a_chunked_body_over_the_cap_is_413_and_a_small_one_still_works(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    def chunks(total: int) -> Iterator[bytes]:
        yield b'{"email":"chunk@example.com","role":"student",'
        yield b'"consentVersion":"' + CONSENT_VERSION.encode() + b'","utmSource":"'
        yield b"x" * total
        yield b'"}'

    big = client.post(
        "/api/waitlist", content=chunks(9000), headers={"content-type": "application/json"}
    )
    assert big.status_code == 413
    assert count_rows(sm) == 0

    small = client.post(
        "/api/waitlist", content=chunks(10), headers={"content-type": "application/json"}
    )
    assert small.status_code == 200  # a chunked body under the cap is parsed normally


# ---------------------------------------------------------------------------
# Edge guard, Turnstile
# ---------------------------------------------------------------------------

EDGE = "edge-secret-for-tests"


def test_with_an_edge_secret_a_request_that_skipped_the_worker_is_403(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(sm, clock, provider, limiter_clock, edge_secret=EDGE) as tc:
        body = {"email": "e@example.com", "role": "student", "consentVersion": CONSENT_VERSION}
        for secret_header in ({}, {"X-Lemely-Edge-Secret": "wrong"}):
            assert tc.post("/api/waitlist", json=body, headers=secret_header).status_code == 403
            assert (
                tc.patch(
                    "/api/waitlist",
                    json={"token": "t" * 30, "subjects": ["biology"]},
                    headers=secret_header,
                ).status_code
                == 403
            )
            assert tc.get("/api/waitlist/config", headers=secret_header).status_code == 403
        assert count_rows(sm) == 0
        ok = tc.post("/api/waitlist", json=body, headers={"X-Lemely-Edge-Secret": EDGE})
        assert ok.status_code == 200
        assert (
            tc.get("/api/waitlist/config", headers={"X-Lemely-Edge-Secret": EDGE}).status_code
            == 200
        )


def test_rate_limits_key_on_the_edge_ip_only_when_the_secret_matched(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    def post(tc: TestClient, n: int, headers: dict[str, str]) -> int:
        body = {"email": f"k{n}@example.com", "role": "student", "consentVersion": CONSENT_VERSION}
        return tc.post("/api/waitlist", json=body, headers=headers).status_code

    # Secret configured and sent: each Worker-verified address has its own bucket.
    with build_client(
        sm, clock, provider, limiter_clock, edge_secret=EDGE, per_client_limit=2
    ) as tc:
        a = {"X-Lemely-Edge-Secret": EDGE, "CF-Connecting-IP": "203.0.113.1"}
        b = {"X-Lemely-Edge-Secret": EDGE, "CF-Connecting-IP": "203.0.113.2"}
        assert [post(tc, 1, a), post(tc, 2, a), post(tc, 3, a)] == [200, 200, 429]
        assert post(tc, 4, b) == 200
    # No secret configured: a client-chosen CF-Connecting-IP is never believed, so rotating
    # it does not buy a fresh bucket (everyone is the socket peer).
    with build_client(sm, clock, provider, limiter_clock, per_client_limit=2) as tc:
        spoofed = [post(tc, 10 + i, {"CF-Connecting-IP": f"198.51.100.{i}"}) for i in range(3)]
        assert spoofed == [200, 200, 429]


def test_turnstile_is_skipped_when_not_configured(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    assert step1(client, "dev@example.com").status_code == 200  # no token, no verifier
    assert count_rows(sm) == 1


def test_turnstile_fails_closed_when_configured(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    fake = FakeTurnstile()
    with build_client(sm, clock, provider, limiter_clock, turnstile=fake) as tc:
        assert step1(tc, "t1@example.com").status_code == 403  # no token
        rejected = step1(tc, "t2@example.com", turnstileToken="bad-token")
        assert rejected.status_code == 403
        assert rejected.json()["detail"] == "turnstile_failed"
        assert count_rows(sm) == 0
        ok = step1(tc, "t3@example.com", turnstileToken="good-token")
        assert ok.status_code == 200
        assert ok.json()["status"] == "created"
        assert count_rows(sm) == 1
        assert [token for token, _ in fake.calls] == [
            "bad-token",
            "good-token",
        ]  # none for "no token"
        # Step 2 carries no Turnstile token: the one-time completion token is its proof.
        assert step2(tc, ok.json()["token"]).status_code == 200
    fake_down = FakeTurnstile(ok=False)
    with build_client(sm, clock, provider, limiter_clock, turnstile=fake_down) as tc:
        assert step1(tc, "t4@example.com", turnstileToken="good-token").status_code == 403


def test_a_honeypot_hit_never_reaches_turnstile(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    fake = FakeTurnstile()
    with build_client(sm, clock, provider, limiter_clock, turnstile=fake) as tc:
        assert step1(tc, "bot@example.com", website="x").status_code == 200
    assert fake.calls == []


def test_config_exposes_the_site_key_only_when_turnstile_is_enforced(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(sm, clock, provider, limiter_clock, turnstile_site_key="0xSITE") as tc:
        body = tc.get("/api/waitlist/config").json()
    assert body == {
        "turnstileSiteKey": None,  # a site key without a secret key is not advertised
        "consentVersion": CURRENT_CONSENT_VERSION,
        "consentText": CONSENT_VERSIONS[CURRENT_CONSENT_VERSION],
    }
    with build_client(
        sm, clock, provider, limiter_clock, turnstile=FakeTurnstile(), turnstile_site_key="0xSITE"
    ) as tc:
        assert tc.get("/api/waitlist/config").json()["turnstileSiteKey"] == "0xSITE"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("ok", True), ("denied", False), ("http_500", False), ("timeout", False), ("garbage", False)],
)
def test_cloudflare_turnstile_client_fails_closed(
    monkeypatch: pytest.MonkeyPatch, kind: str, expected: bool
) -> None:
    import httpx

    from lemely.web.turnstile import CloudflareTurnstile

    sent: dict[str, object] = {}

    def fake_post(url: str, *, data: dict[str, str], timeout: float) -> httpx.Response:
        sent.update(url=url, data=data)
        request = httpx.Request("POST", url)
        if kind == "timeout":
            raise httpx.ConnectTimeout("slow", request=request)
        if kind == "http_500":
            return httpx.Response(500, request=request)
        if kind == "garbage":
            return httpx.Response(200, content=b"<html>", request=request)
        return httpx.Response(200, json={"success": kind == "ok"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    assert CloudflareTurnstile("sekret").verify("tok", "203.0.113.5") is expected
    assert sent["data"] == {"secret": "sekret", "response": "tok", "remoteip": "203.0.113.5"}
    assert "siteverify" in str(sent["url"])


# ---------------------------------------------------------------------------
# Digest: DB clock, cursor safety
# ---------------------------------------------------------------------------


class FixedDbClockRepo(WaitlistRepository):
    """A repository whose database clock reads a fixed instant."""

    def __init__(self, sm: sessionmaker[Session], at: datetime) -> None:
        super().__init__(sm)
        self._at = at

    def db_now(self) -> datetime:
        return self._at


def test_digest_window_end_comes_from_the_database_clock(
    sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    from lemely.db.models.waitlist import WaitlistDigestLog
    from lemely.web.waitlist_digest import send_waitlist_digest

    db_clock = datetime(2031, 3, 4, 23, 59, 30, tzinfo=UTC)  # nowhere near this machine's clock
    repo = FixedDbClockRepo(sm, db_clock)
    repo.create(
        email="a@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistApplicant).values(created_at=db_clock - timedelta(minutes=5))
        )

    outcome = send_waitlist_digest(repo, provider)  # no `now`: the DB clock decides

    assert outcome.sent
    with sm() as session:
        log = session.execute(sa.select(WaitlistDigestLog)).scalar_one()
    assert log.window_end == db_clock
    assert str(log.day) == "2031-03-04"  # the UTC day is the DB clock's too


def test_a_failed_send_whose_release_also_fails_does_not_advance_the_cursor(
    sm: sessionmaker[Session], provider: FakeEmailProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lemely.web.waitlist_digest import send_waitlist_digest

    repo = WaitlistRepository(sm)
    repo.create(
        email="a@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    day1 = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)
    with sm.begin() as session:
        session.execute(sa.update(WaitlistApplicant).values(created_at=day1 - timedelta(hours=2)))

    provider.raise_on_send = True

    def broken_release(self: WaitlistRepository, day: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(WaitlistRepository, "release_digest_day", broken_release)
    with pytest.raises(RuntimeError):
        send_waitlist_digest(repo, provider, now=day1)
    monkeypatch.undo()

    assert repo.last_digest_window_end() is None  # nothing was sent, so the cursor did not move
    provider.raise_on_send = False
    next_day = send_waitlist_digest(repo, provider, now=day1 + timedelta(hours=20))
    assert next_day.sent
    assert next_day.new_applicants == 1  # the applicant the failed digest owed is still covered
    assert repo.last_digest_window_end() == day1 + timedelta(hours=20)


def test_a_failed_send_with_a_clean_release_leaves_the_cursor_and_the_day_free(
    sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    from lemely.web.waitlist_digest import send_waitlist_digest

    repo = WaitlistRepository(sm)
    repo.create(
        email="a@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    now = datetime.now(UTC) + timedelta(minutes=1)
    provider.raise_on_send = True
    with pytest.raises(RuntimeError):
        send_waitlist_digest(repo, provider, now=now)
    assert repo.last_digest_window_end() is None
    provider.raise_on_send = False
    assert send_waitlist_digest(repo, provider, now=now).sent


# ---------------------------------------------------------------------------
# An unset GitHub secret renders as "": every waitlist secret must read as unset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_secrets_read_as_unset(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert EdgeSettings(origin_secret=blank).origin_secret is None
    waitlist = WaitlistSettings(
        digest_secret=blank, turnstile_secret_key=blank, turnstile_site_key=blank
    )
    assert waitlist.digest_secret is None
    assert waitlist.turnstile_secret_key is None
    assert waitlist.turnstile_site_key is None

    # And through the environment, which is how deploy.yml delivers them.
    from lemely.runtime.config import Settings

    monkeypatch.setenv("LEMELY_EDGE__ORIGIN_SECRET", blank)
    monkeypatch.setenv("LEMELY_WAITLIST__TURNSTILE_SECRET_KEY", blank)
    monkeypatch.setenv("LEMELY_WAITLIST__DIGEST_SECRET", blank)
    settings = Settings()
    assert settings.edge.origin_secret is None
    assert settings.waitlist.turnstile_secret_key is None
    assert settings.waitlist.digest_secret is None


def test_a_blank_edge_secret_does_not_lock_the_waitlist_out(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(sm, clock, provider, limiter_clock, edge_secret="") as tc:
        assert tc.get("/api/waitlist/config").status_code == 200  # no header, no 403
        assert step1(tc, "blank@example.com").status_code == 200


# ---------------------------------------------------------------------------
# Review round 3: limiter order, IPv6 /64, edge secret rotation, body limit, pending digest
# ---------------------------------------------------------------------------


def test_token_less_and_bad_token_posts_do_not_drain_the_global_budget(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    fake = FakeTurnstile()
    with build_client(
        sm, clock, provider, limiter_clock, turnstile=fake, global_limit=2, per_client_limit=100
    ) as tc:
        refused = [step1(tc, f"x{i}@example.com").status_code for i in range(4)]
        refused += [
            step1(tc, f"y{i}@example.com", turnstileToken="bad").status_code for i in range(4)
        ]
        assert refused == [403] * 8  # never 429: the shared budget was not touched

        good = [
            step1(tc, f"g{i}@example.com", turnstileToken="good-token").status_code
            for i in range(3)
        ]
        assert good == [200, 200, 429]  # only real applicants spend the 2-per-day budget


def test_honeypot_hits_do_not_spend_the_global_budget(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(
        sm, clock, provider, limiter_clock, global_limit=1, per_client_limit=100
    ) as tc:
        assert [step1(tc, f"h{i}@example.com", website="x").status_code for i in range(5)] == [
            200
        ] * 5
        assert [
            step1(tc, "real1@example.com").status_code,
            step1(tc, "real2@example.com").status_code,
        ] == [200, 429]


def test_the_caller_s_own_limit_still_applies_before_turnstile(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    fake = FakeTurnstile()
    with build_client(sm, clock, provider, limiter_clock, turnstile=fake, per_client_limit=2) as tc:
        codes = [step1(tc, f"p{i}@example.com", turnstileToken="bad").status_code for i in range(3)]
    assert codes == [403, 403, 429]
    assert len(fake.calls) == 2  # the throttled third never reached Cloudflare


@pytest.mark.parametrize(
    ("ip", "key"),
    [
        ("203.0.113.9", "203.0.113.9"),
        ("2001:db8:abcd:12::1", "2001:db8:abcd:12::/64"),
        ("2001:db8:abcd:12:ffff:ffff:ffff:ffff", "2001:db8:abcd:12::/64"),
        ("2001:db8:abcd:13::1", "2001:db8:abcd:13::/64"),
        ("::ffff:203.0.113.9", "203.0.113.9"),
        ("unknown", "unknown"),
    ],
)
def test_rate_limit_key_collapses_ipv6_to_its_64(ip: str, key: str) -> None:
    from lemely.web.edge import rate_limit_key

    assert rate_limit_key(ip) == key


def test_one_ipv6_64_shares_a_bucket_and_ipv4_addresses_do_not(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    def post(tc: TestClient, n: int, ip: str) -> int:
        headers = {"X-Lemely-Edge-Secret": EDGE, "CF-Connecting-IP": ip}
        body = {"email": f"v{n}@example.com", "role": "student", "consentVersion": CONSENT_VERSION}
        return tc.post("/api/waitlist", json=body, headers=headers).status_code

    with build_client(
        sm, clock, provider, limiter_clock, edge_secret=EDGE, per_client_limit=2
    ) as tc:
        # A rotating interface id inside one /64 buys no fresh bucket.
        assert [post(tc, i, f"2001:db8:aaaa:1::{i:x}") for i in range(1, 4)] == [200, 200, 429]
        assert post(tc, 10, "2001:db8:aaaa:2::1") == 200  # another /64
        # IPv4 stays per address.
        assert [post(tc, 20, "198.51.100.1"), post(tc, 21, "198.51.100.2")] == [200, 200]


PREVIOUS = "previous-edge-secret"


def test_the_edge_guard_accepts_the_current_and_the_previous_secret_and_nothing_else(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(
        sm, clock, provider, limiter_clock, edge_secret=EDGE, edge_previous=PREVIOUS
    ) as tc:

        def config(header: dict[str, str]) -> int:
            return tc.get("/api/waitlist/config", headers=header).status_code

        assert config({"X-Lemely-Edge-Secret": EDGE}) == 200
        assert config({"X-Lemely-Edge-Secret": PREVIOUS}) == 200
        assert config({"X-Lemely-Edge-Secret": "something-else"}) == 403
        assert config({"X-Lemely-Edge-Secret": EDGE + "x"}) == 403
        assert config({"X-Lemely-Edge-Secret": ""}) == 403
        assert config({}) == 403


@pytest.mark.parametrize("current", [EDGE, None])
def test_an_empty_previous_secret_never_matches_an_empty_header(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
    current: str | None,
) -> None:
    with build_client(
        sm, clock, provider, limiter_clock, edge_secret=current, edge_previous=""
    ) as tc:
        empty = tc.get("/api/waitlist/config", headers={"X-Lemely-Edge-Secret": ""})
        absent = tc.get("/api/waitlist/config")
        if current is None:
            assert empty.status_code == absent.status_code == 200  # no secret: the guard is off
        else:
            assert empty.status_code == absent.status_code == 403


def test_a_previous_secret_alone_still_arms_the_guard(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(
        sm, clock, provider, limiter_clock, edge_secret=None, edge_previous=PREVIOUS
    ) as tc:
        assert tc.get("/api/waitlist/config").status_code == 403
        assert (
            tc.get("/api/waitlist/config", headers={"X-Lemely-Edge-Secret": PREVIOUS}).status_code
            == 200
        )


def test_blank_previous_secret_reads_as_unset() -> None:
    assert EdgeSettings(origin_secret_previous="  ").origin_secret_previous is None


def test_the_body_limit_covers_patch_a_lying_length_and_leaves_other_routes_alone(
    client: TestClient,
) -> None:
    over = '{"token":"' + "t" * 9000 + '"}'
    assert (
        client.patch(
            "/api/waitlist", content=over, headers={"content-type": "application/json"}
        ).status_code
        == 413
    )
    # A body longer than its declared length is cut off as it is read, not trusted.
    lying = client.post(
        "/api/waitlist",
        content=b'{"email":"a@b.co","pad":"' + b"x" * 9000 + b'"}',
        headers={"content-type": "application/json", "content-length": "20"},
    )
    assert lying.status_code == 413
    assert client.get("/api/waitlist/config").status_code == 200  # GET is not capped
    # Another route's declared size is not this middleware's business.
    assert (
        client.post(
            "/api/client-errors", content=b"{}", headers={"content-length": "2"}
        ).status_code
        != 413
    )


def test_a_pending_claim_is_not_reported_as_sent_and_is_taken_over_after_its_lease(
    sm: sessionmaker[Session], provider: FakeEmailProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lemely.db.models.waitlist import WaitlistDigestLog
    from lemely.web.waitlist_digest import send_waitlist_digest

    repo = WaitlistRepository(sm)
    repo.create(
        email="a@example.com",
        role="student",
        consent_version=CONSENT_VERSION,
        consent_text=CONSENT,
        utm={},
    )
    day1 = datetime.now(UTC) + timedelta(minutes=1)

    provider.raise_on_send = True

    def broken_release(self: WaitlistRepository, day: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(WaitlistRepository, "release_digest_day", broken_release)
    with pytest.raises(RuntimeError):
        send_waitlist_digest(repo, provider, now=day1)
    monkeypatch.undo()
    provider.raise_on_send = False

    # The claim is still there, unconfirmed. An immediate retry must not say "already sent".
    retry = send_waitlist_digest(repo, provider, now=day1 + timedelta(seconds=30))
    assert retry.pending is True
    assert retry.already_sent is False
    assert retry.sent is False
    assert provider.sent_team_digests == []

    # Once the claim's lease has run out, the retry takes it over, sends, and moves the cursor.
    with sm.begin() as session:
        session.execute(
            sa.update(WaitlistDigestLog).values(
                sent_at=sa.func.now() - sa.text("interval '10 minutes'")
            )
        )
    taken = send_waitlist_digest(repo, provider, now=day1 + timedelta(minutes=10))
    assert taken.sent is True
    assert len(provider.sent_team_digests) == 1
    assert repo.last_digest_window_end() == day1 + timedelta(minutes=10)
    # And now the day really is sent.
    again = send_waitlist_digest(repo, provider, now=day1 + timedelta(minutes=11))
    assert again.already_sent is True or again.new_applicants == 0


def test_the_digest_endpoint_answers_503_for_a_pending_claim(
    client: TestClient, sm: sessionmaker[Session], provider: FakeEmailProvider
) -> None:
    from lemely.db.models.waitlist import WaitlistDigestLog

    step1(client, "p@example.com")
    with sm.begin() as session:  # a claim today that never finished
        session.add(WaitlistDigestLog(day=datetime.now(UTC).date(), new_applicants=1))

    response = digest(client)

    assert response.status_code == 503
    assert response.json()["detail"] == "digest_pending"
    assert provider.sent_team_digests == []


def test_junk_token_patches_do_not_drain_the_global_budget(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(
        sm, clock, provider, limiter_clock, global_limit=3, per_client_limit=1000
    ) as tc:
        junk = [step2(tc, f"junk-{i:04d}".ljust(30, "x")).status_code for i in range(10)]
        assert junk == [400] * 10  # ten junk tokens against a budget of three: never a 429

        # The budget is intact for real applicants, and a valid PATCH still completes.
        first = step1(tc, "real1@example.com")
        assert first.status_code == 200
        assert step2(tc, first.json()["token"]).status_code == 200
        assert step1(tc, "real2@example.com").status_code == 200
        assert step1(tc, "real3@example.com").status_code == 200
        assert step1(tc, "real4@example.com").status_code == 429  # 3 step-1s spent it, nothing else


def test_patch_is_still_limited_per_caller(
    sm: sessionmaker[Session],
    clock: Clock,
    provider: FakeEmailProvider,
    limiter_clock: LimiterClock,
) -> None:
    with build_client(sm, clock, provider, limiter_clock, per_client_limit=2) as tc:
        codes = [step2(tc, f"junk-{i}".ljust(30, "x")).status_code for i in range(3)]
    assert codes == [400, 400, 429]
