"""Device/session registry — enforces the max-3-concurrent-devices policy (D1.11).

Every real login (email/password, parent phone-OTP, self-service signup) registers
a :class:`~lemely.db.models.users.Device` row here and carries its id in the minted
access token as a ``session_id`` claim. The auth dependency
(:func:`~lemely.web.deps.get_auth_context`) then checks that row is live on each
request, so revoking it invalidates the session immediately.

Slot accounting:

* A stable, client-supplied ``client_device_id`` (the SPA mints one and stores it
  locally) lets a re-login on the *same* device reuse its row — its ``last_seen_at``
  is refreshed rather than a new slot consumed. A login with no ``client_device_id``
  always mints a fresh device (a distinct session).
* After registering, if the user holds more than :data:`MAX_DEVICES` non-revoked
  devices, the **oldest by ``last_seen_at``** (tie-break ``created_at``) is revoked
  until the cap is met — "logging in on a 4th silently invalidates the oldest".

The service takes a ``sessionmaker`` (mirroring
:class:`~lemely.db.seat_repo.SeatService` and
:class:`~lemely.db.history_repo.DbHistoryStore`) so the pure registry logic is
Postgres-testable without the live auth stack.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.models import Device, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

MAX_DEVICES = 3
"""Maximum concurrent (non-revoked) devices per account."""


class DeviceError(Exception):
    """Base class for device-registry failures."""


class UnknownUserError(DeviceError):
    """No user row exists for the id a login tried to register a device against."""


@dataclass(frozen=True, slots=True)
class DeviceRegistration:
    """The outcome of registering a login: the live session plus any it evicted."""

    session_id: uuid.UUID
    reused: bool
    evicted_session_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DeviceRow:
    """A single non-revoked device as surfaced to a device-management view."""

    device_id: uuid.UUID
    client_device_id: str | None
    device_label: str | None
    user_agent: str | None
    last_seen_at: datetime


class DeviceRegistry:
    """Register logins, evict the oldest beyond the cap, and check liveness."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the registry to a session factory."""
        self._sessionmaker = sessionmaker

    def register_login(
        self,
        user_id: uuid.UUID | str,
        *,
        client_device_id: str | None = None,
        user_agent: str | None = None,
        device_label: str | None = None,
        now: datetime | None = None,
    ) -> DeviceRegistration:
        """Register (or refresh) a device for ``user_id`` and evict the oldest if needed.

        The user row is locked ``FOR UPDATE`` for the duration so two concurrent
        logins for the same account serialise — the second sees the first's device
        and evicts correctly instead of both racing past the cap (mirrors the seat
        service's TOCTOU lock).

        Args:
            user_id: The mirrored ``public.users`` id logging in.
            client_device_id: Stable client fingerprint; when it matches a live
                device for this user that device is reused (not a new slot).
            user_agent: The request ``User-Agent`` (stored for the device UI).
            device_label: Optional human label for the device.
            now: Injectable clock for deterministic tests.

        Raises:
            UnknownUserError: ``user_id`` has no ``public.users`` row.
        """
        uid = _as_uuid(user_id)
        stamp = now or datetime.now(UTC)
        with self._sessionmaker() as session, session.begin():
            if session.get(User, uid, with_for_update=True) is None:
                raise UnknownUserError(f"Unknown user: {uid}")

            device = self._match_existing(session, uid, client_device_id)
            reused = device is not None
            if device is None:
                device = Device(
                    user_id=uid,
                    client_device_id=client_device_id,
                    device_label=device_label,
                    user_agent=user_agent,
                    last_seen_at=stamp,
                )
                session.add(device)
            else:
                device.last_seen_at = stamp
                if user_agent is not None:
                    device.user_agent = user_agent
                if device_label is not None:
                    device.device_label = device_label
            session.flush()  # assign device.id before we evict / return it

            evicted = self._evict_oldest(session, uid, keep_id=device.id, now=stamp)
            return DeviceRegistration(
                session_id=device.id, reused=reused, evicted_session_ids=evicted
            )

    def is_session_live(self, session_id: uuid.UUID | str) -> bool:
        """Return whether the device row for ``session_id`` exists and is not revoked."""
        try:
            sid = _as_uuid(session_id)
        except ValueError:
            return False
        with self._sessionmaker() as session:
            device = session.get(Device, sid)
            return device is not None and device.revoked_at is None

    def active_devices(self, user_id: uuid.UUID | str) -> list[DeviceRow]:
        """Return the user's non-revoked devices, most-recently-seen first."""
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            stmt = (
                select(Device)
                .where(Device.user_id == uid, Device.revoked_at.is_(None))
                .order_by(Device.last_seen_at.desc(), Device.created_at.desc())
            )
            return [
                DeviceRow(
                    device_id=d.id,
                    client_device_id=d.client_device_id,
                    device_label=d.device_label,
                    user_agent=d.user_agent,
                    last_seen_at=d.last_seen_at,
                )
                for d in session.scalars(stmt).all()
            ]

    def revoke(self, user_id: uuid.UUID | str, session_id: uuid.UUID | str) -> bool:
        """Explicitly revoke one of the user's devices (e.g. a "sign out" action).

        Returns ``True`` if a matching live device was revoked, ``False`` if it did
        not exist, belonged to another user, or was already revoked (idempotent).
        """
        uid = _as_uuid(user_id)
        sid = _as_uuid(session_id)
        with self._sessionmaker() as session, session.begin():
            device = session.get(Device, sid)
            if device is None or device.user_id != uid or device.revoked_at is not None:
                return False
            device.revoked_at = datetime.now(UTC)
            return True

    # -- Internals ----------------------------------------------------------

    def _match_existing(
        self, session: Session, uid: uuid.UUID, client_device_id: str | None
    ) -> Device | None:
        """Return the live device for this ``(user, client fingerprint)``, if any."""
        if client_device_id is None:
            return None
        stmt = (
            select(Device)
            .where(
                Device.user_id == uid,
                Device.client_device_id == client_device_id,
                Device.revoked_at.is_(None),
            )
            .order_by(Device.last_seen_at.desc())
            .limit(1)
        )
        return session.scalars(stmt).first()

    def _evict_oldest(
        self, session: Session, uid: uuid.UUID, *, keep_id: uuid.UUID, now: datetime
    ) -> list[uuid.UUID]:
        """Revoke the oldest non-revoked devices until at most :data:`MAX_DEVICES` remain."""
        stmt = (
            select(Device)
            .where(Device.user_id == uid, Device.revoked_at.is_(None))
            .order_by(Device.last_seen_at.asc(), Device.created_at.asc())
        )
        live = list(session.scalars(stmt).all())
        surplus = len(live) - MAX_DEVICES
        evicted: list[uuid.UUID] = []
        for device in live:
            if surplus <= 0:
                break
            if device.id == keep_id:
                continue  # never evict the session we just registered
            device.revoked_at = now
            evicted.append(device.id)
            surplus -= 1
        return evicted


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "MAX_DEVICES",
    "DeviceError",
    "DeviceRegistration",
    "DeviceRegistry",
    "DeviceRow",
    "UnknownUserError",
]
