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

2. **Parent OTP E2E** (hermetic): OTP request → code recovery → verify →
   parent token → hit /api/student/overview → assert 403 (parent locked out).
   This proves the OTP-minted token flows through get_auth_context RBAC end
   to end.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.auth.otp import OtpChannel, OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token, mint_access_token
from lemely.db.models.enums import Role
from lemely.db.seat_repo import SeatService
from lemely.io.history_store import HistoryStore
from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import (
    get_auth_service,
    get_history_store,
    get_seat_service,
    get_settings,
    reset_singletons,
)

if TYPE_CHECKING:
    from pathlib import Path

from tests.auth_fakes import FakeGoTrueBackend, FakeUserMirror

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
# §6  Parent OTP E2E: request OTP → verify → token → assert 403 on student
#     route. Proves the OTP-minted token flows through get_auth_context RBAC.
# ---------------------------------------------------------------------------


@pytest.fixture
def otp_context(settings: Settings) -> Iterator[tuple[TestClient, AuthService]]:
    """App wired with the full auth stack (FakeGoTrue) plus stub SeatService."""
    mirror = FakeUserMirror()
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
    )

    store = HistoryStore(settings.paths.output_dir / "history")
    stub_seat_service = MagicMock(spec=SeatService)
    stub_seat_service.list_admin_schools.return_value = []

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_history_store] = lambda: store
    app.dependency_overrides[get_seat_service] = lambda: stub_seat_service

    client = TestClient(app)
    try:
        yield client, service
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def test_parent_otp_e2e_locked_out_of_student_route(
    otp_context: tuple[TestClient, AuthService], settings: Settings
) -> None:
    """Full OTP flow: request → recover code → verify → use token → assert 403.

    This covers:
    * /api/auth/otp/request returns 200 and status=sent
    * OTP code is valid and /api/auth/otp/verify returns a token with role=parent
    * The minted token is accepted by the JWT middleware (no 401)
    * get_auth_context RBAC correctly rejects parent from /api/student/overview (403)
    """
    client, service = otp_context
    phone = "+201234599999"

    # Step 1: request OTP
    req_resp = client.post("/api/auth/otp/request", json={"phone": phone})
    assert req_resp.status_code == 200, req_resp.text
    assert req_resp.json()["status"] == "sent"

    # Step 2: recover code via test introspection (mirrors test_auth_router.py)
    code = service._otp_store._challenges[(OtpChannel.phone, phone)].code

    # Step 3: verify OTP → get parent token
    verify_resp = client.post("/api/auth/otp/verify", json={"phone": phone, "code": code})
    assert verify_resp.status_code == 200, verify_resp.text
    parent_token = verify_resp.json()["accessToken"]

    # Confirm the token carries role=parent
    claims = decode_token(parent_token, settings)
    assert claims.app_role == "parent"

    # Step 4: use parent token against a student-only route → must be 403
    protected_resp = client.get(
        "/api/student/overview",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert protected_resp.status_code == 403, protected_resp.text
