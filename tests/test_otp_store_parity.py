"""Parity tests: :class:`~lemely.auth.otp.OtpStore` and :class:`~lemely.db.otp_repo.DbOtpStore`
must behave identically wherever both satisfy :class:`~lemely.auth.otp.OtpChallengeStore`
(spec 2026-09-03 §4.4).

This is the guarantee a multi-instance Cloud Run deployment depends on: a code
issued by one instance must be verifiable by another. ``test_otp.py`` covers
the in-memory store's behaviour in isolation; this module parametrises the
*shared* cases — issue/verify, wrong-code counting and lockout, expiry, and
the resend cooldown — over both implementations, plus two Postgres-only tests
(D7.7 hashing, and the concurrent-verify race) that have no in-memory
equivalent because a single-process dict has no concurrency to race.

Skips cleanly when no local Postgres is reachable (mirrors
``test_auth_token_repo.py`` / ``test_teacher_paper_repo.py``); the ``memory``
parametrisation of ``store`` never touches Postgres at all, so it still runs
in an environment with no database.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.auth.otp import OtpChallengeStore, OtpRateLimitError, OtpResult, OtpStore
from lemely.db.base import Base
from lemely.db.models import OtpChallenge
from lemely.db.otp_repo import DbOtpStore
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FrozenClock:
    """A mutable clock: ``advance`` moves it forward for TTL/cooldown tests.

    Matches the shape established for this exact feature family in
    ``tests/test_otp.py`` / ``tests/test_auth_token_repo.py``.
    """

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> _FrozenClock:
    return _FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))


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
def pg_sessionmaker_or_skip(
    request: pytest.FixtureRequest,
) -> Iterator[sessionmaker[Session] | None]:
    """A ``pg_sessionmaker`` that is a no-op for the ``memory`` parametrisation.

    ``store`` (below) is parametrised over both implementations and takes
    this fixture unconditionally, even on the ``memory`` branch that never
    touches it — so this fixture cannot unconditionally require Postgres, or
    the ``memory`` param would skip in an environment with no database too.
    It inspects the *currently running test's* ``store`` parametrisation (via
    ``request.node.callspec``, the only way a sibling fixture can see another
    parametrized fixture's value) and only builds/skips-for real Postgres when
    that value is ``"postgres"`` — or when the test does not parametrize
    ``store`` at all (the two Postgres-only tests below), matching the plain
    ``pg_sessionmaker`` fixture (``test_auth_token_repo.py``) verbatim in that
    case.
    """
    callspec = getattr(request.node, "callspec", None)
    store_param = callspec.params.get("store") if callspec is not None else None
    if store_param == "memory":
        yield None
        return

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


@pytest.fixture(params=["memory", "postgres"])
def store(
    request: pytest.FixtureRequest,
    pg_sessionmaker_or_skip: sessionmaker[Session] | None,
    clock: _FrozenClock,
) -> OtpChallengeStore:
    kwargs = dict(
        clock=clock,
        rng=random.Random(7),
        ttl_seconds=300,
        email_ttl_seconds=600,
        max_attempts=3,
        code_length=6,
        min_resend_seconds=30,
    )
    if request.param == "memory":
        return OtpStore(**kwargs)
    return DbOtpStore(pg_sessionmaker_or_skip, **kwargs)


PHONE = "+201000000000"


def test_issue_then_verify_consumes(store: OtpChallengeStore, clock: _FrozenClock) -> None:
    code = store.issue(PHONE)
    assert store.verify(PHONE, code) is OtpResult.ok
    assert store.verify(PHONE, code) is OtpResult.no_challenge


def test_wrong_code_counts_and_locks_out_after_max(
    store: OtpChallengeStore, clock: _FrozenClock
) -> None:
    code = store.issue(PHONE)
    assert store.verify(PHONE, "000000") is OtpResult.wrong_code
    assert store.verify(PHONE, "000000") is OtpResult.wrong_code
    assert store.verify(PHONE, "000000") is OtpResult.locked_out  # max_attempts=3
    assert store.verify(PHONE, code) is OtpResult.no_challenge


def test_expired_challenge_is_reported_and_removed(
    store: OtpChallengeStore, clock: _FrozenClock
) -> None:
    code = store.issue(PHONE)
    clock.advance(301)
    assert store.verify(PHONE, code) is OtpResult.expired
    assert store.verify(PHONE, code) is OtpResult.no_challenge


def test_resend_inside_cooldown_raises(store: OtpChallengeStore, clock: _FrozenClock) -> None:
    store.issue(PHONE)
    with pytest.raises(OtpRateLimitError):
        store.issue(PHONE)
    clock.advance(31)
    store.issue(PHONE)  # cooldown elapsed: a fresh challenge


def _db_store(sm: sessionmaker[Session], clock: _FrozenClock, **overrides: object) -> DbOtpStore:
    kwargs = dict(
        clock=clock,
        rng=random.Random(7),
        ttl_seconds=300,
        email_ttl_seconds=600,
        max_attempts=3,
        code_length=6,
        min_resend_seconds=0,
    )
    kwargs.update(overrides)
    return DbOtpStore(sm, **kwargs)


def test_code_is_never_stored_in_plaintext(
    pg_sessionmaker_or_skip: sessionmaker[Session], clock: _FrozenClock
) -> None:
    store = _db_store(pg_sessionmaker_or_skip, clock)
    code = store.issue("+201000000000")
    with pg_sessionmaker_or_skip() as s:
        row = s.scalars(select(OtpChallenge)).one()
    assert code not in (row.code_hash, row.address_hash)
    assert row.address_hash == hashlib.sha256(b"+201000000000").hexdigest()


def test_two_concurrent_verifies_yield_one_ok(
    pg_sessionmaker_or_skip: sessionmaker[Session], clock: _FrozenClock
) -> None:
    store = _db_store(pg_sessionmaker_or_skip, clock)
    code = store.issue("+201000000000")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: store.verify("+201000000000", code), range(2)))
    assert sorted(r.value for r in results) == ["no_challenge", "ok"]
