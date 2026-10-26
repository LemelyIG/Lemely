"""Parent-link integrity on the existing routes (SPEC §c.4, decision row 14 = SC-1; CB-1, CB-2).

What changes, and what each test pins:

* ``DELETE /api/student/parent-links/{parent_id}`` records a ``parent_link_events(unlinked)``
  row and a ``parent_unlinked`` outbox row in the delete's transaction, then sends the
  unlinked parent a ``parent_link`` inbox notice after commit. A no-op unlink writes nothing.
* ``POST /api/invites/{code}/redeem`` (parent branch) refuses a fifth parent with 409
  ``parent_limit``; a new link records a ``linked`` event and tells every parent already
  linked (outbox in the transaction, inbox after commit). Re-linking a linked pair stays
  idempotent, and a child who already has more than four links keeps them.
* ``POST /api/auth/parent/signup`` refuses with the same 409 before any account exists.
* The cap holds under concurrency: the child's ``users`` row is locked ``FOR UPDATE``.
* ``ParentLinkService.lock_link_in_session`` (``FOR SHARE``) makes a concurrent unlink wait,
  and ``linked_parent_ids_in_session`` reads the links in the caller's transaction. An unlink
  locks the child row ``FOR NO KEY UPDATE``, so it deadlocks neither with a booking create
  (child row, then link) nor with a link holder inserting rows that reference the child.
* The guards of the four changed routes are exactly the ones SPEC §c.4 names, and their
  dependency trees are the ones they had before this task plus the two notification seams
  (no permission change).

Symbols this task adds are imported inside the tests that need them, so the file still
collects, and its behaviour tests fail on assertions, against the code before the change.
"""

from __future__ import annotations

import random
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.auth.cooldown import CooldownStore
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteError, InviteService, RedeemResult
from lemely.db.models import Invite, Notification, ParentChildLink, User
from lemely.db.models.enums import NotificationType, ParentLinkEvent, Role
from lemely.db.models.tutoring import EmailOutbox, ParentLinkEventLog
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError
from lemely.web.app import create_app
from lemely.web.deps import (
    get_auth_context,
    get_auth_service,
    get_class_service,
    get_invite_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_resend_verification_cooldown_store,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
)
from lemely.web.push import RecordingPushTransport
from tests.auth_fakes import FakeEmailProvider, FakeGoTrueBackend, FakeUserMirror
from tests.tutoring_app import flatten_routes
from tests.tutoring_db import act_as, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.routing import APIRoute
    from sqlalchemy.orm import Session, sessionmaker

#: SPEC §c.4: "Redeemed links capped at 4 per child".
CAP = 4
_ROOT = Path(__file__).resolve().parents[1]
_SPEC = _ROOT / "docs" / "tutoring" / "SPEC.md"
_MATRIX = _ROOT / "tests" / "test_authz_matrix_complete.py"
_LOCK_WAIT_SECONDS = 15.0


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invite_service(sm: sessionmaker[Session]) -> InviteService:
    return InviteService(sm, ClassService(sm), ParentLinkService(sm))


def _client(sm: sessionmaker[Session]) -> TestClient:
    """The real app with every service the four routes use wired to the test database."""
    links = ParentLinkService(sm)
    classes = ClassService(sm)
    invites = InviteService(sm, classes, links)
    notifications = NotificationService(sm, NotificationPreferencesService(sm))
    transport = RecordingPushTransport()
    app = create_app()
    app.dependency_overrides[get_parent_link_service] = lambda: links
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_invite_service] = lambda: invites
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_push_transport] = lambda: transport
    return TestClient(app)


def _link_direct(sm: sessionmaker[Session], parent: uuid.UUID, child: uuid.UUID) -> None:
    """Seed a link row directly, as a link made before the cap existed would be."""
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=child))


def _child_with_parents(sm: sessionmaker[Session], count: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    child = add_user(sm, Role.student, display_name="Maya")
    parents = [add_user(sm, Role.parent) for _ in range(count)]
    for parent in parents:
        _link_direct(sm, parent, child)
    return child, parents


def _linked_parents(sm: sessionmaker[Session], child: uuid.UUID) -> set[uuid.UUID]:
    with sm() as session:
        return set(
            session.scalars(
                sa.select(ParentChildLink.parent_id).where(ParentChildLink.child_id == child)
            )
        )


def _events(sm: sessionmaker[Session]) -> list[tuple[uuid.UUID, uuid.UUID, ParentLinkEvent]]:
    """Every ``(id, parent_id, event)`` in ``parent_link_events``, oldest first."""
    with sm() as session:
        rows = session.execute(
            sa.select(
                ParentLinkEventLog.id, ParentLinkEventLog.parent_id, ParentLinkEventLog.event
            ).order_by(ParentLinkEventLog.created_at, ParentLinkEventLog.id)
        ).all()
    return [(row.id, row.parent_id, row.event) for row in rows]


def _outbox(sm: sessionmaker[Session]) -> list[tuple[uuid.UUID, str, dict[str, object], str]]:
    """Every ``(recipient, template, context, dedupe_key)`` in the email outbox."""
    with sm() as session:
        rows = session.execute(
            sa.select(
                EmailOutbox.recipient_user_id,
                EmailOutbox.template,
                EmailOutbox.context,
                EmailOutbox.dedupe_key,
            )
        ).all()
    return [(row[0], row[1], dict(row[2]), row[3]) for row in rows]


def _inbox(
    sm: sessionmaker[Session],
) -> list[tuple[uuid.UUID, NotificationType, str | None, dict[str, object]]]:
    """Every ``(user_id, type, dedupe_key, payload)`` in the notification inbox."""
    with sm() as session:
        rows = session.execute(
            sa.select(
                Notification.user_id,
                Notification.type,
                Notification.dedupe_key,
                Notification.payload,
            )
        ).all()
    return [(row[0], row[1], row[2], dict(row[3])) for row in rows]


def _lock_waiters(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(
            session.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            or 0
        )


def _wait_for_lock_waiters(sm: sessionmaker[Session], count: int) -> None:
    """Block until ``count`` backends of the test database wait on a lock (bounded)."""
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _lock_waiters(sm) >= count:
            return
        time.sleep(0.05)
    raise AssertionError(f"fewer than {count} sessions waited on a lock")


# ---------------------------------------------------------------------------
# Unlink (DELETE /api/student/parent-links/{parent_id})
# ---------------------------------------------------------------------------


def test_unlink_notifies_unlinked_parent_inbox_and_outbox(sm: sessionmaker[Session]) -> None:
    child, (parent, other) = _child_with_parents(sm, 2)
    client = _client(sm)
    act_as(client, child, Role.student)

    resp = client.delete(f"/api/student/parent-links/{parent}")

    assert resp.status_code == 204
    outbox = _outbox(sm)
    assert len(outbox) == 1, outbox
    [(event_id, event_parent, event)] = _events(sm)
    assert (event_parent, event) == (parent, ParentLinkEvent.unlinked)
    assert outbox == [
        (parent, "parent_unlinked", {"event_id": str(event_id)}, f"parent-link:{event_id}:{parent}")
    ]
    assert _inbox(sm) == [
        (
            parent,
            NotificationType.parent_link,
            f"parent-link:{event_id}",
            {"eventId": str(event_id)},
        )
    ]
    # The parent still linked is told nothing: only the unlinked parent is.
    assert other not in {row[0] for row in _inbox(sm)}


def test_unlink_noop_writes_no_event_and_no_notice(sm: sessionmaker[Session]) -> None:
    child = add_user(sm, Role.student)
    stranger = add_user(sm, Role.parent)
    client = _client(sm)
    act_as(client, child, Role.student)

    resp = client.delete(f"/api/student/parent-links/{stranger}")

    assert resp.status_code == 204
    assert ParentLinkService(sm).unlink(child, stranger) is False
    assert _events(sm) == []
    assert _outbox(sm) == []
    assert _inbox(sm) == []


def test_unlink_writes_link_event(sm: sessionmaker[Session]) -> None:
    child, (parent,) = _child_with_parents(sm, 1)

    removed = ParentLinkService(sm).unlink(child, parent)

    assert removed is True
    assert [(p, e) for _, p, e in _events(sm)] == [(parent, ParentLinkEvent.unlinked)]
    with sm() as session:
        row = session.execute(sa.select(ParentLinkEventLog.child_id)).one()
    assert row.child_id == child
    assert _linked_parents(sm, child) == set()


# ---------------------------------------------------------------------------
# Redeem (POST /api/invites/{code}/redeem, parent branch)
# ---------------------------------------------------------------------------


def test_redeem_notifies_existing_parents(sm: sessionmaker[Session]) -> None:
    child, existing = _child_with_parents(sm, 2)
    newcomer = add_user(sm, Role.parent)
    code = _invite_service(sm).mint_parent_invite(child, reusable=False).code
    client = _client(sm)
    act_as(client, newcomer, Role.parent)

    resp = client.post(f"/api/invites/{code}/redeem")

    assert resp.status_code == 200, resp.text
    assert resp.json()["childId"] == str(child)
    [(event_id, event_parent, event)] = _events(sm)
    assert (event_parent, event) == (newcomer, ParentLinkEvent.linked)
    assert sorted(_outbox(sm), key=lambda row: str(row[0])) == sorted(
        (
            (
                parent,
                "parent_linked",
                {"event_id": str(event_id)},
                f"parent-link:{event_id}:{parent}",
            )
            for parent in existing
        ),
        key=lambda row: str(row[0]),
    )
    inbox = _inbox(sm)
    assert {row[0] for row in inbox} == set(existing)
    assert all(
        row[1:]
        == (NotificationType.parent_link, f"parent-link:{event_id}", {"eventId": str(event_id)})
        for row in inbox
    )
    assert _linked_parents(sm, child) == {*existing, newcomer}


def test_redeem_cap_409_parent_limit_at_four(sm: sessionmaker[Session]) -> None:
    child, existing = _child_with_parents(sm, CAP)
    fifth = add_user(sm, Role.parent)
    invite = _invite_service(sm).mint_parent_invite(child, reusable=False)
    client = _client(sm)
    act_as(client, fifth, Role.parent)

    resp = client.post(f"/api/invites/{invite.code}/redeem")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "parent_limit"
    assert _linked_parents(sm, child) == set(existing)
    assert _events(sm) == []
    assert _outbox(sm) == []
    assert _inbox(sm) == []
    with sm() as session:
        stored = session.get(Invite, invite.id)
    assert stored is not None
    assert stored.redeemed_by is None  # a refused single-use link stays usable


def test_redeem_relink_at_cap_is_idempotent_200(sm: sessionmaker[Session]) -> None:
    child, existing = _child_with_parents(sm, CAP)
    code = _invite_service(sm).get_or_create_parent_code(child).code
    client = _client(sm)
    act_as(client, existing[0], Role.parent)

    resp = client.post(f"/api/invites/{code}/redeem")

    assert resp.status_code == 200, resp.text
    assert resp.json()["childId"] == str(child)
    assert _linked_parents(sm, child) == set(existing)
    assert _events(sm) == []
    assert _outbox(sm) == []
    assert _inbox(sm) == []


def test_existing_children_over_cap_keep_links(sm: sessionmaker[Session]) -> None:
    child, existing = _child_with_parents(sm, CAP + 1)
    newcomer = add_user(sm, Role.parent)
    code = _invite_service(sm).get_or_create_parent_code(child).code
    client = _client(sm)

    act_as(client, newcomer, Role.parent)
    refused = client.post(f"/api/invites/{code}/redeem")
    act_as(client, existing[0], Role.parent)
    relinked = client.post(f"/api/invites/{code}/redeem")

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "parent_limit"
    assert relinked.status_code == 200
    assert _linked_parents(sm, child) == set(existing)

    # Unlinking one still leaves the child at the cap: the newcomer is still refused.
    assert ParentLinkService(sm).unlink(child, existing[-1]) is True
    act_as(client, newcomer, Role.parent)
    assert client.post(f"/api/invites/{code}/redeem").status_code == 409
    assert _linked_parents(sm, child) == set(existing[:-1])


# ---------------------------------------------------------------------------
# Parent signup (POST /api/auth/parent/signup)
# ---------------------------------------------------------------------------


class _PgMirror(FakeUserMirror):
    """An in-memory mirror that also writes the ``users`` row the link's foreign key needs."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._factory = factory

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
        with self._factory.begin() as session:
            if session.get(User, user_id) is None:
                session.add(User(id=user_id, email=email, role=role, display_name=display_name))


def _signup_client(sm: sessionmaker[Session]) -> tuple[TestClient, _PgMirror, FakeGoTrueBackend]:
    settings = Settings()
    mirror = _PgMirror(sm)
    gotrue = FakeGoTrueBackend()
    service = AuthService(
        gotrue=gotrue,
        mirror=mirror,
        sms=MockSmsProvider(),
        otp_store=OtpStore(
            clock=lambda: datetime.now(UTC),
            rng=random.Random(11),
            ttl_seconds=settings.auth.otp_ttl_seconds,
            max_attempts=settings.auth.otp_max_attempts,
            code_length=settings.auth.otp_length,
        ),
        settings=settings,
        email=FakeEmailProvider(),
    )
    signup_cooldown = CooldownStore(clock=lambda: datetime.now(UTC), min_seconds=60)
    resend_cooldown = CooldownStore(clock=lambda: datetime.now(UTC), min_seconds=60)
    client = _client(sm)
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_auth_service] = lambda: service
    overrides[get_user_mirror] = lambda: mirror
    overrides[get_signup_and_reset_cooldown_store] = lambda: signup_cooldown
    overrides[get_resend_verification_cooldown_store] = lambda: resend_cooldown
    return client, mirror, gotrue


def test_parent_signup_at_cap_409_creates_no_user(sm: sessionmaker[Session]) -> None:
    child, existing = _child_with_parents(sm, CAP)
    code = _invite_service(sm).get_or_create_parent_code(child).code
    client, mirror, gotrue = _signup_client(sm)
    email = "fifth-parent@example.com"

    requested = client.post(
        "/api/auth/parent/request-code", json={"email": email, "inviteCode": code}
    )
    assert requested.status_code == 200, requested.text
    verified = client.post(
        "/api/auth/parent/verify-code",
        json={"email": email, "inviteCode": code, "code": requested.json()["devCode"]},
    )
    assert verified.status_code == 200, verified.text

    resp = client.post(
        "/api/auth/parent/signup",
        json={
            "proofToken": verified.json()["proofToken"],
            "password": "pw-123456",
            "acceptedTerms": True,
        },
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "parent_limit"
    assert mirror.get_by_email(email) is None
    with pytest.raises(AuthError):
        gotrue.password_grant(email, "pw-123456")
    with sm() as session:
        assert session.scalar(sa.select(User.id).where(User.email == email)) is None
    assert _linked_parents(sm, child) == set(existing)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_race_two_redeems_at_three_links_exactly_one_succeeds(sm: sessionmaker[Session]) -> None:
    """Two parents redeem two single-use links for a child with three links, together.

    A third session holds the child's ``users`` row so both redemptions are inside their
    transactions, waiting, before either can finish. With the ``FOR UPDATE`` on the child
    row they wait before counting and so serialise: the second counts four and is refused.
    Without it both count three before waiting on the link insert's foreign-key check, and
    both insert.
    """
    child, existing = _child_with_parents(sm, CAP - 1)
    invites = _invite_service(sm)
    racers = [add_user(sm, Role.parent) for _ in range(2)]
    codes = [invites.mint_parent_invite(child, reusable=False).code for _ in racers]
    outcomes: list[object] = [None, None]

    def redeem(index: int) -> None:
        try:
            outcomes[index] = invites.redeem(racers[index], codes[index], caller_role=Role.parent)
        except Exception as exc:  # recorded and asserted below
            outcomes[index] = exc

    threads = [threading.Thread(target=redeem, args=(index,)) for index in range(2)]
    with sm() as holder:
        holder.execute(sa.select(User.id).where(User.id == child).with_for_update())
        for thread in threads:
            thread.start()
        _wait_for_lock_waiters(sm, 2)
        holder.commit()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    successes = [o for o in outcomes if isinstance(o, RedeemResult)]
    failures = [o for o in outcomes if isinstance(o, InviteError)]
    assert len(successes) == 1, outcomes
    assert len(failures) == 1, outcomes
    assert len(_linked_parents(sm, child)) == CAP
    assert _linked_parents(sm, child) >= set(existing)

    from lemely.db.invite_repo import InviteParentLimitError

    assert isinstance(failures[0], InviteParentLimitError)


def test_lock_link_in_session_blocks_concurrent_unlink(sm: sessionmaker[Session]) -> None:
    child, (parent,) = _child_with_parents(sm, 1)
    stranger = add_user(sm, Role.parent)
    service = ParentLinkService(sm)
    removed: list[bool] = []

    def unlink() -> None:
        removed.append(service.unlink(child, parent))

    worker = threading.Thread(target=unlink)
    with sm() as holder:
        assert service.lock_link_in_session(holder, parent, child) is True
        assert service.lock_link_in_session(holder, stranger, child) is False
        worker.start()
        _wait_for_lock_waiters(sm, 1)
        assert worker.is_alive()  # the DELETE waits for the share lock
        assert _linked_parents(sm, child) == {parent}
        holder.commit()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert removed == [True]
    assert _linked_parents(sm, child) == set()


def test_unlink_takes_the_child_row_lock_before_the_link_so_a_booking_cannot_deadlock(
    sm: sessionmaker[Session],
) -> None:
    """A booking create locks the child's ``users`` row, then the link (SPEC §a.4b steps 2, 4).

    An unlink racing it must wait at the child row, not hold the link row while its event
    insert waits for the child row: that order would deadlock against the booking.
    """
    child, (parent,) = _child_with_parents(sm, 1)
    service = ParentLinkService(sm)
    outcomes: list[object] = []

    def unlink() -> None:
        try:
            outcomes.append(service.unlink(child, parent))
        except Exception as exc:  # recorded and asserted below
            outcomes.append(exc)

    worker = threading.Thread(target=unlink)
    with sm() as booking:
        booking.execute(sa.select(User.id).where(User.id == child).with_for_update())
        worker.start()
        _wait_for_lock_waiters(sm, 1)
        assert service.lock_link_in_session(booking, parent, child) is True
        booking.commit()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert outcomes == [True]
    assert _linked_parents(sm, child) == set()


def test_unlink_does_not_deadlock_with_a_link_holder_inserting_a_row_for_the_child(
    sm: sessionmaker[Session],
) -> None:
    """A parent's cancel or complete holds the link ``FOR SHARE``, then writes child rows.

    SPEC §a.4b step 4, then an outbox (or booking) insert whose foreign key to ``users`` takes
    a key-share lock on the child's row. An unlink racing it holds the child row and waits for
    the link. If that child-row lock were ``FOR UPDATE`` it would block the key-share lock and
    Postgres would abort one side with ``DeadlockDetected``; ``FOR NO KEY UPDATE`` lets the
    holder's insert through, the holder commits, and the unlink then completes.
    """
    from lemely.db.email_outbox_repo import enqueue_in_session

    child, (parent,) = _child_with_parents(sm, 1)
    service = ParentLinkService(sm)
    outcomes: list[object] = []

    def unlink() -> None:
        try:
            outcomes.append(service.unlink(child, parent))
        except Exception as exc:  # recorded and asserted below
            outcomes.append(exc)

    worker = threading.Thread(target=unlink)
    with sm() as holder:
        assert service.lock_link_in_session(holder, parent, child) is True
        worker.start()
        _wait_for_lock_waiters(sm, 1)  # the unlink holds the child row, waiting for the link
        queued = enqueue_in_session(
            holder,
            recipient_user_id=child,
            template="parent_linked",
            context={"event_id": uuid.uuid4()},
            dedupe_key=f"deadlock-probe:{child}",
        )
        holder.commit()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert queued is True
    assert outcomes == [True]
    assert _linked_parents(sm, child) == set()
    assert [(p, e) for _, p, e in _events(sm)] == [(parent, ParentLinkEvent.unlinked)]


def test_linked_parent_ids_in_session(sm: sessionmaker[Session]) -> None:
    child, parents = _child_with_parents(sm, 2)
    other_child, (unrelated,) = _child_with_parents(sm, 1)
    late = add_user(sm, Role.parent)
    service = ParentLinkService(sm)

    with sm() as session:
        assert service.linked_parent_ids_in_session(session, child) == sorted(parents)
        assert service.linked_parent_ids_in_session(session, other_child) == [unrelated]
        session.add(ParentChildLink(parent_id=late, child_id=child))
        session.flush()
        # Reads the caller's own transaction, uncommitted link included.
        assert service.linked_parent_ids_in_session(session, child) == sorted([*parents, late])
        session.rollback()

    with sm() as session:
        assert service.linked_parent_ids_in_session(session, child) == sorted(parents)
        assert service.linked_parent_ids_in_session(session, uuid.uuid4()) == []


# ---------------------------------------------------------------------------
# No permission change (SPEC §c.4: guards unchanged)
# ---------------------------------------------------------------------------

#: Guard names as SPEC §c.4 and the matrix write them, by the role set ``require_role`` holds.
_GUARD_NAMES = {frozenset({"student"}): "STUDENT", frozenset({"parent"}): "PARENT"}


def _c4_routes() -> dict[tuple[str, str], str]:
    """``(method, path) -> guard name`` for every SPEC §c.4 row that names its guard."""
    text = _SPEC.read_text(encoding="utf-8")
    section = text.split("### c.4", 1)[1].split("\n---", 1)[0]
    rows = re.findall(
        r"^\| `(GET|POST|PUT|PATCH|DELETE) (/api/[^`]+)` \(([A-Z_]+)[;)]", section, re.MULTILINE
    )
    return {(method, path): guard for method, path, guard in rows}


def _matrix_rows() -> dict[tuple[str, str], str]:
    """The single-line ``EXPECTED`` rows of the authz matrix, read from its source.

    Read as text rather than imported: the module computes its sweeps over every
    route at import time, and the lead adds the S16/S17 rows at integration.
    """
    rows = re.findall(
        r'^\s*\("(GET|POST|PUT|PATCH|DELETE)", "([^"]+)"\): ([A-Z_]+),',
        _MATRIX.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return {(method, path): guard for method, path, guard in rows}


def _wired_guard(route: APIRoute) -> str:
    """The guard wired into ``route``: the role set its ``require_role`` closures allow.

    Independent of the matrix's own reader: walks the dependency tree for the
    ``_guard`` closures ``require_role`` returns and intersects their roles.
    """
    roles: set[str] | None = None
    authenticated = False
    pending = [route.dependant]
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        call = dependant.call
        if call is get_auth_context:
            authenticated = True
        if call is None or getattr(call, "__name__", "") != "_guard" or not call.__closure__:
            continue
        cells = dict(zip(call.__code__.co_freevars, call.__closure__, strict=True))
        allowed = set(cells["allowed_values"].cell_contents)
        roles = allowed if roles is None else roles & allowed
    if roles is not None:
        return _GUARD_NAMES.get(frozenset(roles), ",".join(sorted(roles)))
    return "AUTH_ANY" if authenticated else "PUBLIC"


#: The notification seams the four handlers gained for their after-commit notices (SPEC §c.4:
#: "the after-commit notify calls in the four handlers"). They resolve services, never refuse.
_NOTIFY_DEPENDENCIES = frozenset({"get_notification_service", "get_push_transport"})

#: Every dependency callable of the four routes at ``b540af94^`` (the commit before T09),
#: read from ``create_app()`` on an export of that revision: a guard added or removed
#: anywhere in a route's dependency tree (``require_verified_email``, a second role check)
#: changes its set.
_DEPENDENCIES_BEFORE_T09: dict[tuple[str, str], frozenset[str]] = {
    ("DELETE", "/api/student/parent-links/{parent_id}"): frozenset(
        {
            "HTTPBearer",
            "get_auth_context",
            "get_device_registry",
            "get_parent_link_service",
            "get_settings",
            "require_role.<locals>._guard",
        }
    ),
    ("POST", "/api/invites/{code}/redeem"): frozenset(
        {
            "HTTPBearer",
            "get_auth_context",
            "get_device_registry",
            "get_invite_service",
            "get_settings",
        }
    ),
    ("POST", "/api/student/classes/join"): frozenset(
        {
            "HTTPBearer",
            "get_auth_context",
            "get_class_service",
            "get_device_registry",
            "get_settings",
            "require_role.<locals>._guard",
        }
    ),
    ("POST", "/api/auth/parent/signup"): frozenset(
        {"get_auth_service", "get_invite_service", "get_settings"}
    ),
}


def _dependency_names(route: APIRoute) -> frozenset[str]:
    """The qualified name of every callable in ``route``'s dependency tree (endpoint excluded)."""
    found: set[str] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        call = dependant.call
        if call is not None:
            found.add(getattr(call, "__qualname__", type(call).__qualname__))
    return frozenset(found)


def test_existing_route_guards_unchanged() -> None:
    declared = _c4_routes()
    assert len(declared) == 4, declared  # parent-links DELETE, redeem, classes/join, parent signup
    routes = {
        (method, route.path): route
        for route in flatten_routes(create_app().router)
        for method in route.methods
        if (method, route.path) in declared
    }
    wired = {key: _wired_guard(route) for key, route in routes.items()}
    matrix = _matrix_rows()
    assert wired == declared
    assert {key: matrix.get(key) for key in declared} == declared

    assert set(_DEPENDENCIES_BEFORE_T09) == set(declared)
    dependencies = {
        key: _dependency_names(route) - _NOTIFY_DEPENDENCIES for key, route in routes.items()
    }
    assert dependencies == _DEPENDENCIES_BEFORE_T09
