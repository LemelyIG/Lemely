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
* :meth:`refresh` — redeems a refresh token for a new access token so a signed-in
  device stays signed in past the (short) access-token lifetime.

Each of the three sign-in flows also hands back a refresh token bound to the
device it just registered; only a flow that registers no device (hermetic tests,
seat-invite signups) returns ``None``, since a refresh token with no device row
behind it could never be revoked.

Every collaborator (GoTrue backend, user mirror, SMS provider, OTP store, token
signer) is injected so the whole service is swappable in hermetic tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from lemely.auth.otp import OtpResult
from lemely.auth.tokens import (
    decode_refresh_token,
    mint_access_token,
    mint_otp_token,
    mint_refresh_token,
)
from lemely.db.device_repo import RefreshRejectedError
from lemely.db.models.enums import Role
from lemely.runtime.errors import AuthError

if TYPE_CHECKING:
    from datetime import datetime

    from lemely.auth.gotrue import GoTrueBackend
    from lemely.auth.mirror import UserMirror
    from lemely.auth.otp import OtpStore
    from lemely.auth.sms import SmsProvider
    from lemely.db.device_repo import DeviceRegistration, DeviceRegistry
    from lemely.runtime.config import Settings


@dataclass(frozen=True, slots=True)
class DeviceContext:
    """Per-login device metadata used to enforce the 3-device limit (D1.11).

    ``client_device_id`` is the stable client fingerprint; ``user_agent`` and
    ``label`` are stored for the device-management view. A login carrying no
    :class:`DeviceContext` (e.g. a seat-invite signup) registers no device and its
    token carries no ``session_id`` claim, so it is exempt from the liveness check.
    """

    client_device_id: str | None = None
    user_agent: str | None = None
    label: str | None = None


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
        session_id: uuid.UUID | None = None,
        ttl_seconds: int | None = None,
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
        device_registry: DeviceRegistry | None = None,
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
            device_registry: Enforces the 3-device limit (D1.11). When ``None`` (or
                when a flow is called without a :class:`DeviceContext`) no device is
                registered and the minted token carries no ``session_id`` claim.
        """
        self._gotrue = gotrue
        self._mirror = mirror
        self._sms = sms
        self._otp_store = otp_store
        self._settings = settings
        self._token_signer: TokenSigner = token_signer or mint_otp_token
        self._device_registry = device_registry

    def _register_device(
        self, user_id: uuid.UUID, device: DeviceContext | None, *, allow_eviction: bool = True
    ) -> DeviceRegistration | None:
        """Register the login's device and return the registration, or ``None``.

        Returns ``None`` (so no ``session_id`` claim is minted, exempting the token
        from the liveness check) when either the registry or the device context is
        absent — e.g. hermetic tests and seat-invite signups.

        With ``allow_eviction=False`` a login that would consume a fourth slot
        raises :class:`~lemely.db.device_repo.DeviceLimitReachedError` and writes
        nothing, letting the caller confirm with the user first (D5.12).
        """
        if self._device_registry is None or device is None:
            return None
        return self._device_registry.register_login(
            user_id,
            client_device_id=device.client_device_id,
            user_agent=device.user_agent,
            device_label=device.label,
            allow_eviction=allow_eviction,
        )

    def _mint_refresh(
        self, user_id: uuid.UUID, registration: DeviceRegistration | None, provider: str
    ) -> str | None:
        """Mint the refresh token for a freshly-registered device, if there is one.

        A session-less flow (hermetic tests, seat-invite signups) gets ``None``:
        a refresh token with no device row behind it could never be revoked, so
        those flows stay short-lived rather than gaining an unrevocable one.
        """
        if registration is None:
            return None
        return mint_refresh_token(
            user_id=user_id,
            settings=self._settings,
            session_id=registration.session_id,
            token_id=registration.refresh_token_id,
            provider=provider,
        )

    def signup(
        self,
        email: str,
        password: str,
        role: Role,
        display_name: str | None = None,
        phone: str | None = None,
        device: DeviceContext | None = None,
    ) -> AuthResult:
        """Create a GoTrue user, mirror it, and return a self-signed token.

        The user is admin-created (email pre-confirmed) with ``role`` in
        ``user_metadata`` and mirrored 1:1 into ``public.users``. The caller then
        receives a self-signed HS256 access token minted by the backend (D1.5) —
        GoTrue's own token is never forwarded. When a :class:`DeviceContext` is
        supplied the login is registered against the 3-device limit (D1.11).
        """
        created = self._gotrue.admin_create_user(email, password, role.value, phone)
        self._mirror.upsert(
            created.id,
            email=created.email,
            role=role,
            phone=phone,
            display_name=display_name,
        )
        registration = self._register_device(created.id, device)
        access_token = self._mint_email_token(
            user_id=created.id,
            role=role,
            email=created.email,
            phone=phone,
            session_id=registration.session_id if registration else None,
        )
        return AuthResult(
            access_token=access_token,
            user_id=created.id,
            role=role,
            refresh_token=self._mint_refresh(created.id, registration, "email"),
        )

    def login(
        self,
        email: str,
        password: str,
        device: DeviceContext | None = None,
        *,
        confirm_device_eviction: bool = False,
    ) -> AuthResult:
        """Verify the credential via GoTrue, re-mirror, and mint a token.

        GoTrue's password grant is used only to *verify* the credential; its
        (ES256) access token is discarded and the backend mints its own HS256
        token (D1.5). The mirrored role is read from the existing ``public.users``
        row when present (GoTrue owns the credential, we own the role); it falls
        back to ``student`` only if the user was never mirrored. When a
        :class:`DeviceContext` is supplied the login registers a device (D1.11).

        A login that would consume a **fourth** device slot raises
        :class:`~lemely.db.device_repo.DeviceLimitReachedError` unless
        ``confirm_device_eviction`` is set — the credential has been verified by
        then, so the caller may show the user which devices would be signed out
        (D5.12) and re-send the login confirmed. Nothing is written on the
        unconfirmed attempt; in particular no device is evicted.
        """
        token = self._gotrue.password_grant(email, password)
        existing = self._mirror.get_by_id(token.user.id)
        role = existing.role if existing is not None else Role.student
        phone = existing.phone if existing is not None else None
        self._mirror.upsert(token.user.id, email=token.user.email, role=role)
        registration = self._register_device(
            token.user.id, device, allow_eviction=confirm_device_eviction
        )
        access_token = self._mint_email_token(
            user_id=token.user.id,
            role=role,
            email=token.user.email,
            phone=phone,
            session_id=registration.session_id if registration else None,
        )
        return AuthResult(
            access_token=access_token,
            user_id=token.user.id,
            role=role,
            refresh_token=self._mint_refresh(token.user.id, registration, "email"),
        )

    def _mint_email_token(
        self,
        *,
        user_id: uuid.UUID,
        role: Role,
        email: str | None,
        phone: str | None,
        session_id: uuid.UUID | None = None,
    ) -> str:
        """Mint a self-signed HS256 access token for an email/password user."""
        return mint_access_token(
            user_id=user_id,
            settings=self._settings,
            app_role=role.value,
            provider="email",
            phone=phone,
            email=email,
            session_id=session_id,
        )

    def request_otp(self, phone: str) -> str | None:
        """Issue a phone-OTP challenge, deliver it, and return it only if nothing else will.

        Returns the code **iff the configured provider does not deliver it out of
        band** (:attr:`~lemely.auth.sms.SmsProvider.delivers_out_of_band`) — i.e.
        only when this API is the sole way to obtain it, which is exactly the
        offline-mock case ``docs/LEMELY_UI_SPEC.md`` §G-05's developer affordance
        exists for. With a real SMS gateway configured this returns ``None`` and
        the code never crosses the wire (D3.16). The gate is the provider's own
        capability, never an environment string.
        """
        code = self._otp_store.issue(phone)
        self._sms.send_code(phone, code)
        return None if self._sms.delivers_out_of_band else code

    def verify_otp(self, phone: str, code: str, device: DeviceContext | None = None) -> AuthResult:
        """Verify an OTP and mint a self-signed parent access token.

        On success the mirrored parent user is looked up (mirrored ``id`` becomes
        the token ``sub``); if no parent row exists yet a fresh id is minted and
        the user is mirrored so the token always has a stable subject. When a
        :class:`DeviceContext` is supplied the login is registered against the
        3-device limit (D1.11).

        Unlike :meth:`login`, a fourth device here still **silently evicts** the
        oldest rather than raising D5.12's confirmation challenge: the OTP code is
        single-use and is consumed by the ``verify`` above, so a challenge the
        caller re-sent confirmed would fail on a spent code and cost the parent a
        second SMS. Scoping the challenge to the email/password path is deliberate
        and is carried as an honest gap, not an oversight.

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

        registration = self._register_device(user_id, device)
        token = self._token_signer(
            user_id=user_id,
            settings=self._settings,
            app_role=Role.parent.value,
            phone=phone,
            email=email,
            session_id=registration.session_id if registration else None,
        )
        return AuthResult(
            access_token=token,
            user_id=user_id,
            role=Role.parent,
            refresh_token=self._mint_refresh(user_id, registration, "phone"),
        )

    def refresh(self, refresh_token: str) -> AuthResult:
        """Redeem a refresh token for a new access token, keeping the session alive.

        The token is verified, then *disbelieved*: the only thing taken from it is
        which device row it names. That row decides whether the session is still
        live and who it belongs to, and the caller's role, email, and phone are
        re-read from ``public.users`` — so a user demoted, renamed, or deleted
        since sign-in gets an access token reflecting that on their next refresh,
        rather than riding the role they held for the refresh token's full
        lifetime. The refresh token itself is returned unchanged: it does not
        rotate (see :meth:`~lemely.db.device_repo.DeviceRegistry.redeem_refresh_token`),
        so two browser tabs refreshing at once cannot invalidate each other.

        Raises:
            AuthError: The token is malformed, expired, not a refresh token, or
                names a session that has been signed out, evicted, or superseded
                — and likewise if the user it belongs to no longer exists.
        """
        claims = decode_refresh_token(refresh_token, self._settings)
        if self._device_registry is None:
            raise AuthError("Refresh is unavailable: no device registry configured")
        try:
            user_id = self._device_registry.redeem_refresh_token(claims.session_id, claims.token_id)
        except RefreshRejectedError as exc:
            raise AuthError(f"Refresh token rejected: {exc}") from exc

        # The registry's answer wins over the token's own `sub`. They cannot
        # disagree without the signing secret, but authority is read from the
        # database here on principle rather than trusted from the credential.
        if str(user_id) != claims.sub:
            raise AuthError("Refresh token subject does not match its session")

        user = self._mirror.get_by_id(user_id)
        if user is None:
            raise AuthError("Refresh token belongs to a user that no longer exists")

        access_token = mint_access_token(
            user_id=user_id,
            settings=self._settings,
            app_role=user.role.value,
            provider=claims.provider,
            phone=user.phone,
            email=user.email,
            session_id=uuid.UUID(claims.session_id),
        )
        return AuthResult(
            access_token=access_token,
            user_id=user_id,
            role=user.role,
            refresh_token=refresh_token,
        )


def _phone_placeholder_email(phone: str) -> str:
    """Synthesise a unique placeholder email for a phone-only parent user.

    ``public.users.email`` is NOT NULL + unique; a parent who authenticates via
    phone alone still needs a row, so we derive a stable, unique placeholder from
    the phone number until a real email is captured during onboarding.
    """
    normalised = "".join(ch for ch in phone if ch.isdigit())
    return f"phone+{normalised}@parents.lemely.local"


__all__ = ["AuthResult", "AuthService", "DeviceContext", "TokenSigner"]
