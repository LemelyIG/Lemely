"""Parity tests: :class:`~lemely.auth.cooldown.CooldownStore` and
:class:`~lemely.db.cooldown_repo.DbCooldownStore` must behave identically wherever
both satisfy :class:`~lemely.auth.cooldown.CooldownStoreProtocol` (spec 2026-09-03
§4.4).

This is the guarantee a multi-instance Cloud Run deployment depends on: a
resend cooldown one instance stamps must throttle the same key seen by
another. ``test_auth_cooldown.py`` covers the in-memory store's behaviour in
isolation; this module parametrises its six cases over both implementations,
plus two Postgres-only tests (D7.7 hashing, and per-purpose independence)
that have no in-memory equivalent because a single-process dict has no
concurrent-writer story and no notion of "purpose" at all — every
``CooldownStore`` instance is already scoped to one purpose by construction.

Skips cleanly when no local Postgres is reachable (mirrors
``test_otp_store_parity.py`` / ``test_auth_token_repo.py``); the ``memory``
parametrisation of ``store`` never touches Postgres at all, so it still runs
in an environment with no database.
"""

from __future__ import annotations

import hashlib
import threading
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

from lemely.auth.cooldown import CooldownError, CooldownStore, CooldownStoreProtocol
from lemely.db.base import Base
from lemely.db.cooldown_repo import DbCooldownStore
from lemely.db.models import AuthCooldown
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FrozenClock:
    """A mutable clock: ``advance`` moves it forward for window tests.

    Matches the shape established for this exact feature family in
    ``tests/test_auth_cooldown.py`` / ``tests/test_otp_store_parity.py``.
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
    ``store`` at all (the Postgres-only tests below), matching the plain
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
) -> CooldownStoreProtocol:
    if request.param == "memory":
        return CooldownStore(clock=clock, min_seconds=30)
    assert pg_sessionmaker_or_skip is not None  # only None on the "memory" branch above
    return DbCooldownStore(
        pg_sessionmaker_or_skip,
        clock=clock,
        purpose="resend_verification",
        min_seconds=30,
    )


# ---------------------------------------------------------------------------
# The six cases of tests/test_auth_cooldown.py, parametrised over both stores.
# ---------------------------------------------------------------------------


def test_first_call_passes(store: CooldownStoreProtocol, clock: _FrozenClock) -> None:
    store.check_and_stamp("a@example.com")  # no raise


def test_immediate_second_call_raises_with_positive_retry_after(
    store: CooldownStoreProtocol, clock: _FrozenClock
) -> None:
    store.check_and_stamp("a@example.com")
    with pytest.raises(CooldownError) as exc_info:
        store.check_and_stamp("a@example.com")
    assert exc_info.value.retry_after > 0


def test_retry_after_reflects_the_remaining_window(
    store: CooldownStoreProtocol, clock: _FrozenClock
) -> None:
    """Pins the exact contract, not just its sign."""
    store.check_and_stamp("a@example.com")
    clock.advance(5)
    with pytest.raises(CooldownError) as exc_info:
        store.check_and_stamp("a@example.com")
    assert exc_info.value.retry_after == pytest.approx(25.0)


def test_call_after_window_passes(store: CooldownStoreProtocol, clock: _FrozenClock) -> None:
    store.check_and_stamp("a@example.com")
    clock.advance(30)
    store.check_and_stamp("a@example.com")  # cooldown elapsed -> no raise


def test_distinct_keys_do_not_interfere(store: CooldownStoreProtocol, clock: _FrozenClock) -> None:
    store.check_and_stamp("a@example.com")
    store.check_and_stamp("b@example.com")  # different key -> no raise


def test_a_rejected_call_does_not_reset_the_window(
    store: CooldownStoreProtocol, clock: _FrozenClock
) -> None:
    """A rejected attempt must not itself extend the cooldown it was rejected by."""
    store.check_and_stamp("a@example.com")

    clock.advance(10)
    with pytest.raises(CooldownError):
        store.check_and_stamp("a@example.com")  # rejected; must not re-stamp

    clock.advance(20)  # 30s since the *original* stamp, not the rejected one
    store.check_and_stamp("a@example.com")  # now allowed


# ---------------------------------------------------------------------------
# Postgres-only tests: no in-memory equivalent.
# ---------------------------------------------------------------------------


def test_purposes_do_not_interfere(
    pg_sessionmaker_or_skip: sessionmaker[Session], clock: _FrozenClock
) -> None:
    a = DbCooldownStore(
        pg_sessionmaker_or_skip, clock=clock, purpose="signup_and_reset", min_seconds=30
    )
    b = DbCooldownStore(
        pg_sessionmaker_or_skip, clock=clock, purpose="resend_verification", min_seconds=30
    )
    a.check_and_stamp("x@example.com")
    b.check_and_stamp("x@example.com")  # different purpose: passes


def test_key_is_stored_hashed(
    pg_sessionmaker_or_skip: sessionmaker[Session], clock: _FrozenClock
) -> None:
    store = DbCooldownStore(
        pg_sessionmaker_or_skip, clock=clock, purpose="signup_and_reset", min_seconds=30
    )
    store.check_and_stamp("x@example.com")
    with pg_sessionmaker_or_skip() as s:
        row = s.scalars(select(AuthCooldown)).one()
    assert row.key_hash == hashlib.sha256(b"x@example.com").hexdigest()


def test_concurrent_check_and_stamp_for_brand_new_key_never_races(
    pg_sessionmaker_or_skip: sessionmaker[Session], clock: _FrozenClock
) -> None:
    """A never-before-seen ``(purpose, key_hash)`` has no row for a lock to
    hold, so the *first* ``check_and_stamp`` for it cannot be serialised by a
    row lock the way a resend against an existing row can — the insert
    itself has to be the thing the database arbitrates. A
    :class:`threading.Barrier` releases every worker at (as close to) the
    same instant, forcing genuinely concurrent first-time calls against real
    Postgres rather than trusting :class:`~concurrent.futures.ThreadPoolExecutor`
    scheduling to happen to interleave them.

    Against a naive "SELECT, then INSERT or UPDATE in Python" shape, this
    reliably raises an unhandled ``IntegrityError`` (a unique violation on
    ``pk_auth_cooldowns``) for the losing caller instead of the domain's own
    ``CooldownError`` — exactly the bug ``DbOtpStore.issue`` shipped with
    before its fix (``lemely/db/otp_repo.py``).
    """
    n = 16
    store = DbCooldownStore(
        pg_sessionmaker_or_skip, clock=clock, purpose="signup_and_reset", min_seconds=30
    )
    key = "race@example.com"
    barrier = threading.Barrier(n)

    def _check_and_stamp(_: int) -> None | CooldownError:
        barrier.wait()
        try:
            store.check_and_stamp(key)
            return None
        except CooldownError as exc:
            return exc

    with ThreadPoolExecutor(n) as pool:
        results = list(pool.map(_check_and_stamp, range(n)))

    passed = [r for r in results if r is None]
    throttled = [r for r in results if isinstance(r, CooldownError)]
    # No IntegrityError (or anything else) escaped: every outcome is one of
    # these two, and together they account for every caller.
    assert len(passed) + len(throttled) == n
    # The frozen clock means every conflicting write after the first sees a
    # stamp that is not yet past its cooldown, so exactly one caller wins the
    # brand-new row and every other one is correctly throttled -- never a
    # crash.
    assert len(passed) == 1
