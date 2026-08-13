"""Hermetic fakes for AuthService tests (no network, no DB).

Shared by ``test_auth_service.py`` and ``test_auth_router.py`` so both exercise
the exact same in-memory GoTrue backend, user mirror, and device registry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from lemely.auth.gotrue import GoTrueToken, GoTrueUser
from lemely.db.device_repo import DeviceRegistration, RefreshRejectedError
from lemely.db.models.enums import Role
from lemely.runtime.errors import AuthError


@dataclass
class _Account:
    user_id: uuid.UUID
    email: str
    password: str
    role: str


class FakeGoTrueBackend:
    """In-memory GoTrue backend: stores accounts and issues opaque tokens."""

    def __init__(self) -> None:
        self._by_email: dict[str, _Account] = {}

    def admin_create_user(
        self,
        email: str,
        password: str,
        role: str,
        phone: str | None = None,
    ) -> GoTrueUser:
        if email in self._by_email:
            raise AuthError(f"GoTrue admin-create failed (422): user already exists: {email}")
        account = _Account(uuid.uuid4(), email, password, role)
        self._by_email[email] = account
        return GoTrueUser(id=account.user_id, email=email)

    def password_grant(self, email: str, password: str) -> GoTrueToken:
        account = self._by_email.get(email)
        if account is None or account.password != password:
            raise AuthError("GoTrue password-grant failed (400): invalid credentials")
        return GoTrueToken(
            access_token=f"gotrue-access-{account.user_id}",
            refresh_token=f"gotrue-refresh-{account.user_id}",
            user=GoTrueUser(id=account.user_id, email=email),
        )


@dataclass
class _MirroredUser:
    id: uuid.UUID
    email: str
    role: Role
    phone: str | None = None
    display_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeUserMirror:
    """In-memory ``public.users`` mirror keyed by user id."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, _MirroredUser] = {}

    def upsert(
        self,
        user_id: uuid.UUID,
        email: str,
        role: Role,
        phone: str | None = None,
        display_name: str | None = None,
    ) -> None:
        existing = self.rows.get(user_id)
        if existing is None:
            self.rows[user_id] = _MirroredUser(
                id=user_id,
                email=email,
                role=role,
                phone=phone,
                display_name=display_name,
            )
        else:
            existing.email = email
            existing.role = role
            if phone is not None:
                existing.phone = phone
            if display_name is not None:
                existing.display_name = display_name

    def get_by_id(self, user_id: uuid.UUID) -> _MirroredUser | None:
        return self.rows.get(user_id)

    def get_by_phone(self, phone: str) -> _MirroredUser | None:
        matches = [u for u in self.rows.values() if u.phone == phone]
        if not matches:
            return None
        return max(matches, key=lambda u: u.created_at)


class FakeDeviceRegistry:
    """In-memory stand-in for :class:`~lemely.db.device_repo.DeviceRegistry`.

    Implements the slice the auth flows depend on — registering a login, minting
    and redeeming the device-bound refresh token id, liveness, and revocation —
    with the same semantics as the Postgres implementation, whose own guarantees
    (the 3-device cap, ``FOR UPDATE`` serialisation, eviction ordering) are proven
    against a real database in ``test_device_repo.py``. Deliberately does **not**
    model the cap: these tests are about the refresh lifecycle, and a fake that
    silently evicted would make failures ambiguous.
    """

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, dict[str, object]] = {}

    def register_login(
        self,
        user_id: uuid.UUID,
        *,
        client_device_id: str | None = None,
        user_agent: str | None = None,
        device_label: str | None = None,
        allow_eviction: bool = True,
        now: datetime | None = None,
    ) -> DeviceRegistration:
        del user_agent, device_label, allow_eviction, now
        existing = next(
            (
                sid
                for sid, row in self.rows.items()
                if row["user_id"] == user_id
                and client_device_id is not None
                and row["client_device_id"] == client_device_id
                and row["revoked"] is False
            ),
            None,
        )
        session_id = existing or uuid.uuid4()
        # Re-minted on reuse, exactly as the real registry does, so a re-login
        # supersedes any refresh token still outstanding for the device.
        token_id = str(uuid.uuid4())
        self.rows[session_id] = {
            "user_id": user_id,
            "client_device_id": client_device_id,
            "refresh_token_id": token_id,
            "revoked": False,
        }
        return DeviceRegistration(
            session_id=session_id, reused=existing is not None, refresh_token_id=token_id
        )

    def redeem_refresh_token(
        self, session_id: uuid.UUID | str, token_id: str, *, now: datetime | None = None
    ) -> uuid.UUID:
        del now
        try:
            sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)
        except ValueError as exc:
            raise RefreshRejectedError("Refresh token names no known session") from exc
        row = self.rows.get(sid)
        if row is None or row["revoked"] is True:
            raise RefreshRejectedError("Refresh token names no live session")
        if row["refresh_token_id"] != token_id:
            raise RefreshRejectedError("Refresh token has been superseded")
        return cast("uuid.UUID", row["user_id"])

    def is_session_live(self, session_id: uuid.UUID | str) -> bool:
        try:
            sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)
        except ValueError:
            return False
        row = self.rows.get(sid)
        return row is not None and row["revoked"] is False

    def revoke(self, user_id: uuid.UUID | str, session_id: uuid.UUID | str) -> bool:
        sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)
        row = self.rows.get(sid)
        if row is None or row["user_id"] != user_id or row["revoked"] is True:
            return False
        row["revoked"] = True
        return True
