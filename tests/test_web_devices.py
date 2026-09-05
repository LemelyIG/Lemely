"""HTTP-layer tests for the device surfaces G-10 and G-11 (P5.7 chunk A, D5.12).

Two routes' worth of wiring, proven hermetically against a recording stand-in for
:class:`~lemely.db.device_repo.DeviceRegistry` — the registry's own Postgres
guarantees (the cap, the eviction order, the refusal writing nothing) are proven
in ``tests/test_device_repo.py`` and are not re-proven here. What this file pins
is the part only the HTTP layer can get wrong:

* the **409 challenge** body — its shape, that it carries no token, and that it
  names the device a confirmed retry would actually evict;
* that a confirmed retry is the one that is allowed to evict;
* that ``/api/me/devices`` is scoped to the token's ``sub`` with no user id
  anywhere on the router, is role-agnostic, and marks the caller's own device;
* that signing out an unknown, malformed, or someone else's device answers
  ``removed: false`` rather than a 404 that would confirm the id exists.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.auth.cooldown import CooldownStore
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.device_repo import (
    MAX_DEVICES,
    DeviceLimitReachedError,
    DeviceRegistration,
    DeviceRegistry,
    DeviceRow,
)
from lemely.db.models.enums import Role
from lemely.runtime.config import Settings
from lemely.web.app import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_auth_service,
    get_device_registry,
    get_resend_verification_cooldown_store,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
    reset_singletons,
)
from tests.auth_fakes import FakeGoTrueBackend, FakeUserMirror

if TYPE_CHECKING:
    from collections.abc import Iterator

BASE = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


class StubRegistry(DeviceRegistry):
    """In-memory stand-in with the real registry's contract, minus Postgres.

    Deliberately not a `Mock`: the 409 body is built from real
    :class:`DeviceRow` values, so a field the router forgets to project shows up
    as a wrong response rather than as an attribute that silently exists.
    """

    def __init__(self, rows: list[DeviceRow] | None = None) -> None:
        self.rows: list[DeviceRow] = list(rows or [])
        self.registered: list[bool] = []  # one entry per register_login: allow_eviction
        self.revoked: list[tuple[str, str]] = []

    def register_login(  # type: ignore[override]
        self,
        user_id: uuid.UUID | str,
        *,
        client_device_id: str | None = None,
        user_agent: str | None = None,
        device_label: str | None = None,
        allow_eviction: bool = True,
        now: datetime | None = None,
    ) -> DeviceRegistration:
        self.registered.append(allow_eviction)
        if len(self.rows) >= MAX_DEVICES and not allow_eviction:
            raise DeviceLimitReachedError(list(self.rows))
        evicted = []
        if len(self.rows) >= MAX_DEVICES:
            evicted = [self.rows.pop().device_id]
        fresh = _row(f"device-{len(self.rows)}")
        self.rows.insert(0, fresh)
        return DeviceRegistration(
            session_id=fresh.device_id, reused=False, evicted_session_ids=evicted
        )

    def active_devices(self, user_id: uuid.UUID | str) -> list[DeviceRow]:
        return list(self.rows)

    def revoke(self, user_id: uuid.UUID | str, session_id: uuid.UUID | str) -> bool:
        self.revoked.append((str(user_id), str(session_id)))
        uuid.UUID(str(session_id))  # the real registry rejects a malformed id this way
        remaining = [r for r in self.rows if str(r.device_id) != str(session_id)]
        removed = len(remaining) != len(self.rows)
        self.rows = remaining
        return removed

    def is_session_live(self, session_id: uuid.UUID | str) -> bool:
        return any(str(r.device_id) == str(session_id) for r in self.rows)


def _row(label: str, *, minutes_ago: int = 0, user_agent: str | None = "Firefox/1.0") -> DeviceRow:
    return DeviceRow(
        device_id=uuid.uuid4(),
        client_device_id=label,
        device_label=label,
        user_agent=user_agent,
        last_seen_at=BASE - timedelta(minutes=minutes_ago),
    )


def _three_rows() -> list[DeviceRow]:
    """Three devices, most-recently-active first (the registry's own ordering)."""
    return [
        _row("laptop", minutes_ago=1),
        _row("tablet", minutes_ago=30),
        _row("phone", minutes_ago=600),
    ]


# ---------------------------------------------------------------------------
# G-10 — the login challenge
# ---------------------------------------------------------------------------


@pytest.fixture
def login_context() -> Iterator[tuple[TestClient, StubRegistry]]:
    settings = Settings()
    registry = StubRegistry(_three_rows())
    mirror = FakeUserMirror()
    service = AuthService(
        gotrue=FakeGoTrueBackend(),
        mirror=mirror,
        sms=MockSmsProvider(),
        otp_store=OtpStore(
            clock=lambda: datetime.now(UTC),
            rng=random.Random(7),
            ttl_seconds=settings.auth.otp_ttl_seconds,
            max_attempts=settings.auth.otp_max_attempts,
            code_length=settings.auth.otp_length,
        ),
        settings=settings,
        device_registry=registry,
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    # Issue #10: /auth/signup now reads the mirror for a read-only
    # duplicate-address pre-check (see routers/auth.py's `signup` docstring).
    # Override it to the same mirror `service` is built on, keeping this
    # fixture's own hermetic claim (its module docstring) true rather than
    # falling back to the real DbUserMirror against a database this file
    # otherwise never touches.
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    # Spec §4.4: the two D7.12 cooldown dependencies are now Postgres-backed
    # (`DbCooldownStore`) in production. Left unoverridden, this fixture's own
    # `/auth/signup` call below would stamp the real dev database's
    # `auth_cooldowns` table for "s@example.com" — and unlike the old
    # in-memory `CooldownStore` that `reset_singletons()` rebuilt fresh for
    # every test, that stamp is durable: it outlives this fixture's teardown
    # and 429s whichever test using this same fixture runs next in the same
    # session, exactly the failure mode the mirror override above already
    # guards against for the duplicate-address check.
    # Built once here and captured by the override lambdas' closures — never
    # constructed inside a lambda, which FastAPI would re-invoke (with no
    # caching of its own) on every request, silently handing out a brand-new
    # empty store per call rather than one shared across a whole test.
    signup_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC), min_seconds=settings.auth.signup_and_reset_cooldown_seconds
    )
    resend_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC),
        min_seconds=settings.auth.resend_verification_cooldown_seconds,
    )
    app.dependency_overrides[get_signup_and_reset_cooldown_store] = lambda: signup_cooldown
    app.dependency_overrides[get_resend_verification_cooldown_store] = lambda: resend_cooldown
    client = TestClient(app)
    client.post(
        "/api/auth/signup",
        json={
            "email": "s@example.com",
            "password": "pw-123456",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    registry.rows = _three_rows()  # the signup consumed a slot; reset to "at the cap"
    registry.registered.clear()
    try:
        yield client, registry
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def _login(client: TestClient, **extra: object) -> object:
    return client.post(
        "/api/auth/login",
        json={"email": "s@example.com", "password": "pw-123456", **extra},
    )


def test_a_fourth_device_login_is_a_409_challenge_and_mints_nothing(
    login_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = login_context
    expected = [str(row.device_id) for row in registry.rows]

    resp = _login(client)

    assert resp.status_code == 409, resp.text  # type: ignore[attr-defined]
    detail = resp.json()["detail"]  # type: ignore[attr-defined]
    assert detail["reason"] == "device_limit_reached"
    assert detail["maxDevices"] == MAX_DEVICES
    assert [d["deviceId"] for d in detail["devices"]] == expected
    # D5.12 §2: no token is minted on the challenge, so a client cannot treat a
    # 409 as a soft success and proceed half-authenticated.
    assert "accessToken" not in resp.text  # type: ignore[attr-defined]
    assert registry.registered == [False]


def test_the_challenge_names_the_device_that_will_be_signed_out(
    login_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = login_context
    oldest = str(registry.rows[-1].device_id)

    detail = _login(client).json()["detail"]  # type: ignore[attr-defined]

    assert detail["oldestDeviceId"] == oldest


def test_the_challenge_carries_no_location_field(
    login_context: tuple[TestClient, StubRegistry],
) -> None:
    # D5.12 §5: UI spec G-10 asks for a rough location and this build has no
    # geo-IP source and stores no IP, so the field must be *absent* rather than
    # guessed — it is the one a user would base "sign this one out" on, and
    # inventing it is exactly what UI spec §1.4 forbids.
    client, _ = login_context

    resp = _login(client)

    # Assert the challenge fired before scanning it: a 200 body trivially
    # contains no "location" either, and this test must not pass for that reason.
    assert resp.status_code == 409, resp.text  # type: ignore[attr-defined]
    body = resp.text.lower()  # type: ignore[attr-defined]
    assert "location" not in body
    assert "city" not in body


def test_a_confirmed_login_is_the_one_allowed_to_evict(
    login_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = login_context

    resp = _login(client, confirmDeviceEviction=True)

    assert resp.status_code == 200, resp.text  # type: ignore[attr-defined]
    assert resp.json()["accessToken"]  # type: ignore[attr-defined]
    assert registry.registered == [True]
    assert len(registry.rows) == MAX_DEVICES


def test_a_login_below_the_cap_is_never_challenged(
    login_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = login_context
    registry.rows = registry.rows[:1]

    resp = _login(client)

    assert resp.status_code == 200, resp.text  # type: ignore[attr-defined]


def test_bad_credentials_are_still_a_401_not_a_challenge(
    login_context: tuple[TestClient, StubRegistry],
) -> None:
    # The device list is only ever produced *after* the credential is verified
    # (D5.12 §1). A wrong password must not reach the registry at all, or an
    # email address alone would enumerate a stranger's browsers.
    client, registry = login_context

    resp = client.post(
        "/api/auth/login",
        json={"email": "s@example.com", "password": "wrong-password"},
    )

    assert resp.status_code == 401, resp.text
    assert registry.registered == []


# ---------------------------------------------------------------------------
# G-11 — the device list and individual sign-out
# ---------------------------------------------------------------------------


@pytest.fixture
def me_context() -> Iterator[tuple[TestClient, StubRegistry]]:
    registry = StubRegistry(_three_rows())
    app = create_app()
    app.dependency_overrides[get_device_registry] = lambda: registry
    client = TestClient(app)
    try:
        yield client, registry
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def _as(
    client: TestClient, *, role: Role = Role.student, session_id: str | None = None
) -> TestClient:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(uuid.uuid4()), role=role.value, session_id=session_id
    )
    return client


def test_the_list_marks_only_the_calling_device_as_current(
    me_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = me_context
    mine = str(registry.rows[1].device_id)
    _as(client, session_id=mine)

    body = client.get("/api/me/devices").json()

    assert body["maxDevices"] == MAX_DEVICES
    assert [d["isCurrent"] for d in body["devices"]] == [False, True, False]
    assert [d["deviceId"] for d in body["devices"]] == [str(r.device_id) for r in registry.rows]


def test_a_token_with_no_session_claim_marks_nothing_current(
    me_context: tuple[TestClient, StubRegistry],
) -> None:
    # Seat-invite signups and hermetic tokens carry no session_id (D1.11). The
    # list must still render — with no device claimed — rather than guessing one.
    client, _ = me_context
    _as(client, session_id=None)

    body = client.get("/api/me/devices").json()

    assert all(d["isCurrent"] is False for d in body["devices"])


@pytest.mark.parametrize(
    "role", [Role.student, Role.parent, Role.teacher, Role.school_admin, Role.platform_admin]
)
def test_every_role_can_manage_its_own_devices(
    me_context: tuple[TestClient, StubRegistry], role: Role
) -> None:
    # G-11 is "All" in the UI spec, and the 3-device limit applies to every
    # account. A role gate here would build a settings screen two-thirds of the
    # platform cannot open — the mistake P5.6 chunk C1 caught on the inbox.
    client, _ = me_context
    _as(client, role=role)

    assert client.get("/api/me/devices").status_code == 200


def test_signing_out_the_current_device_reports_it(
    me_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = me_context
    mine = str(registry.rows[0].device_id)
    _as(client, session_id=mine)

    body = client.delete(f"/api/me/devices/{mine}").json()

    assert body == {"removed": True, "wasCurrent": True}
    assert all(str(r.device_id) != mine for r in registry.rows)


def test_signing_out_another_of_my_devices_is_not_current(
    me_context: tuple[TestClient, StubRegistry],
) -> None:
    client, registry = me_context
    other = str(registry.rows[2].device_id)
    _as(client, session_id=str(registry.rows[0].device_id))

    body = client.delete(f"/api/me/devices/{other}").json()

    assert body == {"removed": True, "wasCurrent": False}


@pytest.mark.parametrize("device_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_an_unknown_or_malformed_device_is_a_false_not_a_404(
    me_context: tuple[TestClient, StubRegistry], device_id: str
) -> None:
    # A 404 here would answer "does this device id exist?" for ids the caller
    # does not own. Both cases are an ordinary, idempotent "nothing removed".
    client, _ = me_context
    _as(client)

    resp = client.delete(f"/api/me/devices/{device_id}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"removed": False, "wasCurrent": False}


def test_the_revoke_is_always_scoped_to_the_token_subject(
    me_context: tuple[TestClient, StubRegistry],
) -> None:
    # There is no user id on this router: the id handed to the registry is the
    # token's sub, so one account cannot revoke another's session (D1.6).
    client, registry = me_context
    caller = uuid.uuid4()
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(caller), role=Role.student.value, session_id=None
    )
    target = str(registry.rows[0].device_id)

    client.delete(f"/api/me/devices/{target}")

    assert registry.revoked == [(str(caller), target)]
