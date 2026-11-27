"""Database and web helpers shared by the tutoring test modules (T06 review R4).

Not a test module (no ``test_`` prefix, so pytest does not collect it). Each
test module still defines its own ``tutoring_db``/``sm``/``client`` fixtures from
these helpers, because a fixture imported by name would be redefined by the
parameter that uses it.

* :func:`tutoring_database` builds one throwaway ``create_all`` database per
  module (the tutoring models install ``btree_gist`` themselves);
  :func:`emptied_after` empties it after every test.
* :func:`count_statements` collects the statements sent inside a block, for the
  SPEC §e.3 query budget.
* ``add_*`` seed users, subjects, tutor profiles and blocks directly, bypassing
  the repositories under test.
* :func:`tutoring_client` mounts the T06 routers through
  ``tests.tutoring_app.app_with_routers`` (a lane never edits ``lemely/web/app.py``)
  and wires them to the test database; :func:`act_as` and :func:`anonymous` set
  the caller.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.tutor_ratings import bayesian_score
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.academic import Subject
from lemely.db.models.enums import Role, TutorListingState
from lemely.db.models.tutoring import (
    TutorAvailabilityRule,
    TutoringBlock,
    TutorProfile,
    TutorSubject,
)
from lemely.db.models.users import User
from lemely.db.tutor_directory_repo import TutorDirectoryRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.runtime.config import DatabaseSettings
from lemely.web.deps import AuthContext, get_auth_context, get_user_mirror
from lemely.web.deps_tutoring import get_tutor_directory_repo, get_tutor_profile_repo
from lemely.web.routers import tutor_profile, tutoring_directory, tutoring_public
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from decimal import Decimal

import_all_models()

NOW = datetime.now(UTC)
_UNSET = object()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@contextmanager
def tutoring_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
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
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table that references users or subjects."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, subjects CASCADE"))


@contextmanager
def count_statements(factory: sessionmaker[Session]) -> Iterator[list[str]]:
    """Collect every statement sent to the database inside the block."""
    engine = factory.kw["bind"]
    seen: list[str] = []

    def on_execute(*args: object) -> None:
        seen.append(str(args[2]))

    sa.event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        sa.event.remove(engine, "before_cursor_execute", on_execute)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def add_user(
    factory: sessionmaker[Session],
    role: Role | str = Role.student,
    *,
    verified: bool = True,
    display_name: str | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=Role(role),
                display_name=display_name,
                email_verified_at=NOW - timedelta(days=60) if verified else None,
            )
        )
    return uid


def add_subject(
    factory: sessionmaker[Session], code: str | None = None, name: str = "Mathematics"
) -> str:
    code = code or f"S{uuid.uuid4().hex[:7]}"
    with factory.begin() as session:
        session.add(Subject(code=code, name=name))
    return code


@dataclass(frozen=True)
class SeededTutor:
    profile_id: uuid.UUID
    user_id: uuid.UUID


def add_tutor(
    factory: sessionmaker[Session],
    *,
    state: str = "listed",
    paused: bool = False,
    first_name: str = "Sara",
    initial: str | None = "M",
    headline: str = "IGCSE Mathematics, patient and exam focused",
    bio: str = "",
    qualification_note: str | None = None,
    other_mode_note: str | None = None,
    subjects: Sequence[str] = (),
    modes: Sequence[str] = ("virtual",),
    area: str = "cairo",
    rating: tuple[int, int] = (0, 0),
    rank: Decimal | None = None,
    first_listed_at: object = _UNSET,
    indexable: bool = True,
    rules: Sequence[tuple[int, int, int]] = ((4, 1020, 1200),),
    verified: bool = True,
    documents_seen: bool = False,
) -> SeededTutor:
    user_id = add_user(factory, Role.teacher, verified=verified)
    profile_id = uuid.uuid4()
    if first_listed_at is _UNSET:
        first_listed_at = NOW - timedelta(days=30) if state == "listed" else None
    with factory.begin() as session:
        session.add(
            TutorProfile(
                id=profile_id,
                user_id=user_id,
                public_first_name=first_name,
                public_last_initial=initial,
                headline=headline,
                bio=bio,
                qualification_note=qualification_note,
                offers_virtual="virtual" in modes,
                offers_in_person="in_person" in modes,
                offers_other="other" in modes,
                other_mode_note=other_mode_note,
                area_code=area,
                listing_state=TutorListingState(state),
                paused_at=NOW - timedelta(days=1) if paused else None,
                closed_at=NOW - timedelta(days=1) if state == "closed" else None,
                submitted_at=NOW - timedelta(days=40) if state != "draft" else None,
                first_listed_at=first_listed_at,
                indexable=indexable,
                rating_sum=rating[0],
                rating_count=rating[1],
                rank_score=rank if rank is not None else bayesian_score(*rating),
                documents_seen_at=NOW - timedelta(days=20) if documents_seen else None,
            )
        )
        session.flush()
        for code in subjects:
            session.add(TutorSubject(tutor_profile_id=profile_id, subject_code=code))
        for day, start, end in rules:
            session.add(
                TutorAvailabilityRule(
                    tutor_profile_id=profile_id, iso_weekday=day, start_minute=start, end_minute=end
                )
            )
    return SeededTutor(profile_id=profile_id, user_id=user_id)


def add_block(
    factory: sessionmaker[Session],
    blocker: uuid.UUID,
    blocked: uuid.UUID,
    *,
    removed: bool = False,
) -> None:
    with factory.begin() as session:
        session.add(
            TutoringBlock(
                blocker_user_id=blocker,
                blocked_user_id=blocked,
                removed_at=NOW if removed else None,
            )
        )


def set_block_removed(
    factory: sessionmaker[Session], blocker: uuid.UUID, blocked: uuid.UUID
) -> None:
    with factory.begin() as session:
        row = session.get(TutoringBlock, (blocker, blocked))
        assert row is not None
        row.removed_at = NOW


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


class DbMirror:
    """The one ``UserMirror`` method ``require_verified_email`` reads, over the test database."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        with self._factory() as session:
            return session.get(User, user_id)


def tutoring_client(factory: sessionmaker[Session]) -> TestClient:
    """The three T06 routers on a fresh app, wired to the test database."""
    app = app_with_routers(tutoring_public.router, tutoring_directory.router, tutor_profile.router)
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(factory)
    app.dependency_overrides[get_tutor_directory_repo] = lambda: TutorDirectoryRepository(factory)
    app.dependency_overrides[get_user_mirror] = lambda: DbMirror(factory)
    return TestClient(app)


def act_as(client: TestClient, user_id: uuid.UUID, role: Role | str) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[attr-defined]
        user_id=str(user_id), role=Role(role).value
    )


def anonymous(client: TestClient) -> None:
    client.app.dependency_overrides.pop(get_auth_context, None)  # type: ignore[attr-defined]


def json_keys(value: object) -> set[str]:
    """Every object key anywhere in a decoded JSON value."""
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= json_keys(item)
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys |= json_keys(item)
        return keys
    return set()
