"""Postgres integration tests for the parent-link model service (D3.11/P3.6a).

Exercises :class:`~lemely.db.parent_repo.ParentLinkService` against a
throwaway database and skips cleanly when no local server is reachable
(mirrors ``tests/test_class_repo.py``, whose ``pg_sessionmaker`` fixture and
seed-helper style this file duplicates verbatim per this repo's convention —
every ``test_*_repo.py`` file carries its own copy rather than sharing one via
conftest). Proves the guarantees D3.11 requires:

* ``link`` never creates a user — a phone with no ``role=parent`` account is
  a clean :class:`ParentUserNotFoundError`, and the ``users`` row count is
  provably unchanged.
* ``link`` is idempotent (no duplicate link row, no ``IntegrityError``) and
  picks the most-recently-created parent when multiple share a phone,
  mirroring :meth:`~lemely.auth.mirror.DbUserMirror.get_by_phone`.
* ``get_child`` is the authz seam: ``None`` for an unlinked pair, a real row
  for a linked one — including the two-parent/two-child disjoint-link
  regression (a parent must never resolve a child linked only to someone
  else).
* ``unlink`` is idempotent and its effect is visible from both directions
  (the child drops off the parent's list, the parent drops off the child's).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import ParentChildLink, User
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ParentLinkService, ParentUserNotFoundError
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(
    sm: sessionmaker[Session],
    role: Role = Role.student,
    *,
    display_name: str | None = None,
    phone: str | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                display_name=display_name,
                phone=phone,
            )
        )
    return uid


def _link(sm: sessionmaker[Session], *, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))


def _user_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(select(func.count()).select_from(User)) or 0)


def _link_row_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(select(func.count()).select_from(ParentChildLink)) or 0)


# ── linked_children / list_parents / get_child ──────────────────────────────


def test_linked_children_returns_every_child_ordered(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    zed = _seed_user(pg_sessionmaker, Role.student, display_name="Zed")
    amelia = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    _link(pg_sessionmaker, parent_id=parent, child_id=zed)
    _link(pg_sessionmaker, parent_id=parent, child_id=amelia)

    service = ParentLinkService(pg_sessionmaker)
    children = service.linked_children(parent)

    assert [c.display_name for c in children] == ["Amelia", "Zed"]
    assert {c.child_id for c in children} == {zed, amelia}


def test_linked_children_falls_back_to_email_like_roster_entry(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student, display_name=None)
    _link(pg_sessionmaker, parent_id=parent, child_id=child)

    service = ParentLinkService(pg_sessionmaker)
    rows = service.linked_children(parent)

    assert rows[0].display_name == f"{child}@example.com"


def test_list_parents_returns_every_parent_linked_to_a_child(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    child = _seed_user(pg_sessionmaker, Role.student)
    mum = _seed_user(pg_sessionmaker, Role.parent, display_name="Mum", phone="+15550000001")
    dad = _seed_user(pg_sessionmaker, Role.parent, display_name="Dad", phone="+15550000002")
    _link(pg_sessionmaker, parent_id=mum, child_id=child)
    _link(pg_sessionmaker, parent_id=dad, child_id=child)

    service = ParentLinkService(pg_sessionmaker)
    parents = service.list_parents(child)

    assert {p.display_name for p in parents} == {"Mum", "Dad"}
    assert {p.parent_id for p in parents} == {mum, dad}


def test_get_child_returns_none_when_no_link_row_exists(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    stranger_child = _seed_user(pg_sessionmaker, Role.student, display_name="Not Mine")

    service = ParentLinkService(pg_sessionmaker)
    assert service.get_child(parent, stranger_child) is None


def test_get_child_returns_the_row_when_linked(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    _link(pg_sessionmaker, parent_id=parent, child_id=child)

    service = ParentLinkService(pg_sessionmaker)
    row = service.get_child(parent, child)

    assert row is not None
    assert row.display_name == "Amelia"


def test_two_parent_two_child_disjoint_links_never_cross(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Parent A (only linked to child A) must never resolve child B, and vice versa."""
    parent_a = _seed_user(pg_sessionmaker, Role.parent, display_name="Parent A")
    parent_b = _seed_user(pg_sessionmaker, Role.parent, display_name="Parent B")
    child_a = _seed_user(pg_sessionmaker, Role.student, display_name="Child A")
    child_b = _seed_user(pg_sessionmaker, Role.student, display_name="Child B")
    _link(pg_sessionmaker, parent_id=parent_a, child_id=child_a)
    _link(pg_sessionmaker, parent_id=parent_b, child_id=child_b)

    service = ParentLinkService(pg_sessionmaker)

    assert service.get_child(parent_a, child_a) is not None
    assert service.get_child(parent_a, child_b) is None
    assert service.get_child(parent_b, child_b) is not None
    assert service.get_child(parent_b, child_a) is None
    assert [c.child_id for c in service.linked_children(parent_a)] == [child_a]
    assert [c.child_id for c in service.linked_children(parent_b)] == [child_b]


def test_malformed_uuid_raises_value_error(pg_sessionmaker: sessionmaker[Session]) -> None:
    service = ParentLinkService(pg_sessionmaker)
    with pytest.raises(ValueError, match="Identifier must be a UUID"):
        service.get_child("not-a-uuid", "also-not-a-uuid")


# ── link ─────────────────────────────────────────────────────────────────────


def test_link_creates_a_row_and_returns_the_parent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent, display_name="Mum", phone="+15550001111")

    service = ParentLinkService(pg_sessionmaker)
    row = service.link(student, "+15550001111")

    assert row.parent_id == parent
    assert row.display_name == "Mum"
    assert service.get_child(parent, student) is not None
    assert _link_row_count(pg_sessionmaker) == 1


def test_link_is_idempotent_no_duplicate_row(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_user(pg_sessionmaker, Role.parent, phone="+15550002222")

    service = ParentLinkService(pg_sessionmaker)
    first = service.link(student, "+15550002222")
    second = service.link(student, "+15550002222")

    assert first.parent_id == second.parent_id
    assert _link_row_count(pg_sessionmaker) == 1


def test_link_unknown_phone_never_creates_a_user(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    before = _user_count(pg_sessionmaker)

    service = ParentLinkService(pg_sessionmaker)
    with pytest.raises(ParentUserNotFoundError):
        service.link(student, "+15559999999")

    assert _user_count(pg_sessionmaker) == before
    assert _link_row_count(pg_sessionmaker) == 0


def test_link_ignores_a_matching_phone_on_a_non_parent_role(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A student/teacher sharing the phone must not be mistaken for a parent."""
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_user(pg_sessionmaker, Role.teacher, phone="+15553333333")
    before = _user_count(pg_sessionmaker)

    service = ParentLinkService(pg_sessionmaker)
    with pytest.raises(ParentUserNotFoundError):
        service.link(student, "+15553333333")

    assert _user_count(pg_sessionmaker) == before


def test_link_picks_the_most_recently_created_parent_for_a_shared_phone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Mirrors ``DbUserMirror.get_by_phone``'s tie-break so both lookups agree."""
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_user(pg_sessionmaker, Role.parent, display_name="Older", phone="+15554444444")
    newer = _seed_user(pg_sessionmaker, Role.parent, display_name="Newer", phone="+15554444444")

    service = ParentLinkService(pg_sessionmaker)
    row = service.link(student, "+15554444444")

    assert row.parent_id == newer


# ── unlink ───────────────────────────────────────────────────────────────────


def test_unlink_then_relist_shows_the_link_gone_both_directions(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent, display_name="Mum")
    child = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    _link(pg_sessionmaker, parent_id=parent, child_id=child)

    service = ParentLinkService(pg_sessionmaker)
    assert service.get_child(parent, child) is not None

    service.unlink(child, parent)

    assert service.get_child(parent, child) is None
    assert service.linked_children(parent) == []
    assert service.list_parents(child) == []


def test_unlink_absent_link_is_a_silent_no_op(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = _seed_user(pg_sessionmaker, Role.parent)
    child = _seed_user(pg_sessionmaker, Role.student)

    service = ParentLinkService(pg_sessionmaker)
    service.unlink(child, parent)  # never linked — must not raise

    assert _link_row_count(pg_sessionmaker) == 0
