"""``users.email_verified_at`` keeps the **first** verification instant (lead decision, T05 review).

Tutor outcome statistics count a student only if their email was verified at or before
their first session (ADR-T04, ``core.tutor_outcomes.is_outcome_eligible``). That rule reads
``email_verified_at``, so a later re-verification (the link and the code are independent
credentials, and a resend mints new ones) must not move it forward: the first instant is
the fact. :meth:`lemely.auth.mirror.DbUserMirror.mark_email_verified` therefore writes only
while the column is ``NULL``.

Runs :class:`~lemely.auth.mirror.DbUserMirror` against a throwaway database, through
``Settings`` pointed at it, and the resend case through a real
:class:`~lemely.auth.service.AuthService` on that mirror.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.auth.mirror import DbUserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.session import get_engine
from lemely.runtime.config import DatabaseSettings, Settings
from tests.auth_fakes import FakeAuthTokenService, FakeEmailProvider, FakeGoTrueBackend

if TYPE_CHECKING:
    from collections.abc import Iterator

FIRST = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
LATER = FIRST + timedelta(days=40)


@pytest.fixture
def db_settings() -> Iterator[tuple[Settings, sessionmaker[Session]]]:
    """``Settings`` whose database is a fresh throwaway one, plus a sessionmaker on it."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    data = Settings().model_dump()
    data["database"]["url"] = url
    settings = Settings.model_validate(data)
    try:
        Base.metadata.create_all(engine)
        yield settings, sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        # DbUserMirror re-points the process-wide engine at this database; point it back.
        get_engine(Settings())
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _seed(factory: sessionmaker[Session], verified_at: datetime | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=Role.student,
                email_verified_at=verified_at,
            )
        )
    return uid


def _verified_at(factory: sessionmaker[Session], user_id: uuid.UUID) -> datetime | None:
    with factory() as session:
        return session.scalar(sa.select(User.email_verified_at).where(User.id == user_id))


def test_first_verification_sets_email_verified_at(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    user = _seed(factory)

    DbUserMirror(settings).mark_email_verified(user, verified_at=FIRST)

    assert _verified_at(factory, user) == FIRST


def test_second_verification_keeps_the_first_instant(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    mirror = DbUserMirror(settings)
    user = _seed(factory)
    untouched = _seed(factory)

    mirror.mark_email_verified(user, verified_at=FIRST)
    mirror.mark_email_verified(user, verified_at=LATER)
    mirror.mark_email_verified(uuid.uuid4(), verified_at=LATER)  # unknown user: a no-op

    assert _verified_at(factory, user) == FIRST
    assert _verified_at(factory, untouched) is None


def test_resend_verification_for_verified_user_leaves_it(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    """A resend, and redeeming what it sent (link and code), keep the first instant."""
    settings, factory = db_settings
    tokens = FakeAuthTokenService()
    service = AuthService(
        gotrue=FakeGoTrueBackend(),
        mirror=DbUserMirror(settings),
        sms=MockSmsProvider(),
        otp_store=OtpStore(
            clock=lambda: datetime.now(UTC),
            rng=random.Random(5),
            ttl_seconds=settings.auth.otp_ttl_seconds,
            max_attempts=settings.auth.otp_max_attempts,
            code_length=settings.auth.otp_length,
            min_resend_seconds=0,
        ),
        settings=settings,
        email=FakeEmailProvider(),
        tokens=tokens,
    )
    user = _seed(factory, verified_at=FIRST)

    dev_link, dev_code = service.resend_verification(user)
    assert _verified_at(factory, user) == FIRST

    assert dev_link is not None
    assert dev_code is not None
    service.verify_email(dev_link.rsplit("/", 1)[-1])
    service.verify_email_code(user, dev_code)

    assert _verified_at(factory, user) == FIRST
