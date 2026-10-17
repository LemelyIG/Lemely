"""Postgres integration tests for the parent-link model service (D3.11/P3.6a).

Exercises :class:`~lemely.db.parent_repo.ParentLinkService` against a
throwaway database and skips cleanly when no local server is reachable
(mirrors ``tests/test_class_repo.py``, whose ``pg_sessionmaker`` fixture and
seed-helper style this file duplicates verbatim per this repo's convention —
every ``test_*_repo.py`` file carries its own copy rather than sharing one via
conftest). Proves the guarantees D3.11 requires:

* ``link_in_session`` is idempotent (no duplicate link row, no
  ``IntegrityError``) and writes inside whatever transaction the caller
  passes it rather than committing one of its own — proved by rolling that
  transaction back and finding no row survived it.
* ``get_child`` is the authz seam: ``None`` for an unlinked pair, a real row
  for a linked one — including the two-parent/two-child disjoint-link
  regression (a parent must never resolve a child linked only to someone
  else).
* ``unlink`` is idempotent and its effect is visible from both directions
  (the child drops off the parent's list, the parent drops off the child's).
* ``list_parents`` carries a parent's real email, and still falls back to
  the phone for legacy phone-only rows whose email is the synthesised
  placeholder.
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
from lemely.db.parent_repo import _PLACEHOLDER_EMAIL_DOMAIN, ParentLinkService
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


def test_list_parents_carries_email(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The student UI shows a parent's email in place of a phone (spec §5)."""
    child = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent, display_name="Mum")
    _link(pg_sessionmaker, parent_id=parent, child_id=child)

    service = ParentLinkService(pg_sessionmaker)
    parents = service.list_parents(child)

    assert parents[0].email == f"{parent}@example.com"


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


# ── link_in_session ──────────────────────────────────────────────────────────


def test_link_in_session_inserts_one_row_and_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Mirrors the invite service's call site: caller owns the transaction."""
    student = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent, display_name="Mum")

    service = ParentLinkService(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        service.link_in_session(session, parent, student)

    assert service.get_child(parent, student) is not None
    assert _link_row_count(pg_sessionmaker) == 1

    # Redeeming the same invite twice (e.g. a reusable code) must not
    # attempt a duplicate insert or raise IntegrityError.
    with pg_sessionmaker.begin() as session:
        service.link_in_session(session, parent, student)

    assert _link_row_count(pg_sessionmaker) == 1


def test_link_in_session_participates_in_the_callers_transaction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The write must live or die with the caller's transaction, not its own.

    ``test_link_in_session_inserts_one_row_and_is_idempotent`` uses
    ``pg_sessionmaker.begin()``, which always commits on a clean exit — that
    alone can't tell "wrote through the session I was given" apart from "opened
    and committed its own session regardless of what was passed in". Rolling
    back here is the only way to prove ``link_in_session`` never calls
    ``commit()`` itself: if it did, this rollback would have nothing left to
    undo and the row would survive it.
    """
    student = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    service = ParentLinkService(pg_sessionmaker)

    with pg_sessionmaker() as session:
        service.link_in_session(session, parent, student)
        session.rollback()

    assert _link_row_count(pg_sessionmaker) == 0

    # Contrast: a call inside a transaction that *does* commit leaves the row.
    with pg_sessionmaker.begin() as session:
        service.link_in_session(session, parent, student)

    assert _link_row_count(pg_sessionmaker) == 1


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


def test_a_phone_only_parents_name_is_their_phone_not_the_placeholder_email(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A synthesised address must never surface as a person's name (P3.9 chunk d).

    ``AuthService.verify_otp`` mints a phone-only parent with a
    ``phone+20…@parents.lemely.local`` email because ``users.email`` is NOT
    NULL + unique. Falling back to that address showed a student
    "phone+201000000555@parents.lemely.local" where their parent's name should
    be. The link row is seeded directly here (rather than through
    ``link_in_session``, which no longer resolves a parent by phone) because
    this test is about a legacy row's *display*, not how it got linked.
    """
    phone = "+201000000555"
    parent = uuid.uuid4()
    child = _seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker.begin() as session:
        session.add(
            User(
                id=parent,
                email=f"phone+201000000555{_PLACEHOLDER_EMAIL_DOMAIN}",
                role=Role.parent,
                display_name=None,
                phone=phone,
            )
        )
    _link(pg_sessionmaker, parent_id=parent, child_id=child)
    service = ParentLinkService(pg_sessionmaker)

    listed = service.list_parents(child)
    assert [p.display_name for p in listed] == [phone]
    assert all(_PLACEHOLDER_EMAIL_DOMAIN not in p.display_name for p in listed)


def test_placeholder_domain_matches_the_auth_services_synthesised_address() -> None:
    """Pins the two halves that import-linter forbids wiring together directly.

    ``lemely.db`` may not import ``lemely.auth``, so ``parent_repo`` keeps its
    own copy of the placeholder domain. If ``_phone_placeholder_email`` ever
    changes shape, this fails instead of silently reverting the fix above to
    "show the raw placeholder".
    """
    from lemely.auth.service import _phone_placeholder_email

    assert _phone_placeholder_email("+20 100 000 0555").endswith(_PLACEHOLDER_EMAIL_DOMAIN)
