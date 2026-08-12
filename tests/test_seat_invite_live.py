"""Live E2E: school_admin invites a student via SeatService → student logs in.

Proves the seat-invite → login path that a real school onboarding uses:

1. A school_admin User, a School row, and a SchoolMembership are seeded
   directly into the live Supabase Postgres.
2. SeatService.invite_student() is called — it creates the student account
   in GoTrue, mirrors a ``public.users`` row, and allocates a seat row, all
   in the same live database.
3. The returned temporary password is used to log in via AuthService.login().
4. The resulting access token is decoded and the claim ``app_role`` is
   asserted to equal ``student``.

Skip guards mirror test_auth_live.py exactly: skip (never fail) when any of
the Supabase service-role key, anon key, GoTrue endpoint, or local Postgres is
absent or unreachable.

Cleanup runs in a ``finally`` block that deletes every seeded row (admin,
school, school_membership, student user, seat) plus the GoTrue account, so
repeated runs leave the DB clean.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.auth.mirror import DbUserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token
from lemely.db.models import School, SchoolMembership, User
from lemely.db.models.enums import MembershipRole, Role
from lemely.db.seat_repo import SeatService
from lemely.db.session import dispose_engine, get_sessionmaker, session_scope
from lemely.runtime.config import Settings
from lemely.web.deps import AuthServiceStudentCreator

# ---------------------------------------------------------------------------
# Skip-guard helpers (mirrors test_auth_live.py exactly)
# ---------------------------------------------------------------------------


def _gotrue_reachable(url: str) -> bool:
    try:
        resp = httpx.get(f"{url.rstrip('/')}/auth/v1/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return resp.status_code < 500


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


def _live_settings() -> Settings | None:
    service_key = os.environ.get("LEMELY_SUPABASE__SERVICE_ROLE_KEY")
    anon_key = os.environ.get("LEMELY_SUPABASE__ANON_KEY")
    if not service_key or not anon_key:
        return None
    settings = Settings()
    return settings.model_copy(
        update={
            "supabase": settings.supabase.model_copy(
                update={
                    "service_role_key": SecretStr(service_key),
                    "anon_key": SecretStr(anon_key),
                }
            )
        }
    )


# ---------------------------------------------------------------------------
# Live AuthService fixture (identical construction to test_auth_live.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def live_auth_service() -> AuthService:
    settings = _live_settings()
    if settings is None:
        pytest.skip("Supabase service-role/anon keys not set in environment")
    if not _gotrue_reachable(settings.supabase.url):
        pytest.skip("local GoTrue not reachable")
    if not _server_reachable(settings.database.url):
        pytest.skip("local Postgres not reachable")

    dispose_engine()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(),
    )
    return AuthService(
        gotrue=HttpGoTrueBackend(settings),
        mirror=DbUserMirror(settings),
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _cleanup_rows(settings: Settings, row_ids: dict[str, uuid.UUID | None]) -> None:
    """Delete seeded rows from the live DB in FK-safe order."""
    with session_scope(settings) as session:
        # seats are FK → users and schools; delete first
        if row_ids.get("seat_id"):
            session.execute(
                text("DELETE FROM seats WHERE id = :id"),
                {"id": row_ids["seat_id"]},
            )
        # school_memberships are FK → schools and users
        if row_ids.get("school_id") and row_ids.get("admin_id"):
            session.execute(
                text("DELETE FROM school_memberships WHERE school_id = :sid AND user_id = :uid"),
                {"sid": row_ids["school_id"], "uid": row_ids["admin_id"]},
            )
        if row_ids.get("school_id"):
            session.execute(
                text("DELETE FROM schools WHERE id = :id"),
                {"id": row_ids["school_id"]},
            )
        if row_ids.get("student_id"):
            session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": row_ids["student_id"]},
            )
        if row_ids.get("admin_id"):
            session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": row_ids["admin_id"]},
            )


def _delete_gotrue_user(settings: Settings, user_id: uuid.UUID) -> None:
    """Best-effort: delete a GoTrue account via the service-role admin API."""
    import contextlib

    service_key = settings.supabase.service_role_key.get_secret_value()
    url = f"{settings.supabase.url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    with contextlib.suppress(Exception):
        httpx.delete(
            url,
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=5.0,
        )


# ---------------------------------------------------------------------------
# The E2E test
# ---------------------------------------------------------------------------


def test_seat_invite_student_can_login(live_auth_service: AuthService) -> None:
    """seat-invite → login → token carries app_role=student.

    Everything runs against the single live Supabase Postgres so FK constraints
    between seats → users are satisfied.

    Steps:
    1. Seed a school_admin User + School + SchoolMembership directly.
    2. Build a SeatService against the same live DB with a real
       AuthServiceStudentCreator that calls live_auth_service.signup().
    3. SeatService.invite_student() creates the GoTrue account, mirrors the
       user row, and allocates a seat — all in the live DB.
    4. AuthService.login() with the temporary password returns a token.
    5. Decode the token and assert app_role == "student".
    6. Cleanup all created rows and the GoTrue account in a finally block.
    """
    settings = _live_settings()
    assert settings is not None  # already checked by live_auth_service fixture

    # IDs collected for cleanup
    row_ids: dict[str, uuid.UUID | None] = {
        "admin_id": None,
        "school_id": None,
        "student_id": None,
        "seat_id": None,
    }

    admin_id = uuid.uuid4()
    school_id = uuid.uuid4()
    row_ids["admin_id"] = admin_id
    row_ids["school_id"] = school_id

    # Seed admin user + school + membership directly into the live DB
    with session_scope(settings) as session:
        session.add(User(id=admin_id, email=f"{admin_id}@example.com", role=Role.school_admin))
        session.add(School(id=school_id, name="Live Invite Test School", seat_quota=5))
        session.add(
            SchoolMembership(
                school_id=school_id,
                user_id=admin_id,
                membership_role=MembershipRole.school_admin,
            )
        )

    # SeatService wired to the live DB using the real student creator
    creator = AuthServiceStudentCreator(live_auth_service)
    service = SeatService(get_sessionmaker(settings), creator)

    student_email = f"seat-live-{uuid.uuid4().hex[:10]}@example.com"
    temp_password = f"TmpPw-{uuid.uuid4().hex[:16]}"

    try:
        result = service.invite_student(admin_id, school_id, student_email, temp_password)
        row_ids["student_id"] = result.user_id
        row_ids["seat_id"] = result.seat_id

        # The student account now exists in GoTrue + mirrored. Log in.
        login = live_auth_service.login(student_email, temp_password)
        assert login.user_id == result.user_id

        # Decode and assert role.
        claims = decode_token(login.access_token, settings)
        assert claims.app_role == "student", f"expected student, got {claims.app_role!r}"
        assert claims.sub == str(result.user_id)
    finally:
        _cleanup_rows(settings, row_ids)
        if row_ids.get("student_id"):
            _delete_gotrue_user(settings, row_ids["student_id"])
