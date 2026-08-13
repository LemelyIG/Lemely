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


class RefreshRejectedError(DeviceError):
    """A refresh token named a device that will not honour it.

    Raised by :meth:`DeviceRegistry.redeem_refresh_token` when the device row is
    unknown, has been revoked (explicit sign-out or eviction past the cap), or no
    longer holds the ``refresh_token_id`` the token carries — the last of which
    means a newer login on that device has superseded it. Deliberately one error
    for all three: the client's only correct response to any of them is to sign
    in again, and distinguishing them would tell an anonymous caller holding a
    stale token which case it hit.
    """


class DeviceLimitReachedError(DeviceError):
    """A login would have evicted a device but was not permitted to (D5.12).

    Raised by :meth:`DeviceRegistry.register_login` when ``allow_eviction`` is
    ``False`` and the account already holds :data:`MAX_DEVICES` live devices that
    the incoming login does not match. Carries the live devices so the caller can
    show the user *what* would be signed out before they confirm — the list is
    read inside the same locked transaction that would have done the evicting, so
    it cannot disagree with what a confirmed retry actually evicts.
    """

    def __init__(self, devices: list[DeviceRow]) -> None:
        """Carry the account's live devices, most-recently-seen first."""
        super().__init__(f"Account already has {len(devices)} signed-in devices.")
        self.devices = devices


@dataclass(frozen=True, slots=True)
class DeviceRegistration:
    """The outcome of registering a login: the live session plus any it evicted."""

    session_id: uuid.UUID
    reused: bool
    refresh_token_id: str = ""
    """The id this login's refresh token must carry to be redeemable.

    Minted inside the registration transaction and written to the device row, so
    a device never exists without one. Re-minted on a *reused* row too: signing
    in again on a device supersedes any refresh token still outstanding for it.
    """
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
        allow_eviction: bool = True,
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
            allow_eviction: When ``False``, a login that would consume a fourth
                slot raises :class:`DeviceLimitReachedError` instead of evicting,
                so the caller can ask the user to confirm first (D5.12). The
                check runs **inside** this method's ``FOR UPDATE`` transaction
                rather than as a preflight query, because two concurrent logins
                asking "would this evict?" separately could both be told no.
            now: Injectable clock for deterministic tests.

        Raises:
            UnknownUserError: ``user_id`` has no ``public.users`` row.
            DeviceLimitReachedError: The cap is reached, this login needs a new
                slot, and ``allow_eviction`` is ``False``. Nothing is written.
        """
        uid = _as_uuid(user_id)
        stamp = now or datetime.now(UTC)
        with self._sessionmaker() as session, session.begin():
            if session.get(User, uid, with_for_update=True) is None:
                raise UnknownUserError(f"Unknown user: {uid}")

            device = self._match_existing(session, uid, client_device_id)
            reused = device is not None
            if device is None and not allow_eviction:
                live = self._live_devices(session, uid)
                if len(live) >= MAX_DEVICES:
                    raise DeviceLimitReachedError([_row(d) for d in live])
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
            # Supersede any refresh token outstanding for this row: a fresh
            # credential was just presented, so the previous one has no further
            # claim. Minted here rather than by the caller so the column and the
            # device row can never disagree — they are written in one transaction.
            refresh_token_id = str(uuid.uuid4())
            device.refresh_token_id = refresh_token_id
            session.flush()  # assign device.id before we evict / return it

            evicted = self._evict_oldest(session, uid, keep_id=device.id, now=stamp)
            return DeviceRegistration(
                session_id=device.id,
                reused=reused,
                refresh_token_id=refresh_token_id,
                evicted_session_ids=evicted,
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

    def redeem_refresh_token(
        self,
        session_id: uuid.UUID | str,
        token_id: str,
        *,
        now: datetime | None = None,
    ) -> uuid.UUID:
        """Authorise one refresh and return the id of the user it belongs to.

        The device row is the sole authority: the token is honoured only while
        that row is live *and* still holds ``token_id``. Every existing way a
        session ends therefore ends its refresh token too — signing the device
        out, evicting it past :data:`MAX_DEVICES`, or logging in on it again
        (which re-mints the id). The caller learns *who* from the return value
        rather than from the token's own ``sub``, so a forged subject cannot
        refresh its way into another account.

        The row is locked ``FOR UPDATE`` so two concurrent redemptions serialise.
        ``last_seen_at`` is advanced on success, keeping an actively-refreshing
        device from drifting to the front of the eviction queue.

        Args:
            session_id: The ``devices`` row named by the token's ``session_id``.
            token_id: The token's ``jti``, matched against ``refresh_token_id``.
            now: Injectable clock for deterministic tests.

        Raises:
            RefreshRejectedError: The device is unknown, revoked, or holds a
                different (newer) refresh token id.
        """
        try:
            sid = _as_uuid(session_id)
        except ValueError as exc:
            raise RefreshRejectedError("Refresh token names no known session") from exc
        stamp = now or datetime.now(UTC)
        with self._sessionmaker() as session, session.begin():
            device = session.get(Device, sid, with_for_update=True)
            if device is None or device.revoked_at is not None:
                raise RefreshRejectedError("Refresh token names no live session")
            # Compared inside the lock, against the row rather than the token, so
            # a token superseded by a concurrent login loses cleanly.
            if not device.refresh_token_id or device.refresh_token_id != token_id:
                raise RefreshRejectedError("Refresh token has been superseded")
            device.last_seen_at = stamp
            return device.user_id

    def active_devices(self, user_id: uuid.UUID | str) -> list[DeviceRow]:
        """Return the user's non-revoked devices, most-recently-seen first."""
        uid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            return [_row(d) for d in self._live_devices(session, uid)]

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

    def _live_devices(self, session: Session, uid: uuid.UUID) -> list[Device]:
        """Return the user's non-revoked devices, most-recently-seen first.

        Shared by :meth:`active_devices` and the ``allow_eviction`` check so the
        list a user confirms against in G-10 and the list they manage in G-11 are
        the same query, ordered the same way.
        """
        stmt = (
            select(Device)
            .where(Device.user_id == uid, Device.revoked_at.is_(None))
            .order_by(Device.last_seen_at.desc(), Device.created_at.desc())
        )
        return list(session.scalars(stmt).all())

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


def _row(device: Device) -> DeviceRow:
    """Project a ``devices`` ORM row onto the read-only view DTO."""
    return DeviceRow(
        device_id=device.id,
        client_device_id=device.client_device_id,
        device_label=device.device_label,
        user_agent=device.user_agent,
        last_seen_at=device.last_seen_at,
    )


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
    "DeviceLimitReachedError",
    "DeviceRegistration",
    "DeviceRegistry",
    "DeviceRow",
    "RefreshRejectedError",
    "UnknownUserError",
]
