"""AuthService — the identity orchestrator.

Owns the four flows (decisions D1.4 + D1.5). The backend is the sole token issuer:
every access token returned to a client is minted here, self-signed HS256, and
GoTrue's own (ES256) token is discarded rather than forwarded (D1.5).

* :meth:`signup` — admin-creates a GoTrue email/password user, mirrors it into
  ``public.users``, and mints a self-signed access token for the new user.
* :meth:`login` — password-grants against GoTrue to *verify* the credential,
  re-mirrors the user, and mints a self-signed access token (GoTrue's token is
  discarded).
* :meth:`request_otp` — issues a parent phone-OTP challenge and delivers the code
  via the injected :class:`~lemely.auth.sms.SmsProvider`.
* :meth:`verify_otp` — verifies the challenge and mints a self-signed,
  Supabase-compatible access token whose ``app_metadata.role == "parent"``.

Every collaborator (GoTrue backend, user mirror, SMS provider, OTP store, token
signer) is injected so the whole service is swappable in hermetic tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from lemely.auth.otp import OtpResult
from lemely.auth.tokens import mint_access_token, mint_otp_token
from lemely.db.models.enums import Role
from lemely.runtime.errors import AuthError

if TYPE_CHECKING:
    from datetime import datetime

    from lemely.auth.gotrue import GoTrueBackend
    from lemely.auth.mirror import UserMirror
    from lemely.auth.otp import OtpStore
    from lemely.auth.sms import SmsProvider
    from lemely.runtime.config import Settings


class TokenSigner(Protocol):
    """Mints a self-signed access token for a verified OTP session."""

    def __call__(
        self,
        *,
        user_id: uuid.UUID,
        settings: Settings,
        app_role: str,
        phone: str | None = None,
        email: str | None = None,
        ttl_seconds: int = 3600,
        now: datetime | None = None,
    ) -> str:
        """Return a signed access token string."""
        ...


@dataclass(frozen=True, slots=True)
class AuthResult:
    """A successful auth flow: the access token and the mirrored user id/role."""

    access_token: str
    user_id: uuid.UUID
    role: Role
    refresh_token: str | None = None


class AuthService:
    """Coordinates GoTrue, the user mirror, and the phone-OTP lifecycle."""

    def __init__(
        self,
        *,
        gotrue: GoTrueBackend,
        mirror: UserMirror,
        sms: SmsProvider,
        otp_store: OtpStore,
        settings: Settings,
        token_signer: TokenSigner | None = None,
    ) -> None:
        """Wire the service from injected collaborators.

        Args:
            gotrue: Email/password backend (real or fake).
            mirror: ``public.users`` mirror (real DB or in-memory fake).
            sms: OTP delivery provider.
            otp_store: In-memory OTP challenge store.
            settings: Shared settings (JWT secret, audience, auth knobs).
            token_signer: Self-signed-token minter; defaults to
                :func:`~lemely.auth.tokens.mint_otp_token`.
        """
        self._gotrue = gotrue
        self._mirror = mirror
        self._sms = sms
        self._otp_store = otp_store
        self._settings = settings
        self._token_signer: TokenSigner = token_signer or mint_otp_token

    def signup(
        self,
        email: str,
        password: str,
        role: Role,
        display_name: str | None = None,
        phone: str | None = None,
    ) -> AuthResult:
        """Create a GoTrue user, mirror it, and return a self-signed token.

        The user is admin-created (email pre-confirmed) with ``role`` in
        ``user_metadata`` and mirrored 1:1 into ``public.users``. The caller then
        receives a self-signed HS256 access token minted by the backend (D1.5) —
        GoTrue's own token is never forwarded.
        """
        created = self._gotrue.admin_create_user(email, password, role.value, phone)
        self._mirror.upsert(
            created.id,
            email=created.email,
            role=role,
            phone=phone,
            display_name=display_name,
        )
        access_token = self._mint_email_token(
            user_id=created.id, role=role, email=created.email, phone=phone
        )
        return AuthResult(access_token=access_token, user_id=created.id, role=role)

    def login(self, email: str, password: str) -> AuthResult:
        """Verify the credential via GoTrue, re-mirror, and mint a token.

        GoTrue's password grant is used only to *verify* the credential; its
        (ES256) access token is discarded and the backend mints its own HS256
        token (D1.5). The mirrored role is read from the existing ``public.users``
        row when present (GoTrue owns the credential, we own the role); it falls
        back to ``student`` only if the user was never mirrored.
        """
        token = self._gotrue.password_grant(email, password)
        existing = self._mirror.get_by_id(token.user.id)
        role = existing.role if existing is not None else Role.student
        phone = existing.phone if existing is not None else None
        self._mirror.upsert(token.user.id, email=token.user.email, role=role)
        access_token = self._mint_email_token(
            user_id=token.user.id, role=role, email=token.user.email, phone=phone
        )
        return AuthResult(access_token=access_token, user_id=token.user.id, role=role)

    def _mint_email_token(
        self,
        *,
        user_id: uuid.UUID,
        role: Role,
        email: str | None,
        phone: str | None,
    ) -> str:
        """Mint a self-signed HS256 access token for an email/password user."""
        return mint_access_token(
            user_id=user_id,
            settings=self._settings,
            app_role=role.value,
            provider="email",
            phone=phone,
            email=email,
        )

    def request_otp(self, phone: str) -> None:
        """Issue a phone-OTP challenge and deliver the code via SMS.

        The code is never returned; :class:`~lemely.auth.sms.MockSmsProvider`
        logs it for local dev.
        """
        code = self._otp_store.issue(phone)
        self._sms.send_code(phone, code)

    def verify_otp(self, phone: str, code: str) -> AuthResult:
        """Verify an OTP and mint a self-signed parent access token.

        On success the mirrored parent user is looked up (mirrored ``id`` becomes
        the token ``sub``); if no parent row exists yet a fresh id is minted and
        the user is mirrored so the token always has a stable subject.

        Raises:
            AuthError: The OTP is unknown, expired, wrong, or locked out.
        """
        result = self._otp_store.verify(phone, code)
        if result is not OtpResult.ok:
            raise AuthError(f"OTP verification failed: {result.value}")

        existing = self._mirror.get_by_phone(phone)
        if existing is not None:
            user_id = existing.id
            email = existing.email
        else:
            user_id = uuid.uuid4()
            email = None
            self._mirror.upsert(
                user_id, email=_phone_placeholder_email(phone), role=Role.parent, phone=phone
            )

        token = self._token_signer(
            user_id=user_id,
            settings=self._settings,
            app_role=Role.parent.value,
            phone=phone,
            email=email,
        )
        return AuthResult(access_token=token, user_id=user_id, role=Role.parent)


def _phone_placeholder_email(phone: str) -> str:
    """Synthesise a unique placeholder email for a phone-only parent user.

    ``public.users.email`` is NOT NULL + unique; a parent who authenticates via
    phone alone still needs a row, so we derive a stable, unique placeholder from
    the phone number until a real email is captured during onboarding.
    """
    normalised = "".join(ch for ch in phone if ch.isdigit())
    return f"phone+{normalised}@parents.lemely.local"


__all__ = ["AuthResult", "AuthService", "TokenSigner"]
