"""Hermetic fakes for AuthService tests (no network, no DB).

Shared by ``test_auth_service.py`` and ``test_auth_router.py`` so both exercise
the exact same in-memory GoTrue backend and user mirror.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lemely.auth.gotrue import GoTrueToken, GoTrueUser
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
