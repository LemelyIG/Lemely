"""FastAPI TestClient coverage of the /api/auth/* endpoints.

Fully hermetic (in-memory GoTrue + user mirror) via the ``context`` fixture,
except for the seven ``/auth/parent/*`` tests (spec §4), which redeem a real,
Postgres-backed ``InviteService`` via the separate ``parent_context`` fixture
— see that fixture's own docstring for why it is kept apart from ``context``.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.auth.cooldown import CooldownStore
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.auth.tokens import decode_token, mint_access_token, mint_email_proof_token
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import (
    InviteAlreadyRedeemedError,
    InvitePreview,
    InviteService,
    RedeemResult,
)
from lemely.db.models import Invite, School, SchoolMembership, User
from lemely.db.models.enums import MembershipRole, Role
from lemely.db.parent_repo import ParentLinkService
from lemely.runtime.config import DatabaseSettings, Settings
from lemely.runtime.errors import AuthError
from lemely.web.app import create_app
from lemely.web.deps import (
    get_auth_service,
    get_device_registry,
    get_invite_service,
    get_resend_verification_cooldown_store,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
    reset_singletons,
)
from lemely.web.routers.auth import _UNKNOWN_PARENT_INVITE_DETAIL
from tests.auth_fakes import (
    FakeDeviceRegistry,
    FakeEmailProvider,
    FakeGoTrueBackend,
    FakeUserMirror,
)

# ── Postgres fixtures (``parent_context``'s InviteService override) ────────
#
# Self-contained rather than shared via conftest, matching every other
# ``test_web_*.py`` file's ``pg_sessionmaker`` duplication convention (see
# ``tests/test_web_invites.py``, whose fixtures this mirrors exactly).


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


def _seed_user(sm: sessionmaker[Session], role: Role, display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _invite_service(sm: sessionmaker[Session]) -> InviteService:
    return InviteService(sm, ClassService(sm), ParentLinkService(sm))


class PgBackedUserMirror(FakeUserMirror):
    """A :class:`~tests.auth_fakes.FakeUserMirror` that also writes real ``users`` rows.

    Needed only for the parent-signup tests below. The three ``/auth/parent/*``
    routes redeem the freshly signed-up parent through the **real**,
    Postgres-backed ``InviteService`` this file's ``parent_context`` fixture
    wires (see its own docstring), and
    :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session` inserts a
    genuine ``parent_child_links`` row whose ``parent_id`` foreign-keys to
    ``users.id`` in that same database. ``FakeUserMirror``'s own in-memory
    dict is invisible to Postgres and cannot satisfy that constraint on its
    own, so this subclass keeps that dict (existing tests still read
    ``service._mirror.rows`` directly) and mirrors every write into a real
    row in the same throwaway database ``pg_sessionmaker`` built.
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


def _override_cooldowns(app: FastAPI, settings: Settings) -> None:
    """Override both D7.12 cooldown dependencies with fresh in-memory stores.

    Spec §4.4 moved ``get_signup_and_reset_cooldown_store`` /
    ``get_resend_verification_cooldown_store`` onto ``DbCooldownStore``
    (Postgres-backed) in production. Left unoverridden, every
    ``/auth/signup``, ``/auth/verify-email/resend`` or
    ``/auth/password-reset/request`` call this hermetic suite makes would
    stamp the real dev database's ``auth_cooldowns`` table — and, unlike the
    old in-memory ``CooldownStore`` that ``reset_singletons()`` rebuilt fresh
    for every test, that stamp is durable: it outlives the fixture teardown
    and throttles (429) whichever *later* test in the same run reuses the
    same email, exactly as ``test_signup_duplicate_returns_400``'s own
    comment already documents for ``get_user_mirror``. A fresh
    :class:`~lemely.auth.cooldown.CooldownStore` per fixture invocation
    restores that same fresh-per-test isolation.

    Each store is built once, here, and captured by the override lambda's
    closure — **not** constructed inside the lambda. FastAPI re-invokes a
    dependency override on every request with no caching of its own, so a
    lambda that builds ``CooldownStore(...)`` in its own body would hand out
    a brand-new, empty store to every request rather than one store shared
    across the whole test: cooldown would silently never trigger *within* a
    test, only (correctly, but for the wrong reason) look isolated *between*
    tests. Capturing one instance here is what makes it isolated between
    tests while still persisting within one.
    """
    signup_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC),
        min_seconds=settings.auth.signup_and_reset_cooldown_seconds,
    )
    resend_cooldown = CooldownStore(
        clock=lambda: datetime.now(UTC),
        min_seconds=settings.auth.resend_verification_cooldown_seconds,
    )
    app.dependency_overrides[get_signup_and_reset_cooldown_store] = lambda: signup_cooldown
    app.dependency_overrides[get_resend_verification_cooldown_store] = lambda: resend_cooldown


@pytest.fixture
def context() -> Iterator[tuple[TestClient, AuthService, Settings]]:
    """Fully hermetic: in-memory GoTrue, mirror, OTP store — no database at all.

    Deliberately carries **no** ``pg_sessionmaker`` dependency. Every test in
    this file except the seven ``/auth/parent/*`` ones (see
    :func:`parent_context`) uses this fixture, and none of them touch an
    invite — a Postgres dependency here would silently *skip* (not fail) the
    whole file's signup/login/refresh/password-reset/device-limit coverage
    wherever local Postgres is unreachable, which is exactly the "green run,
    no signal" failure mode a CI lane without a database would hit.
    """
    settings = Settings()
    mirror = FakeUserMirror()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(7),
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
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    # Issue #10: /auth/signup now reads the mirror directly (a read-only
    # duplicate-address pre-check gating whether D7.12's cooldown applies at
    # all — see routers/auth.py's `signup` docstring). Override it to the
    # SAME mirror `service` is built on, or this app would fall back to the
    # real, unoverridden DbUserMirror against a database these hermetic tests
    # never touch — which would see every address as unclaimed forever and
    # make `test_signup_duplicate_returns_400`'s second call spuriously 429.
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    _override_cooldowns(app, settings)
    client = TestClient(app)
    try:
        yield client, service, settings
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


@pytest.fixture
def parent_context(
    pg_sessionmaker: sessionmaker[Session],
) -> Iterator[tuple[TestClient, AuthService, Settings]]:
    """Layers a real, Postgres-backed ``InviteService`` on top of :func:`context`'s shape.

    Used only by the seven ``/auth/parent/*`` tests below, so only those
    tests pay for (and require) a throwaway Postgres database — every other
    test in this file uses the fully hermetic :func:`context` instead.

    GoTrue and the OTP store stay in-memory, exactly as in :func:`context`.
    The **user mirror** is :class:`PgBackedUserMirror` rather than the plain
    :class:`~tests.auth_fakes.FakeUserMirror` — see that class's own
    docstring — and ``get_invite_service`` is overridden to a real,
    Postgres-backed :class:`~lemely.db.invite_repo.InviteService` (the same
    ``pg_sessionmaker`` pattern ``tests/test_web_invites.py`` uses), rather
    than a fake with matching method names: these routes' whole point is
    minting a genuine ``parent_child_links`` row, and a fake service could
    not prove that row is real.
    """
    settings = Settings()
    mirror = PgBackedUserMirror(pg_sessionmaker)
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(7),
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
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    app.dependency_overrides[get_invite_service] = lambda: _invite_service(pg_sessionmaker)
    _override_cooldowns(app, settings)
    client = TestClient(app)
    try:
        yield client, service, settings
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def test_signup_endpoint(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": "s@example.com",
            "password": "pw-123456",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "student"
    assert body["accessToken"]
    assert body["userId"]


@pytest.mark.parametrize("role", ["school_admin", "platform_admin"])
def test_signup_elevated_role_forbidden(
    context: tuple[TestClient, AuthService, Settings], role: str
) -> None:
    # D1.7, revised in scope but not in spirit by D7.1 (which admits `teacher`
    # to self-service signup — see `_SELF_SERVICE_SIGNUP_ROLES`'s own comment
    # in `lemely/web/routers/auth.py`, and `test_web_auth.py`'s
    # `test_signup_elevated_role_still_forbidden`, the fuller, house-style
    # version of this test). `school_admin`/`platform_admin` remain
    # unobtainable by an anonymous caller: requesting either must be a 403 so
    # signup can never be a privilege-escalation path (anonymous caller
    # POSTing role="platform_admin" to mint an admin token).
    client, _, _ = context
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": f"{role}@example.com",
            "password": "pw-123456",
            "role": role,
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 403, resp.text


def test_signup_duplicate_returns_400(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    payload = {
        "email": "dup@example.com",
        "password": "pw-123456",
        "role": "student",
        "acceptedTerms": True,
    }
    assert client.post("/api/auth/signup", json=payload).status_code == 200
    resp = client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 400


def test_login_endpoint(context: tuple[TestClient, AuthService, Settings]) -> None:
    client, _, _ = context
    client.post(
        "/api/auth/signup",
        json={
            "email": "l@example.com",
            "password": "pw-abcdef",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "l@example.com", "password": "pw-abcdef"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "student"


def test_login_wrong_password_returns_401(
    context: tuple[TestClient, AuthService, Settings],
) -> None:
    client, _, _ = context
    client.post(
        "/api/auth/signup",
        json={
            "email": "w@example.com",
            "password": "right-pw-1",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "w@example.com", "password": "bad-pw-1"},
    )
    assert resp.status_code == 401


def test_parent_request_code_happy_path_returns_dev_code(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client, service, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student)
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)

    resp = client.post(
        "/api/auth/parent/request-code",
        json={"email": "parent1@example.com", "inviteCode": invite.code},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "sent"
    assert body["devCode"], "the offline mock provider is the only source of the code"
    assert service._email.sent_signup_codes == [("parent1@example.com", body["devCode"])]


def test_parent_request_code_dead_invite_is_404(
    parent_context: tuple[TestClient, AuthService, Settings],
) -> None:
    client, _, _ = parent_context
    resp = client.post(
        "/api/auth/parent/request-code",
        json={"email": "nobody@example.com", "inviteCode": "NOSUCHCODE"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": _UNKNOWN_PARENT_INVITE_DETAIL}
    assert "NOSUCHCODE" not in resp.text


def test_parent_request_code_404_is_byte_identical_across_dead_invite_kinds(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Unknown, non-parent, expired and already-redeemed codes must be
    indistinguishable (spec §4's own binding disclosure rule) — same status,
    same body, byte for byte, across all four. A caller who could tell any
    one of these apart from "unknown code" would learn something about a
    code they have no business redeeming, and none of the four detail
    strings may contain the code that produced them."""
    client, _, _ = parent_context
    invite_service = _invite_service(pg_sessionmaker)

    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(School(id=school_id, name="Dead-Invite Test School", seat_quota=5))
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=admin, membership_role=MembershipRole.school_admin
            )
        )
    non_parent_invite = invite_service.mint_seat_invite(admin, school_id)

    expired_student = _seed_user(pg_sessionmaker, Role.student)
    expired_invite = invite_service.mint_parent_invite(expired_student, reusable=False)
    with pg_sessionmaker.begin() as session:
        row = session.get(Invite, expired_invite.id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(days=1)

    redeemed_student = _seed_user(pg_sessionmaker, Role.student)
    redeemed_invite = invite_service.mint_parent_invite(redeemed_student, reusable=False)
    redeeming_parent = _seed_user(pg_sessionmaker, Role.parent)
    invite_service.redeem(redeeming_parent, redeemed_invite.code, caller_role=Role.parent)

    codes = {
        "unknown": "NOSUCHCODE",
        "non_parent": non_parent_invite.code,
        "expired": expired_invite.code,
        "redeemed": redeemed_invite.code,
    }
    responses = {
        name: client.post(
            "/api/auth/parent/request-code",
            json={"email": "nobody@example.com", "inviteCode": code},
        )
        for name, code in codes.items()
    }

    for name, resp in responses.items():
        assert resp.status_code == 404, f"{name}: {resp.text}"
        assert resp.json() == {"detail": _UNKNOWN_PARENT_INVITE_DETAIL}, name
        assert codes[name] not in resp.text, name


def test_parent_request_code_taken_email_is_400(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client, _, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student)
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "taken@example.com",
            "password": "pw-123456",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    assert signup.status_code == 200, signup.text

    resp = client.post(
        "/api/auth/parent/request-code",
        json={"email": "taken@example.com", "inviteCode": invite.code},
    )

    assert resp.status_code == 400, resp.text


def test_parent_request_code_cooldown_is_429(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client, _, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student)
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)
    payload = {"email": "cooldown@example.com", "inviteCode": invite.code}

    first = client.post("/api/auth/parent/request-code", json=payload)
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/parent/request-code", json=payload)
    assert second.status_code == 429, second.text


def test_parent_verify_code_wrong_is_401(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client, _, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student)
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)
    email = "wrong@example.com"
    request = client.post(
        "/api/auth/parent/request-code", json={"email": email, "inviteCode": invite.code}
    )
    dev_code = request.json()["devCode"]
    # Guaranteed different from the real code regardless of its value.
    wrong_last_digit = "0" if dev_code[-1] != "0" else "1"
    wrong_code = dev_code[:-1] + wrong_last_digit

    resp = client.post(
        "/api/auth/parent/verify-code",
        json={"email": email, "inviteCode": invite.code, "code": wrong_code},
    )

    assert resp.status_code == 401


def test_parent_verify_code_taken_email_never_reaches_the_otp_store(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Final review I-1: an already-registered email must be refused with the
    same 400 :func:`request_parent_code` uses *before*
    ``AuthService.verify_parent_signup_code`` is ever called — that method
    verifies on the OTP store's ``email`` channel keyed by the plain address,
    the identical ``(channel, address)`` key ``AuthService._issue_email_code``
    uses for a signed-up user's own pending email-verification challenge.
    Reaching it with a taken email would let an anonymous caller lock out a
    stranger's challenge after five wrong guesses. Proven here by driving five
    wrong guesses through the public route and then showing the victim's own
    challenge still verifies.
    """
    client, service, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student)
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)

    victim_email = "victim@example.com"
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": victim_email,
            "password": "pw-123456",
            "role": "student",
            "acceptedTerms": True,
        },
    )
    assert signup.status_code == 200, signup.text
    victim_id = uuid.UUID(signup.json()["userId"])

    # `parent_context`'s `AuthService` is built with no `tokens=`, so `signup`
    # itself never mints a verification challenge (see `signup`'s own
    # docstring, "Both `email` and `tokens` are optional collaborators").
    # Issuing one directly here stands in for the challenge a real deployment
    # would already have minted, or `resend_verification` would mint fresh.
    real_code = service._issue_email_code(victim_email)

    for _ in range(5):
        resp = client.post(
            "/api/auth/parent/verify-code",
            json={"email": victim_email, "inviteCode": invite.code, "code": "000000"},
        )
        assert resp.status_code == 400, resp.text

    # The victim's own challenge survives untouched: the real code still
    # verifies, proving the router never reached `verify_parent_signup_code`
    # (which would have consumed or, after five wrong guesses, locked it out).
    service.verify_email_code(victim_id, real_code)


def test_parent_signup_creates_verified_parent_and_links(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client, service, settings = parent_context
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Maya")
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)
    email = "newparent@example.com"

    request = client.post(
        "/api/auth/parent/request-code", json={"email": email, "inviteCode": invite.code}
    )
    assert request.status_code == 200, request.text
    dev_code = request.json()["devCode"]

    verify = client.post(
        "/api/auth/parent/verify-code",
        json={"email": email, "inviteCode": invite.code, "code": dev_code},
    )
    assert verify.status_code == 200, verify.text
    proof_token = verify.json()["proofToken"]

    signup = client.post(
        "/api/auth/parent/signup",
        json={
            "proofToken": proof_token,
            "password": "pw-123456",
            "acceptedTerms": True,
            "displayName": "New Parent",
        },
    )

    assert signup.status_code == 200, signup.text
    body = signup.json()
    assert body["role"] == "parent"
    # Verified immediately from the proof token - no verification link/code minted.
    assert body["devLink"] is None
    assert body["devCode"] is None
    claims = decode_token(body["accessToken"], settings)
    assert claims.app_role == "parent"
    assert claims.email == email

    mirrored = service._mirror.get_by_id(uuid.UUID(body["userId"]))
    assert mirrored is not None
    assert mirrored.email_verified_at is not None

    children = ParentLinkService(pg_sessionmaker).linked_children(uuid.UUID(body["userId"]))
    assert [c.child_id for c in children] == [student]


def test_parent_signup_expired_proof_is_401(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client, _, settings = parent_context
    student = _seed_user(pg_sessionmaker, Role.student)
    invite = _invite_service(pg_sessionmaker).mint_parent_invite(student, reusable=False)
    expired_proof = mint_email_proof_token(
        email="expired@example.com",
        invite_code=invite.code,
        settings=settings,
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    resp = client.post(
        "/api/auth/parent/signup",
        json={"proofToken": expired_proof, "password": "pw-123456", "acceptedTerms": True},
    )

    assert resp.status_code == 401, resp.text


def test_parent_signup_proof_token_only_redeems_its_own_invite(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Pins ``claims.invite_code`` (never any other source) as what ``redeem`` uses.

    Two students, two live parent invites. The proof token here is minted
    for invite A alone; completing signup with it must link only child A.
    ``ParentSignupDTO`` carries no ``inviteCode`` field today precisely so
    there is nothing for a caller to supply, but a future refactor that read
    one from the body (or otherwise stopped trusting the token's own claim)
    would defeat this test by linking the wrong child or none at all.
    """
    client, _, settings = parent_context
    student_a = _seed_user(pg_sessionmaker, Role.student, display_name="A")
    student_b = _seed_user(pg_sessionmaker, Role.student, display_name="B")
    invite_service = _invite_service(pg_sessionmaker)
    invite_a = invite_service.mint_parent_invite(student_a, reusable=False)
    invite_service.mint_parent_invite(student_b, reusable=False)
    proof_token = mint_email_proof_token(
        email="pinned@example.com", invite_code=invite_a.code, settings=settings
    )

    signup = client.post(
        "/api/auth/parent/signup",
        json={"proofToken": proof_token, "password": "pw-123456", "acceptedTerms": True},
    )

    assert signup.status_code == 200, signup.text
    parent_id = uuid.UUID(signup.json()["userId"])
    children = ParentLinkService(pg_sessionmaker).linked_children(parent_id)
    assert [c.child_id for c in children] == [student_a]


def test_parent_signup_link_redeemed_by_another_parent_before_signup_is_404(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A single-use link forwarded to two parents: whichever completes
    signup second must not get a stray account. Parent A redeems the link
    in the window between parent B's own ``verify-code`` and ``signup``
    calls — by the time B's ``signup`` runs, ``_require_live_parent_invite``'s
    ``preview`` call sees the row as already redeemed (spec §3: a redeemed
    single-use link previews as unknown) and refuses **before** any GoTrue
    account is created for B, with the identical detail an unknown code
    gets. See ``test_parent_signup_survives_a_redeem_that_fails_after_account_creation``
    for the narrower window this cannot close (the account already created
    by the time ``redeem`` itself is what raises).
    """
    client, service, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Kid")
    invite_service = _invite_service(pg_sessionmaker)
    invite = invite_service.mint_parent_invite(student, reusable=False)
    parent_a = _seed_user(pg_sessionmaker, Role.parent)
    email_b = "parent-b@example.com"

    request = client.post(
        "/api/auth/parent/request-code", json={"email": email_b, "inviteCode": invite.code}
    )
    dev_code = request.json()["devCode"]
    verify = client.post(
        "/api/auth/parent/verify-code",
        json={"email": email_b, "inviteCode": invite.code, "code": dev_code},
    )
    proof_token = verify.json()["proofToken"]

    # Parent A redeems the same single-use link in the window between B's
    # verify-code and signup calls (simulating two parents racing one link).
    invite_service.redeem(parent_a, invite.code, caller_role=Role.parent)

    signup = client.post(
        "/api/auth/parent/signup",
        json={"proofToken": proof_token, "password": "pw-123456", "acceptedTerms": True},
    )

    assert signup.status_code == 404, signup.text
    assert signup.json() == {"detail": _UNKNOWN_PARENT_INVITE_DETAIL}
    assert invite.code not in signup.text
    # No account was created for B - the check ran before GoTrue create.
    assert service._mirror.get_by_email(email_b) is None


def test_parent_signup_survives_a_redeem_that_fails_after_account_creation(
    parent_context: tuple[TestClient, AuthService, Settings],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """C1: if ``redeem`` itself fails *after* the GoTrue account already
    exists, the route must not 500 or strand the caller with no way back.

    The previous test closes the window where the race is won early enough
    for ``_require_live_parent_invite``'s own ``preview`` check to catch it.
    This test exercises the narrower window that check cannot see — the
    invite is redeemed by someone else in the instant *between* that check
    and ``InviteService.redeem`` itself, inside the same request — which is
    not reproducible sequentially against the real service (the exact same
    lookup both calls share would simply see the same state). A stub
    ``InviteService`` whose ``redeem`` always fails, swapped in only for the
    final call, stands in for that instant.
    """
    client, service, _ = parent_context
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Kid")
    invite_service = _invite_service(pg_sessionmaker)
    invite = invite_service.mint_parent_invite(student, reusable=False)
    email = "raced-parent@example.com"

    request = client.post(
        "/api/auth/parent/request-code", json={"email": email, "inviteCode": invite.code}
    )
    dev_code = request.json()["devCode"]
    verify = client.post(
        "/api/auth/parent/verify-code",
        json={"email": email, "inviteCode": invite.code, "code": dev_code},
    )
    proof_token = verify.json()["proofToken"]

    class _RedeemAlwaysFails:
        """Stands in for a ``redeem`` that loses a genuine same-instant race.

        ``preview`` delegates to the real, still-live invite (so
        ``_require_live_parent_invite`` passes exactly as it would in
        production up to this point); only ``redeem`` is replaced, with the
        exact exception a real race would produce.
        """

        def __init__(self, real: InviteService) -> None:
            self._real = real

        def preview(self, code: str) -> InvitePreview:
            return self._real.preview(code)

        def redeem(
            self, user_id: uuid.UUID | str, code: str, *, caller_role: Role | None = None
        ) -> RedeemResult:
            raise InviteAlreadyRedeemedError(f"Invite {code!r} has already been redeemed")

    client.app.dependency_overrides[get_invite_service] = lambda: _RedeemAlwaysFails(  # type: ignore[union-attr]
        invite_service
    )
    try:
        signup = client.post(
            "/api/auth/parent/signup",
            json={"proofToken": proof_token, "password": "pw-123456", "acceptedTerms": True},
        )
    finally:
        client.app.dependency_overrides[get_invite_service] = lambda: invite_service  # type: ignore[union-attr]

    assert signup.status_code == 200, signup.text
    body = signup.json()
    parent_id = uuid.UUID(body["userId"])
    # The account is real and the token works, even though the link failed.
    assert service._mirror.get_by_id(parent_id) is not None
    assert ParentLinkService(pg_sessionmaker).linked_children(parent_id) == []


# ── Refresh ───────────────────────────────────────────────────────────────────
#
# The regression these exist for: access tokens expire after an hour, and before
# this endpoint existed nothing renewed them. Every request past that point came
# back 401 "Invalid access token: Signature has expired", which the SPA rendered
# verbatim on screen while its route guard — which only checks that *a* session
# object is in localStorage — kept happily rendering the portal around it.


@pytest.fixture
def refreshable() -> Iterator[tuple[TestClient, AuthService, Settings, FakeDeviceRegistry]]:
    """A client whose auth service registers devices, so refresh tokens are minted.

    ``access_token_ttl_seconds`` is floored at 60 by config, so tests that need an
    already-expired access token mint one directly with an explicit past ``now``
    rather than waiting.
    """
    settings = Settings()
    mirror = FakeUserMirror()
    registry = FakeDeviceRegistry()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(7),
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
        device_registry=registry,  # type: ignore[arg-type]
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_device_registry] = lambda: registry
    # See the `context` fixture above for why this override is required now.
    app.dependency_overrides[get_user_mirror] = lambda: mirror
    _override_cooldowns(app, settings)
    client = TestClient(app)
    try:
        yield client, service, settings, registry
    finally:
        app.dependency_overrides.clear()
        reset_singletons()


def _signup(client: TestClient, email: str = "r@example.com") -> dict[str, str]:
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "pw-123456",
            "role": "student",
            "deviceId": "device-A",
            "acceptedTerms": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_signin_hands_back_a_refresh_token(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, _, _ = refreshable
    assert _signup(client)["refreshToken"]


def test_refresh_returns_a_usable_new_access_token(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, settings, _ = refreshable
    body = _signup(client)

    resp = client.post("/api/auth/refresh", json={"refreshToken": body["refreshToken"]})

    assert resp.status_code == 200, resp.text
    renewed = resp.json()
    claims = decode_token(renewed["accessToken"], settings)
    assert claims.sub == body["userId"]
    assert claims.app_role == "student"
    # Not rotated: the client keeps the token it already has (two tabs refreshing
    # concurrently must not be able to invalidate each other).
    assert renewed["refreshToken"] == body["refreshToken"]


def test_refresh_works_once_the_access_token_has_already_expired(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    # The actual bug: an expired access token 401s, and the refresh that is
    # supposed to rescue it must not itself depend on that dead credential.
    client, _, settings, _ = refreshable
    body = _signup(client)
    dead = mint_access_token(
        user_id=uuid.UUID(body["userId"]),
        settings=settings,
        app_role="student",
        provider="email",
        now=datetime.now(UTC) - timedelta(hours=3),
    )
    with pytest.raises(AuthError, match="expired"):
        decode_token(dead, settings)

    resp = client.post(
        "/api/auth/refresh",
        json={"refreshToken": body["refreshToken"]},
        headers={"Authorization": f"Bearer {dead}"},
    )

    assert resp.status_code == 200, resp.text
    assert decode_token(resp.json()["accessToken"], settings).sub == body["userId"]


def test_a_refresh_token_cannot_be_used_as_a_bearer_token(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    # It outlives the access token by a month, so if it also authenticated
    # requests it would quietly become a month-long access token.
    client, _, _, _ = refreshable
    body = _signup(client)

    resp = client.get(
        "/api/me/profile", headers={"Authorization": f"Bearer {body['refreshToken']}"}
    )

    # 401 specifically, not 404: the route exists and rejected the credential.
    assert resp.status_code == 401, resp.text


def test_refresh_is_refused_after_the_device_is_signed_out(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, _, registry = refreshable
    body = _signup(client)
    session_id = next(iter(registry.rows))
    assert registry.revoke(uuid.UUID(body["userId"]), session_id) is True

    resp = client.post("/api/auth/refresh", json={"refreshToken": body["refreshToken"]})

    assert resp.status_code == 401, resp.text


def test_refresh_is_refused_once_a_newer_login_supersedes_it(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    client, _, _, _ = refreshable
    first = _signup(client)
    second = client.post(
        "/api/auth/login",
        json={"email": "r@example.com", "password": "pw-123456", "deviceId": "device-A"},
    ).json()
    assert second["refreshToken"] != first["refreshToken"]

    stale = client.post("/api/auth/refresh", json={"refreshToken": first["refreshToken"]})
    fresh = client.post("/api/auth/refresh", json={"refreshToken": second["refreshToken"]})

    assert stale.status_code == 401, stale.text
    assert fresh.status_code == 200, fresh.text


def test_refresh_reflects_a_role_changed_since_sign_in(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry],
) -> None:
    # A refresh token lives for a month. If the role were read out of it rather
    # than out of `public.users`, a demoted account would keep its old powers for
    # that entire month.
    client, service, settings, _ = refreshable
    body = _signup(client)
    mirror = service._mirror
    mirror.rows[uuid.UUID(body["userId"])].role = Role.teacher

    resp = client.post("/api/auth/refresh", json={"refreshToken": body["refreshToken"]})

    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "teacher"
    assert decode_token(resp.json()["accessToken"], settings).app_role == "teacher"


@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt", "a.b.c"],
    ids=["empty", "garbage", "jwt-shaped-garbage"],
)
def test_malformed_refresh_token_is_401_not_500(
    refreshable: tuple[TestClient, AuthService, Settings, FakeDeviceRegistry], token: str
) -> None:
    client, _, _, _ = refreshable
    resp = client.post("/api/auth/refresh", json={"refreshToken": token})
    assert resp.status_code == 401, resp.text
