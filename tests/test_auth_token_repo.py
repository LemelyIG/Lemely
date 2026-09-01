"""Postgres integration tests for :class:`~lemely.db.auth_token_repo.AuthTokenService` (D7.7).

These exercise the service against a throwaway database and skip cleanly when no
local server is reachable (mirrors ``test_seat_repo.py`` / ``test_db_schema.py``).
They prove the guarantees the security review of this table depends on:

* **Nothing redeemable is stored.** The row holds a SHA-256 hash, never the
  plaintext token handed back by :meth:`~lemely.db.auth_token_repo.AuthTokenService.mint`.
* **Single-use.** A token redeems once; the second presentation of the same
  token is a distinct, more specific failure (``TokenAlreadyUsed``) than an
  unknown one (``TokenNotFound``), and the row is never deleted to make that
  true — it is marked, so a redeemed token remains evidence.
* **Purpose is part of the lookup, not a check bolted on afterwards.** A live,
  unexpired, unused token minted for one purpose is indistinguishable from an
  unknown token when redeemed against the other purpose — both raise
  ``TokenNotFound`` — so the error itself cannot be used to probe which tokens
  exist for which purpose.
* **Expiry is a distinct fact from use.** An unused-but-expired token raises
  ``TokenExpired``, never ``TokenAlreadyUsed`` — the caller's copy differs
  between the two.
* **Revocation stamps, it does not delete.** ``revoke_all`` marks every live
  token for a (user, purpose) pair used, in the same way a normal redemption
  would, rather than removing the rows.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.auth_token_repo import (
    AuthTokenService,
    TokenAlreadyUsed,
    TokenExpired,
    TokenNotFound,
)
from lemely.db.base import Base
from lemely.db.models import AuthToken, User
from lemely.db.models.enums import AuthTokenPurpose, Role
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FrozenClock:
    """A mutable clock: ``advance`` moves it forward for expiry tests.

    Matches the shape already established for this exact feature family in
    ``tests/test_auth_cooldown.py`` — same constructor, same ``advance``
    signature — so a reader who has seen one has seen both.
    """

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


# ── mint ─────────────────────────────────────────────────────────────────────


def test_mint_returns_plaintext_and_stores_only_a_hash(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The stored row must not contain anything redeemable (D7.7)."""
    user_id = _seed_user(pg_sessionmaker)
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)

    token = service.mint(user_id, AuthTokenPurpose.password_reset)

    with pg_sessionmaker() as session:
        row = session.scalars(select(AuthToken)).one()
    assert row.token_hash != token
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.user_id == user_id
    assert row.purpose is AuthTokenPurpose.password_reset
    assert row.used_at is None


# ── mint: per-call ttl override ─────────────────────────────────────────────


def test_mint_per_call_ttl_overrides_the_constructor_default(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The per-call ``ttl_seconds`` wins over the constructor default.

    This is what lets a single shared ``AuthTokenService`` instance serve both
    a long-lived verification token and a short-lived reset token (D7's
    binding rule that the two purposes must not share a lifetime) instead of
    ``deps.py`` wiring two differently-configured instances. Proven by expiry,
    not by inspecting the row: a token minted with a short override must be
    expired at a clock point where a token minted off the (much longer)
    constructor default, on the very same service instance, is not - so the
    override cannot be a global mutation that leaked into the second mint.
    """
    user_id = _seed_user(pg_sessionmaker)
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    service = AuthTokenService(pg_sessionmaker, clock=clock, ttl_seconds=3600)

    overridden = service.mint(user_id, AuthTokenPurpose.email_verification, ttl_seconds=60)
    off_default = service.mint(user_id, AuthTokenPurpose.password_reset)

    clock.advance(61)

    with pytest.raises(TokenExpired):
        service.redeem(overridden, AuthTokenPurpose.email_verification)
    # The constructor's 3600s default has not elapsed - the override applied
    # only to the call that requested it.
    assert service.redeem(off_default, AuthTokenPurpose.password_reset) == user_id


# ── redeem: happy path ──────────────────────────────────────────────────────


def test_redeem_returns_the_user_and_marks_the_token_used(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)
    token = service.mint(user_id, AuthTokenPurpose.email_verification)

    redeemed_user_id = service.redeem(token, AuthTokenPurpose.email_verification)

    assert redeemed_user_id == user_id
    with pg_sessionmaker() as session:
        row = session.scalars(select(AuthToken)).one()
    assert row.used_at is not None


# ── redeem: single-use ───────────────────────────────────────────────────────


def test_redeem_twice_raises_token_already_used(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Single-use is enforced on the row, not by deleting it."""
    user_id = _seed_user(pg_sessionmaker)
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)
    token = service.mint(user_id, AuthTokenPurpose.password_reset)

    service.redeem(token, AuthTokenPurpose.password_reset)

    with pytest.raises(TokenAlreadyUsed):
        service.redeem(token, AuthTokenPurpose.password_reset)

    # The row survives the failed second redemption - it is evidence, not gone.
    with pg_sessionmaker() as session:
        row = session.scalars(select(AuthToken)).one()
    assert row.used_at is not None


# ── redeem: expiry ────────────────────────────────────────────────────────────


def test_redeem_after_expiry_raises_token_expired(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    clock = _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    service = AuthTokenService(pg_sessionmaker, clock=clock, ttl_seconds=60)
    token = service.mint(user_id, AuthTokenPurpose.password_reset)

    clock.advance(61)

    with pytest.raises(TokenExpired):
        service.redeem(token, AuthTokenPurpose.password_reset)


# ── redeem: cross-purpose (the one that matters most) ─────────────────────────


def test_redeem_with_the_wrong_purpose_raises_token_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A verification token presented to the reset route is not a reset token.

    This is the test that matters most in the file: purpose is part of the
    lookup predicate, so cross-purpose redemption is structurally impossible
    rather than checked. Assert it against a *live, unexpired, unused* token so
    the failure can only come from the purpose mismatch, not from some other
    invalidity.
    """
    user_id = _seed_user(pg_sessionmaker)
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)
    token = service.mint(user_id, AuthTokenPurpose.email_verification)

    # Prove liveness before the mismatched redemption, so the TokenNotFound
    # below cannot be explained by anything other than the purpose mismatch.
    with pg_sessionmaker() as session:
        row = session.scalars(select(AuthToken)).one()
        assert row.used_at is None
        assert row.expires_at > datetime.now(UTC)

    with pytest.raises(TokenNotFound):
        service.redeem(token, AuthTokenPurpose.password_reset)

    # And the wrong-purpose attempt must not have consumed or altered it - the
    # token still redeems normally against its real purpose afterwards.
    assert service.redeem(token, AuthTokenPurpose.email_verification) == user_id


# ── redeem: unknown token ──────────────────────────────────────────────────────


def test_redeem_with_an_unknown_token_raises_token_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)

    with pytest.raises(TokenNotFound):
        service.redeem("this-token-was-never-minted", AuthTokenPurpose.password_reset)


# ── revoke_all ──────────────────────────────────────────────────────────────────


def test_revoke_all_marks_every_live_token_for_that_purpose_used(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Called on password change: every outstanding reset link dies at once."""
    user_id = _seed_user(pg_sessionmaker)
    service = AuthTokenService(pg_sessionmaker, ttl_seconds=3600)
    reset_token_a = service.mint(user_id, AuthTokenPurpose.password_reset)
    reset_token_b = service.mint(user_id, AuthTokenPurpose.password_reset)
    verify_token = service.mint(user_id, AuthTokenPurpose.email_verification)

    service.revoke_all(user_id, AuthTokenPurpose.password_reset)

    # Stamped used, not deleted: TokenAlreadyUsed (not TokenNotFound) is what
    # proves the rows still exist after revoke_all.
    with pytest.raises(TokenAlreadyUsed):
        service.redeem(reset_token_a, AuthTokenPurpose.password_reset)
    with pytest.raises(TokenAlreadyUsed):
        service.redeem(reset_token_b, AuthTokenPurpose.password_reset)

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(AuthToken).where(AuthToken.purpose == AuthTokenPurpose.password_reset)
        ).all()
    assert len(rows) == 2
    assert all(row.used_at is not None for row in rows)

    # A different purpose for the same user is untouched.
    assert service.redeem(verify_token, AuthTokenPurpose.email_verification) == user_id
