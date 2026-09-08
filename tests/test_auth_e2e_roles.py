"""End-to-end auth acceptance tests for Phase 1 — all 5 roles.

Two test groups live here:

1. **5-role RBAC outcome matrix** (hermetic, no network, minted tokens).
   For every role we assert:
   * the one representative ALLOWED route returns 200 (or N/A for parent who
     has no allowed routes yet),
   * every DENIED route returns 403.

   Routes covered:
   ┌──────────────────┬──────────────┬──────────────────┬───────────────────┐
   │ Role             │ ALLOWED      │ DENIED 1         │ DENIED 2          │
   ├──────────────────┼──────────────┼──────────────────┼───────────────────┤
   │ student          │ /student/... │ /api/papers      │ /api/school/seats │
   │ teacher          │ /api/papers  │ /student/...     │ /api/school/seats │
   │ school_admin     │ /api/papers  │ /student/...     │ /api/school/seats │
   │                  │ + /sch/seats │                  │ (allowed, see §3) │
   │ platform_admin   │ /api/papers  │ /student/...     │ /api/school/seats │
   │ parent           │ (none yet)   │ /api/papers      │ /student/...      │
   │                  │              │ /api/school/seats│                   │
   └──────────────────┴──────────────┴──────────────────┴───────────────────┘

   The school_admin 200 on /api/school/seats needs a live SeatService, so it
   is tested with a fake SeatService override that returns an empty list (the
   authz check passes, the service is never called with real data).  The
   no-super-role invariant (D1.6) is asserted: platform_admin is 403 there.

2. **Parent-invite E2E** (Postgres-backed, spec §4): a student's reusable
   parent code → email-code request → verify → parent signup → the parent is
   genuinely linked to the child → hit /api/student/overview → assert 403
   (parent locked out). This proves the invite-minted token flows through
   get_auth_context RBAC end to end, and that the link it carries is real,
   not just an asserted role. Retired phone-OTP routes (``/auth/otp/request``,
   ``/auth/otp/verify``) are gone; ``AuthService.request_otp``/``verify_otp``
   stay in the codebase as a kept seam but are not exercised here.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.auth.cooldown import CooldownStore
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token, mint_access_token
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ParentLinkService
from lemely.db.seat_repo import SeatService
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import DatabaseSettings, Settings
from lemely.web import create_app
from lemely.web.deps import (
    get_auth_service,
    get_history_store,
    get_invite_service,
    get_seat_service,
    get_settings,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
    reset_singletons,
)

if TYPE_CHECKING:
    from pathlib import Path

from tests.auth_fakes import FakeEmailProvider, FakeGoTrueBackend, FakeUserMirror

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = Settings()
    data = base.model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    return Settings.model_validate(data)


@pytest.fixture
def app_with_overrides(settings: Settings) -> Iterator[TestClient]:
    """App wired with a real HistoryStore and a stub SeatService.

    The stub SeatService returns an empty school list for GET /api/school/seats
    so the route reaches 200 for school_admin without a live database.
    """
    store = HistoryStore(settings.paths.output_dir / "history")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_history_store] = lambda: store

    # Stub SeatService: list_admin_schools returns [] (no DB needed for RBAC test)
    stub_seat_service = MagicMock(spec=SeatService)
    stub_seat_service.list_admin_schools.return_value = []
    app.dependency_overrides[get_seat_service] = lambda: stub_seat_service

    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint(role: Role, settings: Settings) -> str:
    return mint_access_token(
        user_id=uuid.uuid4(),
        settings=settings,
        app_role=role.value,
        provider="email",
    )


# ---------------------------------------------------------------------------
# §1  student — allowed: /api/student/overview; denied: /api/papers,
#              /api/school/seats
# ---------------------------------------------------------------------------


def test_student_reaches_student_overview(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    token = _mint(Role.student, settings)
    resp = app_with_overrides.get("/api/student/overview", headers=_bearer(token))
    assert resp.status_code == 200, resp.text


def test_student_denied_papers(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.student, settings)
    resp = app_with_overrides.get("/api/papers", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


def test_student_denied_school_seats(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.student, settings)
    resp = app_with_overrides.get("/api/school/seats", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# §2  teacher — allowed: /api/papers; denied: /api/student/overview,
#               /api/school/seats
# ---------------------------------------------------------------------------


def test_teacher_reaches_papers(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.teacher, settings)
    resp = app_with_overrides.get("/api/papers", headers=_bearer(token))
    assert resp.status_code == 200, resp.text


def test_teacher_denied_student_overview(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    token = _mint(Role.teacher, settings)
    resp = app_with_overrides.get("/api/student/overview", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


def test_teacher_denied_school_seats(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.teacher, settings)
    resp = app_with_overrides.get("/api/school/seats", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# §3  school_admin — allowed: /api/papers AND /api/school/seats;
#                   denied: /api/student/overview
# ---------------------------------------------------------------------------


def test_school_admin_reaches_papers(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.school_admin, settings)
    resp = app_with_overrides.get("/api/papers", headers=_bearer(token))
    assert resp.status_code == 200, resp.text


def test_school_admin_reaches_school_seats(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    """school_admin may list seats (stub returns []); confirms authz passes."""
    token = _mint(Role.school_admin, settings)
    resp = app_with_overrides.get("/api/school/seats", headers=_bearer(token))
    assert resp.status_code == 200, resp.text


def test_school_admin_denied_student_overview(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    token = _mint(Role.school_admin, settings)
    resp = app_with_overrides.get("/api/student/overview", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


def test_invite_malformed_school_id_is_422_not_500(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    """Acceptance-review M1: a non-UUID schoolId from an authed admin is a clean 422.

    ``InviteStudentRequestDTO.schoolId`` is typed ``uuid.UUID``; Pydantic rejects a
    malformed value at parse time (after the school_admin authz passes) rather than
    letting it reach ``SeatService`` and raise an unhandled ``ValueError`` → 500.
    """
    token = _mint(Role.school_admin, settings)
    resp = app_with_overrides.post(
        "/api/school/seats/invite",
        headers=_bearer(token),
        json={"schoolId": "not-a-uuid", "email": "new@student.local"},
    )
    assert resp.status_code == 422, resp.text


def test_revoke_malformed_seat_id_is_422_not_500(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    """Acceptance-review M1: a non-UUID seat_id path param is a clean 422, not 500.

    The ``{seat_id}`` path parameter is declared ``uuid.UUID`` so FastAPI rejects a
    malformed segment before the handler runs.
    """
    token = _mint(Role.school_admin, settings)
    resp = app_with_overrides.post(
        "/api/school/seats/not-a-uuid/revoke",
        headers=_bearer(token),
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# §4  platform_admin — allowed: /api/papers; denied: /api/student/overview,
#                      /api/school/seats (D1.6 no-super-role invariant)
# ---------------------------------------------------------------------------


def test_platform_admin_reaches_papers(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.platform_admin, settings)
    resp = app_with_overrides.get("/api/papers", headers=_bearer(token))
    assert resp.status_code == 200, resp.text


def test_platform_admin_denied_student_overview(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    token = _mint(Role.platform_admin, settings)
    resp = app_with_overrides.get("/api/student/overview", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


def test_platform_admin_denied_school_seats_no_super_role(
    app_with_overrides: TestClient, settings: Settings
) -> None:
    """D1.6: platform_admin has NO super-role; /api/school/seats is 403 for them."""
    token = _mint(Role.platform_admin, settings)
    resp = app_with_overrides.get("/api/school/seats", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# §5  parent — no routes yet (Phase 3); every existing route must be 403
# ---------------------------------------------------------------------------


def test_parent_denied_student_overview(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.parent, settings)
    resp = app_with_overrides.get("/api/student/overview", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


def test_parent_denied_papers(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.parent, settings)
    resp = app_with_overrides.get("/api/papers", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


def test_parent_denied_school_seats(app_with_overrides: TestClient, settings: Settings) -> None:
    token = _mint(Role.parent, settings)
    resp = app_with_overrides.get("/api/school/seats", headers=_bearer(token))
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# §6  Parent-invite E2E (spec §4): request-code → verify-code → signup →
#     assert a genuine parent-child link → assert 403 on a student route.
#     Proves the invite-minted token flows through get_auth_context RBAC.
# ---------------------------------------------------------------------------
#
# Postgres-backed rather than the fully in-memory ``app_with_overrides``
# above, mirroring ``tests/test_auth_router.py``'s ``parent_context`` fixture:
# completing ``/auth/parent/signup`` redeems the invite through
# :meth:`~lemely.db.invite_repo.InviteService.redeem`, which inserts a real
# ``parent_child_links`` row via
# :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session` — a fake
# invite service could not prove that link is real, only that a token with
# ``role=parent`` came back. GoTrue itself stays in-memory
# (:class:`~tests.auth_fakes.FakeGoTrueBackend`): this test's RBAC assertion
# does not depend on a live Supabase Auth server, only on genuine Postgres
# rows for the invite/link tables, so a throwaway per-test database (skipped,
# never failed, when local Postgres is unreachable — see
# :func:`_server_reachable`) is enough.


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """Throwaway Postgres database for the parent-invite E2E test.

    Duplicated (rather than shared via conftest) matching the same
    per-file-duplication convention ``tests/test_auth_router.py`` documents
    for its own copy of this fixture.
    """
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_student(sm: sessionmaker[Session], display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(id=uid, email=f"{uid}@example.com", role=Role.student, display_name=display_name)
        )
    return uid


def _invite_service(sm: sessionmaker[Session]) -> InviteService:
    return InviteService(sm, ClassService(sm), ParentLinkService(sm))


class PgBackedUserMirror(FakeUserMirror):
    """A :class:`~tests.auth_fakes.FakeUserMirror` that also writes real ``users`` rows.

    Needed because the parent-signup flow redeems through the **real**,
    Postgres-backed :class:`~lemely.db.invite_repo.InviteService` this
    fixture wires, and
    :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session` inserts a
    genuine ``parent_child_links`` row whose ``parent_id`` foreign-keys to
    ``users.id`` in that same database — a plain, in-memory-only
    :class:`~tests.auth_fakes.FakeUserMirror` is invisible to Postgres and
    cannot satisfy that constraint. Mirrors
    ``tests/test_auth_router.py``'s class of the same name exactly.
    """

    def __init__(self, sessionmaker_: sessionmaker[Session]) -> None:
        super().__init__()
        self._sessionmaker = sessionmaker_

    def upsert(
        self,
        user_id: uuid.UUID,
        email: str,
        role: Role,
        phone: str | None = None,
        display_name: str | None = None,
        terms_accepted_at: datetime | None = None,
    ) -> None:
        super().upsert(
            user_id,
            email=email,
            role=role,
            phone=phone,
            display_name=display_name,
            terms_accepted_at=terms_accepted_at,
        )
        with self._sessionmaker.begin() as session:
            existing = session.get(User, user_id)
            if existing is None:
                session.add(
                    User(
                        id=user_id,
                        email=email,
                        role=role,
                        phone=phone,
                        display_name=display_name,
                        terms_accepted_at=terms_accepted_at,
                    )
                )
            else:
                existing.email = email
                existing.role = role
                if phone is not None:
                    existing.phone = phone
                if display_name is not None:
                    existing.display_name = display_name
                if terms_accepted_at is not None:
                    existing.terms_accepted_at = terms_accepted_at

    def mark_email_verified(self, user_id: uuid.UUID, *, verified_at: datetime) -> None:
        super().mark_email_verified(user_id, verified_at=verified_at)
        with self._sessionmaker.begin() as session:
            existing = session.get(User, user_id)
            if existing is not None:
                existing.email_verified_at = verified_at


@pytest.fixture
def parent_invite_context(
    pg_sessionmaker: sessionmaker[Session], settings: Settings
) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """App wired with FakeGoTrue plus a real, Postgres-backed InviteService.

    Same stub SeatService as :func:`app_with_overrides`; the OTP store still
    backs the parent-signup email code (spec §4's channel, not the retired
    phone one) and post-signup email verification, exactly as
    :class:`~lemely.auth.service.AuthService` itself requires it.

    ``get_signup_and_reset_cooldown_store`` is overridden to a fresh,
    in-memory :class:`~lemely.auth.cooldown.CooldownStore` for the same
    reason ``tests/test_auth_router.py``'s ``_override_cooldowns`` gives:
    left unoverridden it falls back to the real ``DbCooldownStore`` (spec
    §4.4), which stamps the dev database's ``auth_cooldowns`` table on every
    ``/auth/parent/request-code`` call — a stamp durable across runs, not
    reset by this fixture's own throwaway ``pg_sessionmaker`` database, so a
    prior run's call for the same email would otherwise throttle this one
    with a stray 429.
    """
    mirror = PgBackedUserMirror(pg_sessionmaker)
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(42),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
    )
    service = AuthService(
        gotrue=FakeGoTrueBackend(),
        mirror=mirror,
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
        email=FakeEmailProvider(),
    )

    store = HistoryStore(settings.paths.output_dir / "history")
    stub_seat_service = MagicMock(spec=SeatService)
    stub_seat_service.list_admin_schools.return_value = []
    signup_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC),
        min_seconds=settings.auth.signup_and_reset_cooldown_seconds,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    app.dependency_overrides[get_invite_service] = lambda: _invite_service(pg_sessionmaker)
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_seat_service] = lambda: stub_seat_service
    app.dependency_overrides[get_signup_and_reset_cooldown_store] = lambda: signup_cooldown

    client = TestClient(app)
    try:
        yield client, pg_sessionmaker
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def test_parent_invite_e2e_locked_out_of_student_route(
    parent_invite_context: tuple[TestClient, sessionmaker[Session]], settings: Settings
) -> None:
    """Full parent-invite flow: request-code → verify-code → signup → use token → assert 403.

    This covers:
    * a student's reusable parent code (``InviteService.get_or_create_parent_code``)
      opens the flow
    * /api/auth/parent/request-code returns 200 and a devCode (the mock email
      provider does not deliver out of band, D3.16)
    * /api/auth/parent/verify-code exchanges the code for a proofToken
    * /api/auth/parent/signup returns a token with role=parent
    * the redeemed invite produced a genuine parent_child_links row, not just
      an asserted role
    * the minted token is accepted by the JWT middleware (no 401)
    * get_auth_context RBAC correctly rejects parent from /api/student/overview (403)
    """
    client, sm = parent_invite_context
    student = _seed_student(sm, display_name="Student")
    invite = _invite_service(sm).get_or_create_parent_code(student)
    email = "new-parent@example.com"

    # Step 1: request the parent-signup email code.
    request_resp = client.post(
        "/api/auth/parent/request-code",
        json={"email": email, "inviteCode": invite.code},
    )
    assert request_resp.status_code == 200, request_resp.text
    dev_code = request_resp.json()["devCode"]
    assert dev_code is not None

    # Step 2: verify the code → proof token.
    verify_resp = client.post(
        "/api/auth/parent/verify-code",
        json={"email": email, "inviteCode": invite.code, "code": dev_code},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    proof_token = verify_resp.json()["proofToken"]

    # Step 3: complete signup → parent token.
    signup_resp = client.post(
        "/api/auth/parent/signup",
        json={
            "proofToken": proof_token,
            "password": "pw-123456",
            "acceptedTerms": True,
            "displayName": "New Parent",
        },
    )
    assert signup_resp.status_code == 200, signup_resp.text
    body = signup_resp.json()
    assert body["role"] == "parent"
    parent_token = body["accessToken"]

    # Confirm the token carries role=parent
    claims = decode_token(parent_token, settings)
    assert claims.app_role == "parent"

    # Confirm the invite actually linked the parent to the child.
    children = ParentLinkService(sm).linked_children(uuid.UUID(body["userId"]))
    assert [c.child_id for c in children] == [student]

    # Step 4: use parent token against a student-only route → must be 403.
    protected_resp = client.get("/api/student/overview", headers=_bearer(parent_token))
    assert protected_resp.status_code == 403, protected_resp.text
