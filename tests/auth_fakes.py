"""Hermetic fakes for AuthService tests (no network, no DB).

Shared by ``test_auth_service.py`` and ``test_auth_router.py`` so both exercise
the exact same in-memory GoTrue backend, user mirror, device registry,
auth-token service, and email provider.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from lemely.auth.gotrue import GoTrueToken, GoTrueUser
from lemely.db.auth_token_repo import TokenAlreadyUsed, TokenExpired, TokenNotFound
from lemely.db.device_repo import DeviceRegistration, DeviceRow, RefreshRejectedError
from lemely.db.models.enums import AuthTokenPurpose, Role
from lemely.runtime.errors import AuthError

if TYPE_CHECKING:
    from collections.abc import Callable


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

    def admin_update_user_password(self, user_id: uuid.UUID, password: str) -> None:
        for account in self._by_email.values():
            if account.user_id == user_id:
                account.password = password
                return
        raise AuthError(f"GoTrue admin-update-password failed (404): unknown user {user_id}")


@dataclass
class _MirroredUser:
    id: uuid.UUID
    email: str
    role: Role
    phone: str | None = None
    display_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    terms_accepted_at: datetime | None = None
    email_verified_at: datetime | None = None


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
        terms_accepted_at: datetime | None = None,
    ) -> None:
        existing = self.rows.get(user_id)
        if existing is None:
            self.rows[user_id] = _MirroredUser(
                id=user_id,
                email=email,
                role=role,
                phone=phone,
                display_name=display_name,
                terms_accepted_at=terms_accepted_at,
            )
        else:
            existing.email = email
            existing.role = role
            if phone is not None:
                existing.phone = phone
            if display_name is not None:
                existing.display_name = display_name
            if terms_accepted_at is not None:
                existing.terms_accepted_at = terms_accepted_at

    def get_by_id(self, user_id: uuid.UUID) -> _MirroredUser | None:
        return self.rows.get(user_id)

    def get_by_phone(self, phone: str) -> _MirroredUser | None:
        matches = [u for u in self.rows.values() if u.phone == phone]
        if not matches:
            return None
        return max(matches, key=lambda u: u.created_at)

    def get_by_email(self, email: str) -> _MirroredUser | None:
        return next((u for u in self.rows.values() if u.email == email), None)

    def mark_email_verified(self, user_id: uuid.UUID, *, verified_at: datetime) -> None:
        existing = self.rows.get(user_id)
        if existing is not None:
            existing.email_verified_at = verified_at


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

    def active_devices(self, user_id: uuid.UUID | str) -> list[DeviceRow]:
        """Return the user's non-revoked devices — added for D7's
        ``AuthService.reset_password``, which enumerates every live device to
        revoke it (rule 3: a password reset signs the account out everywhere).
        Real device metadata (label, user-agent, last-seen) is not modelled;
        these tests only need which sessions are live and their ids.
        """
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id)
        return [
            DeviceRow(
                device_id=cast("uuid.UUID", sid),
                client_device_id=cast("str | None", row["client_device_id"]),
                device_label=None,
                user_agent=None,
                last_seen_at=datetime.now(UTC),
            )
            for sid, row in self.rows.items()
            if row["user_id"] == uid and row["revoked"] is False
        ]


@dataclass
class _FakeTokenRow:
    user_id: uuid.UUID
    purpose: AuthTokenPurpose
    expires_at: datetime
    used_at: datetime | None = None


class FakeAuthTokenService:
    """In-memory stand-in for :class:`~lemely.db.auth_token_repo.AuthTokenService`.

    Implements the same public surface (``mint``/``redeem``/``revoke_all``,
    including the per-call ``ttl_seconds`` override on ``mint``) so
    :class:`~lemely.auth.service.AuthService`'s own orchestration — which
    purpose gets minted under which TTL, which failure becomes an
    :class:`~lemely.runtime.errors.AuthError`, which link comes back as the
    dev link — is unit-testable without a live database, exactly as
    :class:`FakeDeviceRegistry` above stands in for
    :class:`~lemely.db.device_repo.DeviceRegistry`.

    Deliberately does **not** model hashed storage or ``SELECT ... FOR
    UPDATE`` locking: those guarantees are the entire point of the real
    :class:`~lemely.db.auth_token_repo.AuthTokenService` and are proven
    against a real Postgres in ``tests/test_auth_token_repo.py``. This fake
    raises the real service's own exception classes (imported, never
    reimplemented), so ``AuthService``'s ``except AuthTokenError`` handling is
    exercised against the genuine types it will see in production.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._default_ttl_seconds = ttl_seconds
        self.rows: dict[str, _FakeTokenRow] = {}

    def mint(
        self,
        user_id: uuid.UUID,
        purpose: AuthTokenPurpose,
        *,
        ttl_seconds: int | None = None,
    ) -> str:
        token = f"fake-token-{uuid.uuid4()}"
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        self.rows[token] = _FakeTokenRow(
            user_id=user_id,
            purpose=purpose,
            expires_at=self._clock() + timedelta(seconds=ttl),
        )
        return token

    def redeem(self, token: str, purpose: AuthTokenPurpose) -> uuid.UUID:
        row = self.rows.get(token)
        # Purpose is part of the lookup, matching the real service's rule 2:
        # a wrong-purpose token is indistinguishable from an unknown one.
        if row is None or row.purpose is not purpose:
            raise TokenNotFound("No live token matches this token and purpose.")
        if row.used_at is not None:
            raise TokenAlreadyUsed("Token has already been redeemed.")
        if self._clock() >= row.expires_at:
            raise TokenExpired("Token has expired.")
        row.used_at = self._clock()
        return row.user_id

    def revoke_all(self, user_id: uuid.UUID, purpose: AuthTokenPurpose) -> None:
        now = self._clock()
        for row in self.rows.values():
            if row.user_id == user_id and row.purpose is purpose and row.used_at is None:
                row.used_at = now


@dataclass
class FakeEmailProvider:
    """In-memory :class:`~lemely.auth.email.EmailProvider` fake for hermetic tests.

    Records every call instead of sending or logging anything, so a test can
    assert exactly what would have been delivered and to whom.
    ``delivers_out_of_band`` is constructor-settable (unlike the real
    :class:`~lemely.auth.email.MockEmailProvider`, which hardcodes ``False``)
    so both directions of D3.16's dev-link rule are exercisable from one
    fake: construct with the default to stand in for the offline mock, or
    with ``delivers_out_of_band=True`` to stand in for a real provider and
    prove the dev link disappears (mirrors ``_DeliveringSmsProvider`` in
    ``tests/test_auth_service.py``, which does the same for the analogous OTP
    rule).

    ``raise_on_send``, if set, makes both send methods raise instead of
    recording — for the tests proving a delivery failure never fails the
    operation that triggered it (D7's binding rule, stated on
    :meth:`~lemely.auth.service.AuthService.signup`).
    """

    delivers_out_of_band: bool = False
    raise_on_send: bool = False
    sent_verifications: list[tuple[str, str, str]] = field(default_factory=list)
    sent_resets: list[tuple[str, str]] = field(default_factory=list)

    def send_verification(self, email: str, link: str, code: str) -> None:
        if self.raise_on_send:
            raise RuntimeError("simulated verification-email delivery failure")
        self.sent_verifications.append((email, link, code))

    def send_password_reset(self, email: str, link: str) -> None:
        if self.raise_on_send:
            raise RuntimeError("simulated password-reset-email delivery failure")
        self.sent_resets.append((email, link))
