"""Postgres integration tests for the device/session registry (D1.11).

Exercise :class:`~lemely.db.device_repo.DeviceRegistry` against a throwaway
database, skipping cleanly when no local server is reachable (mirrors
``test_seat_repo.py``). They prove the guarantees the 3-device limit requires:

* **Cap** — up to :data:`MAX_DEVICES` (3) concurrent devices; a 4th login evicts
  the oldest by ``last_seen_at`` and no more than that.
* **Dedupe** — a re-login carrying the same ``client_device_id`` reuses that
  device row (not a new slot) and refreshes its ``last_seen_at``.
* **Liveness** — :meth:`is_session_live` is ``True`` for a registered device and
  ``False`` once it is evicted/revoked or for an unknown id.
* **Ownership** — :meth:`revoke` only touches the caller's own devices and is
  idempotent; ``active_devices`` lists a user's live devices newest-first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.device_repo import MAX_DEVICES, DeviceRegistry, UnknownUserError
from lemely.db.models import Device, User
from lemely.db.models.enums import Role
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


def _seed_user(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return uid


def _live_ids(sm: sessionmaker[Session], user_id: uuid.UUID) -> set[uuid.UUID]:
    with sm() as session:
        rows = session.scalars(
            sa.select(Device).where(Device.user_id == user_id, Device.revoked_at.is_(None))
        ).all()
    return {d.id for d in rows}


# ── Cap + eviction ─────────────────────────────────────────────────────────────


def test_three_devices_coexist(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)
    base = datetime(2026, 7, 31, tzinfo=UTC)

    ids = [
        registry.register_login(uid, now=base + timedelta(minutes=i)).session_id
        for i in range(MAX_DEVICES)
    ]

    assert _live_ids(pg_sessionmaker, uid) == set(ids)
    assert all(registry.is_session_live(sid) for sid in ids)


def test_fourth_login_evicts_oldest(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)
    base = datetime(2026, 7, 31, tzinfo=UTC)

    first = registry.register_login(uid, now=base).session_id
    second = registry.register_login(uid, now=base + timedelta(minutes=1)).session_id
    third = registry.register_login(uid, now=base + timedelta(minutes=2)).session_id
    reg4 = registry.register_login(uid, now=base + timedelta(minutes=3))

    # Exactly the oldest was evicted, and only one.
    assert reg4.evicted_session_ids == [first]
    assert not registry.is_session_live(first)
    assert _live_ids(pg_sessionmaker, uid) == {second, third, reg4.session_id}
    assert len(_live_ids(pg_sessionmaker, uid)) == MAX_DEVICES


# ── Client-fingerprint dedupe ───────────────────────────────────────────────────


def test_same_client_device_id_reuses_slot(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)
    base = datetime(2026, 7, 31, tzinfo=UTC)

    first = registry.register_login(uid, client_device_id="phone-A", now=base)
    again = registry.register_login(uid, client_device_id="phone-A", now=base + timedelta(hours=1))

    assert again.reused is True
    assert again.session_id == first.session_id
    assert again.evicted_session_ids == []
    assert _live_ids(pg_sessionmaker, uid) == {first.session_id}
    # last_seen_at was refreshed to the re-login time.
    with pg_sessionmaker() as session:
        device = session.get(Device, first.session_id)
        assert device is not None
        assert device.last_seen_at == base + timedelta(hours=1)


def test_distinct_client_device_ids_are_separate_slots(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)

    a = registry.register_login(uid, client_device_id="phone-A")
    b = registry.register_login(uid, client_device_id="tablet-B")

    assert a.session_id != b.session_id
    assert b.reused is False
    assert _live_ids(pg_sessionmaker, uid) == {a.session_id, b.session_id}


def test_no_client_id_always_mints_a_fresh_device(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)

    first = registry.register_login(uid)
    second = registry.register_login(uid)

    assert first.session_id != second.session_id
    assert second.reused is False


# ── Liveness ────────────────────────────────────────────────────────────────────


def test_is_session_live_false_for_unknown_or_garbage(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    registry = DeviceRegistry(pg_sessionmaker)
    assert registry.is_session_live(uuid.uuid4()) is False
    assert registry.is_session_live("not-a-uuid") is False


# ── Revocation + listing ─────────────────────────────────────────────────────────


def test_revoke_only_touches_own_device_and_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker)
    stranger = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)
    reg = registry.register_login(owner)

    # A stranger cannot revoke the owner's session.
    assert registry.revoke(stranger, reg.session_id) is False
    assert registry.is_session_live(reg.session_id) is True

    assert registry.revoke(owner, reg.session_id) is True
    assert registry.is_session_live(reg.session_id) is False
    # Idempotent: already-revoked returns False, no error.
    assert registry.revoke(owner, reg.session_id) is False


def test_active_devices_lists_live_newest_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    uid = _seed_user(pg_sessionmaker)
    registry = DeviceRegistry(pg_sessionmaker)
    base = datetime(2026, 7, 31, tzinfo=UTC)

    old = registry.register_login(uid, client_device_id="A", now=base)
    new = registry.register_login(
        uid, client_device_id="B", user_agent="Firefox", now=base + timedelta(minutes=5)
    )
    registry.revoke(uid, old.session_id)

    rows = registry.active_devices(uid)
    assert [r.device_id for r in rows] == [new.session_id]
    assert rows[0].client_device_id == "B"
    assert rows[0].user_agent == "Firefox"


# ── Input validation ─────────────────────────────────────────────────────────────


def test_unknown_user_is_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    registry = DeviceRegistry(pg_sessionmaker)
    with pytest.raises(UnknownUserError):
        registry.register_login(uuid.uuid4())


def test_non_uuid_user_is_value_error(pg_sessionmaker: sessionmaker[Session]) -> None:
    registry = DeviceRegistry(pg_sessionmaker)
    with pytest.raises(ValueError, match="must be a UUID"):
        registry.register_login("not-a-uuid")
