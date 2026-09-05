"""AuthService — the identity orchestrator.

Owns the four flows (decisions D1.4 + D1.5). The backend is the sole token issuer:
every access token returned to a client is minted here, self-signed HS256, and
GoTrue's own (ES256) token is discarded rather than forwarded (D1.5).

* :meth:`signup` — admin-creates a GoTrue email/password user, mirrors it into
  ``public.users``, and mints a self-signed access token for the new user. Also
  mints and best-effort-sends an email-verification token (D7.4/D7.7), plus a
  typed code sent alongside it (spec §4.4/DS15) so a recipient who cannot
  follow the link has a second route through.
* :meth:`login` — password-grants against GoTrue to *verify* the credential,
  re-mirrors the user, and mints a self-signed access token (GoTrue's token is
  discarded).
* :meth:`request_otp` — issues a parent phone-OTP challenge and delivers the code
  via the injected :class:`~lemely.auth.sms.SmsProvider`.
* :meth:`verify_otp` — verifies the challenge and mints a self-signed,
  Supabase-compatible access token whose ``app_metadata.role == "parent"``.
* :meth:`refresh` — redeems a refresh token for a new access token so a signed-in
  device stays signed in past the (short) access-token lifetime.
* :meth:`verify_email` / :meth:`verify_email_code` / :meth:`resend_verification`
  — redeem (or re-mint) the single-use link token and/or the single-use code
  minted by :meth:`signup`, stamping ``users.email_verified_at`` (D7.4), which
  soft-gates the Gemini spend at ``POST /api/student/correct`` (D7.5) — a route
  this service does not itself define. The link and the code are independent
  credentials verifying the same fact: whichever is redeemed first stamps the
  account, and the other simply expires on its own TTL, unused (spec §4.4).
* :meth:`request_password_reset` / :meth:`reset_password` — the anti-enumeration
  request step and the confirm step, the latter revoking every outstanding
  ``auth_tokens`` row and every device session for the account (D7.7 + D1.11).

Each of the three sign-in flows also hands back a refresh token bound to the
device it just registered; only a flow that registers no device (hermetic tests,
seat-invite signups) returns ``None``, since a refresh token with no device row
behind it could never be revoked.

Every collaborator (GoTrue backend, user mirror, SMS provider, OTP store, token
signer, email provider, auth-token service) is injected so the whole service is
swappable in hermetic tests.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from lemely.auth.otp import OtpChannel, OtpResult
from lemely.auth.tokens import (
    decode_refresh_token,
    mint_access_token,
    mint_otp_token,
    mint_refresh_token,
)
from lemely.db.auth_token_repo import AuthTokenError
from lemely.db.device_repo import RefreshRejectedError
from lemely.db.models.enums import AuthTokenPurpose, Role
from lemely.runtime.errors import AuthError

if TYPE_CHECKING:
    from lemely.auth.email import EmailProvider
    from lemely.auth.gotrue import GoTrueBackend
    from lemely.auth.mirror import UserMirror
    from lemely.auth.otp import OtpChallengeStore
    from lemely.auth.sms import SmsProvider
    from lemely.db.auth_token_repo import AuthTokenService
    from lemely.db.device_repo import DeviceRegistration, DeviceRegistry
    from lemely.runtime.config import Settings

logger = logging.getLogger("lemely.auth.service")


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
    verification_dev_link: str | None = None
    """Set by :meth:`AuthService.signup` under the same D3.16-derived rule as
    the OTP's ``devCode`` (see :meth:`AuthService.request_otp`): the freshly
    minted email-verification link, non-``None`` only when the configured
    :class:`~lemely.auth.email.EmailProvider` does not deliver out of band (or
    none is configured at all). Every other flow that returns an
    :class:`AuthResult` (:meth:`login`, :meth:`verify_otp`, :meth:`refresh`)
    mints no verification token and leaves this ``None``."""
    verification_dev_code: str | None = None
    """The typed code minted alongside :attr:`verification_dev_link` (spec
    §4.4/DS15), under the exact same D3.16 rule: non-``None`` only when the
    configured :class:`~lemely.auth.email.EmailProvider` does not deliver out
    of band. Set together with :attr:`verification_dev_link` — either both are
    populated or neither is, since both are minted in the same branch of
    :meth:`AuthService.signup`."""


class AuthService:
    """Coordinates GoTrue, the user mirror, and the phone-OTP lifecycle."""

    def __init__(
        self,
        *,
        gotrue: GoTrueBackend,
        mirror: UserMirror,
        sms: SmsProvider,
        otp_store: OtpChallengeStore,
        settings: Settings,
        token_signer: TokenSigner | None = None,
        device_registry: DeviceRegistry | None = None,
        email: EmailProvider | None = None,
        tokens: AuthTokenService | None = None,
    ) -> None:
        """Wire the service from injected collaborators.

        Args:
            gotrue: Email/password backend (real or fake).
            mirror: ``public.users`` mirror (real DB or in-memory fake).
            sms: OTP delivery provider.
            otp_store: OTP challenge store — in-memory (:class:`~lemely.auth.otp.OtpStore`,
                tests and the seed script) or Postgres-backed
                (:class:`~lemely.db.otp_repo.DbOtpStore`, ``deps.py``); this
                service depends on the :class:`~lemely.auth.otp.OtpChallengeStore`
                Protocol, never on either concretely.
            settings: Shared settings (JWT secret, audience, auth knobs).
            token_signer: Self-signed-token minter; defaults to
                :func:`~lemely.auth.tokens.mint_otp_token`.
            device_registry: Enforces the 3-device limit (D1.11). When ``None`` (or
                when a flow is called without a :class:`DeviceContext`) no device is
                registered and the minted token carries no ``session_id`` claim.
            email: Verification/reset-link delivery seam (D7.6). Optional and
                defaults to ``None``, matching ``device_registry``, so the many
                hermetic tests built before this feature existed keep constructing
                an :class:`AuthService` without it. ``None`` behaves like a
                provider that never delivers out of band: :meth:`signup`,
                :meth:`resend_verification` and :meth:`request_password_reset`
                mint a token and hand its link straight back as the dev link
                rather than attempting to send anything.
            tokens: Verification/reset token issuer (D7.7). Optional for the same
                reason as ``email``: when ``None``, :meth:`signup` mints no
                verification token (``AuthResult.verification_dev_link`` is
                simply ``None``), and :meth:`verify_email`,
                :meth:`resend_verification`, :meth:`request_password_reset` and
                :meth:`reset_password` each raise or return ``None`` rather than
                reaching for a collaborator that was never wired — see each
                method's own docstring for which.
        """
        self._gotrue = gotrue
        self._mirror = mirror
        self._sms = sms
        self._otp_store = otp_store
        self._settings = settings
        self._token_signer: TokenSigner = token_signer or mint_otp_token
        self._device_registry = device_registry
        self._email = email
        self._tokens = tokens

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
        *,
        accepted_terms: bool = False,
    ) -> AuthResult:
        """Create a GoTrue user, mirror it, and return a self-signed token.

        The user is admin-created **with ``email_confirm=True``** (email
        pre-confirmed) with ``role`` in ``user_metadata`` and mirrored 1:1 into
        ``public.users``. The caller then receives a self-signed HS256 access
        token minted by the backend (D1.5) — GoTrue's own token is never
        forwarded. When a :class:`DeviceContext` is supplied the login is
        registered against the 3-device limit (D1.11).

        ``email_confirm=True`` is deliberate and must not become ``False``
        (D7.4): GoTrue-native confirmation is a *hard* wall — it refuses the
        password grant outright until confirmed — and UI spec §G-07 requires "a
        way to continue into a limited preview of the app rather than a hard
        wall". This service owns verification itself instead, in
        ``users.email_verified_at`` (see :meth:`verify_email`), specifically so
        the password grant always succeeds and a soft gate is possible.

        This method has never itself restricted which ``Role`` it will create —
        including now that D7.1 admits ``Role.teacher`` to self-service signup —
        because *which* roles are self-registrable is an HTTP-surface policy
        enforced one layer up, by the router's allowlist. An authenticated admin
        flow (the seat/invite services) calls this exact method to create
        ``teacher`` and ``school_admin`` accounts too, so this method restricting
        roles itself would be enforcing the same policy in two places, one of
        which is wrong for the admin caller.

        ``accepted_terms`` (D7.11) stamps ``users.terms_accepted_at`` with the
        current time when ``True``, and leaves it untouched (``NULL`` for a new
        row) when ``False`` — this records consent that was actually given
        rather than assuming it. There is no terms-of-service document in this
        repository to have "agreed" to; the consent is to ``/data`` (see the
        ``0021`` migration). Defaults to ``False`` so every caller that predates
        this parameter — the seat-invite flow, ``seed.py``, and tests written
        before D7.11 — keeps its previous behaviour: an account created that way
        was never shown the G-03 consent box, and it would be dishonest to stamp
        a timestamp for consent it never collected.

        A fresh account also gets a best-effort email-verification send (D7.4 /
        D7.7), a link **and** a typed code (spec §4.4/DS15):
        :meth:`_mint_verification_link` mints the link token,
        :meth:`_issue_email_code` issues the code on the OTP store's ``email``
        channel, and :meth:`_try_send_verification` attempts delivery of both
        together, but — unlike :meth:`resend_verification` — **never raises**.
        By the time delivery is attempted, ``admin_create_user`` has already
        succeeded: this address now belongs to a real GoTrue user that can
        never be registered again. Letting
        a delivery failure fail this method would fail a signup whose account in
        fact now exists — permanently orphaned, since the caller has no way back
        in and cannot re-signup with the same address. An account that exists
        with no mail sent is strictly better: :meth:`resend_verification`
        recovers it the moment the caller notices no mail arrived.

        Both ``email`` and ``tokens`` are optional collaborators, exactly like
        ``device_registry``: when either is unconfigured (the many hermetic
        tests built before this feature existed) neither the link nor the
        code is minted, and ``AuthResult.verification_dev_link`` /
        ``verification_dev_code`` are simply ``None`` — the rest of signup's
        contract (create the account, return a working access token) is
        unaffected either way.
        """
        created = self._gotrue.admin_create_user(email, password, role.value, phone)
        self._mirror.upsert(
            created.id,
            email=created.email,
            role=role,
            phone=phone,
            display_name=display_name,
            terms_accepted_at=_utcnow() if accepted_terms else None,
        )
        registration = self._register_device(created.id, device)
        access_token = self._mint_email_token(
            user_id=created.id,
            role=role,
            email=created.email,
            phone=phone,
            session_id=registration.session_id if registration else None,
        )
        verification_dev_link: str | None = None
        verification_dev_code: str | None = None
        if self._tokens is not None:
            link = self._mint_verification_link(self._tokens, created.id)
            code = self._issue_email_code(created.email)
            self._try_send_verification(created.email, link, code)
            verification_dev_link = self._dev_link_for(link)
            verification_dev_code = self._dev_code_for(code)
        return AuthResult(
            access_token=access_token,
            user_id=created.id,
            role=role,
            refresh_token=self._mint_refresh(created.id, registration, "email"),
            verification_dev_link=verification_dev_link,
            verification_dev_code=verification_dev_code,
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

    def verify_email(self, token: str) -> uuid.UUID:
        """Redeem a single-use email-verification token and stamp the account verified.

        Redemption is delegated entirely to the injected
        :class:`~lemely.db.auth_token_repo.AuthTokenService`, whose
        :meth:`~lemely.db.auth_token_repo.AuthTokenService.redeem` already
        enforces single-use, expiry, and (critically) that a token minted for
        ``password_reset`` cannot be redeemed here — see that method's own
        docstring for why a cross-purpose token is indistinguishable from an
        unknown one. Every failure mode it can raise
        (:class:`~lemely.db.auth_token_repo.TokenNotFound`,
        :class:`~lemely.db.auth_token_repo.TokenAlreadyUsed`,
        :class:`~lemely.db.auth_token_repo.TokenExpired`) is collapsed into the
        single :class:`~lemely.runtime.errors.AuthError` every other
        ``AuthService`` failure raises, rather than leaking
        ``lemely.db.auth_token_repo``'s internal exception hierarchy across the
        service boundary — callers of this service (the router) only need to
        know "auth failed", the distinction was for the token service's own
        tests to make.

        Returns:
            The id of the now-verified user.

        Raises:
            AuthError: No verification service is configured, or the token is
                unknown, wrong-purpose, already used, or expired.
        """
        if self._tokens is None:
            raise AuthError("Email verification is not configured.")
        try:
            user_id = self._tokens.redeem(token, AuthTokenPurpose.email_verification)
        except AuthTokenError as exc:
            raise AuthError(f"Email verification failed: {exc}") from exc
        self._mirror.mark_email_verified(user_id, verified_at=_utcnow())
        return user_id

    def verify_email_code(self, user_id: uuid.UUID, code: str) -> uuid.UUID:
        """Verify the caller's email by the code sent beside the link (DS15).

        The address is the caller's own, from the mirror — never a body field —
        so this cannot probe or verify another address. Every failure collapses
        into one :class:`~lemely.runtime.errors.AuthError` (same non-revealing
        rule as :meth:`verify_email`).

        The link and this code are independent credentials: the OTP store's
        ``email`` channel is entirely separate from the ``auth_tokens`` table
        the link's token lives in, so redeeming one never touches the other —
        each expires or is consumed on its own (spec §4.4, "Verification is
        idempotent, so this is harmless").

        Returns:
            The id of the now-verified user.

        Raises:
            AuthError: ``user_id`` names no mirrored user, or the code is
                unknown, expired, wrong, or locked out.
        """
        user = self._mirror.get_by_id(user_id)
        if user is None:
            raise AuthError("Unknown user.")
        result = self._otp_store.verify(user.email, code, channel=OtpChannel.email)
        if result is not OtpResult.ok:
            raise AuthError(f"Email verification failed: {result.value}")
        self._mirror.mark_email_verified(user_id, verified_at=_utcnow())
        return user_id

    def resend_verification(self, user_id: uuid.UUID) -> tuple[str | None, str | None]:
        """Mint a fresh verification token and code for ``user_id`` and (re)send them.

        ``user_id`` is expected to come from the caller's own authenticated
        session (the router reads it from ``AuthContext``, never a request
        body) — there is no address parameter here for the same reason
        :meth:`~lemely.auth.service.AuthService.request_otp`'s callers never
        supply someone else's phone number: this can only ever re-trigger
        verification mail for the account that is asking.

        Unlike :meth:`signup`, a delivery failure here is allowed to
        **propagate**. Rule 4 (see :meth:`signup`) exists to protect against
        stranding a GoTrue user a signup cannot retry; that risk does not exist
        here — the account already fully exists, nothing about it is at risk of
        becoming unreachable, and telling the caller their resend failed is
        strictly more useful than a silent success they have no way to
        discover was empty. Anti-enumeration (rule 2) does not apply either:
        this endpoint is authenticated, so there is no "unknown address" case
        to keep indistinguishable from a known one.

        Returns:
            The ``(dev_link, dev_code)`` pair, each exactly under :meth:`signup`'s
            D3.16 rule: non-``None`` only when the configured
            :class:`~lemely.auth.email.EmailProvider` does not deliver out of
            band (or none is configured).

        Raises:
            AuthError: No verification service is configured, or ``user_id``
                names no mirrored user.
        """
        if self._tokens is None:
            raise AuthError("Email verification is not configured.")
        user = self._mirror.get_by_id(user_id)
        if user is None:
            raise AuthError("Unknown user.")
        link = self._mint_verification_link(self._tokens, user_id)
        code = self._issue_email_code(user.email)
        if self._email is not None:
            # Deliberately NOT swallowed here — see the docstring above for why
            # this call is allowed to raise where `_try_send_verification`
            # (used by `signup`) is not.
            self._email.send_verification(user.email, link, code)
        return self._dev_link_for(link), self._dev_code_for(code)

    def request_password_reset(self, email: str) -> str | None:
        """Mint and send a password-reset token for ``email``, if it exists.

        **Never signals whether the address exists (binding anti-enumeration
        rule, D7).** An unknown address mints nothing and this returns ``None``
        — the exact same shape a *known* address gets back from a real
        (``delivers_out_of_band=True``) provider. There is no raise, no
        different return shape, and (see below) no different behaviour on a
        mail-transport failure for a known address either: all three cases are
        `return None (or the dev link) having done nothing observably
        different`. A caller must never be able to use this method's outcome,
        by any channel, to learn whether ``email`` belongs to an account.

        A known address's delivery failure is swallowed for exactly that
        reason: if sending could raise all the way out of this method, a known
        address whose mail transport is briefly unhealthy would look different
        (an exception, plausibly a 500 at the router) from an unknown address,
        which always returns cleanly. That gap would itself be an enumeration
        oracle, so :meth:`_try_send_password_reset` never raises, same as
        :meth:`signup`'s verification send — a different justification (D7's
        rule 2 here, rule 4 there), the same mechanism.

        Returns:
            The dev link (D3.16 rule, see :meth:`signup`) when ``email`` is
            known and a token was minted; ``None`` both when the address is
            unknown *and* when a real provider is configured and delivered —
            these two cases are indistinguishable by design.
        """
        if self._tokens is None:
            return None
        user = self._mirror.get_by_email(email)
        if user is None:
            return None
        link = self._mint_password_reset_link(self._tokens, user.id)
        self._try_send_password_reset(user.email, link)
        return self._dev_link_for(link)

    def reset_password(self, token: str, new_password: str) -> None:
        """Redeem a reset token, set the new credential, and sign the account out everywhere.

        Three things happen, in order, once the token redeems successfully:

        1. The GoTrue credential is actually changed
           (:meth:`~lemely.auth.gotrue.GoTrueBackend.admin_update_user_password`)
           — this is the step that makes the new password real.
        2. **Every outstanding ``auth_tokens`` row for this user is revoked, for
           BOTH purposes** (``password_reset`` *and* ``email_verification``),
           via :meth:`~lemely.db.auth_token_repo.AuthTokenService.revoke_all`.
           A second copy of this exact reset link (e.g. opened from two tabs)
           must not silently succeed a second time, and an unrelated
           outstanding verification link must not survive a credential change
           either — the account holder forgetting about it is not a reason to
           leave it live.
        3. **Every device row for this user is revoked**, via
           :class:`~lemely.db.device_repo.DeviceRegistry`. The reason someone
           resets a password may be a compromise, so a reset signs the account
           out on every device, not just the one used to complete the reset —
           this is user-visible behaviour the G-06 success screen must state
           plainly (see spec §5 Risks), not a side effect discovered later.

        Step 3 is skipped (not an error) when no ``device_registry`` was
        configured — matching how every other flow in this class treats that
        collaborator as optional.

        Raises:
            AuthError: No verification service is configured, or the token is
                unknown, wrong-purpose, already used, or expired.
        """
        if self._tokens is None:
            raise AuthError("Password reset is not configured.")
        try:
            user_id = self._tokens.redeem(token, AuthTokenPurpose.password_reset)
        except AuthTokenError as exc:
            raise AuthError(f"Password reset failed: {exc}") from exc

        self._gotrue.admin_update_user_password(user_id, new_password)

        self._tokens.revoke_all(user_id, AuthTokenPurpose.password_reset)
        self._tokens.revoke_all(user_id, AuthTokenPurpose.email_verification)

        if self._device_registry is not None:
            for row in self._device_registry.active_devices(user_id):
                self._device_registry.revoke(user_id, row.device_id)

    def _mint_verification_link(self, tokens: AuthTokenService, user_id: uuid.UUID) -> str:
        """Mint an email-verification token under its own TTL and return its link.

        The link is the frontend route with the token embedded
        (``/verify-email/:token``, spec §4.4) rather than a fully-qualified URL:
        there is no configured public origin in ``Settings`` (nothing in this
        codebase needs one yet), so a relative path is what is handed to
        :class:`~lemely.auth.email.EmailProvider` and returned as the dev link
        — exactly what the SPA needs to navigate there directly, and the
        caller's job to prefix an origin if a real provider ever requires one.
        """
        token = tokens.mint(
            user_id,
            AuthTokenPurpose.email_verification,
            ttl_seconds=self._settings.auth.email_verification_ttl_seconds,
        )
        return f"/verify-email/{token}"

    def _mint_password_reset_link(self, tokens: AuthTokenService, user_id: uuid.UUID) -> str:
        """Mint a password-reset token under its own (shorter) TTL and return its link.

        See :meth:`_mint_verification_link` for why this is a relative path
        (``/reset/:token``, spec §4.4) rather than a fully-qualified URL.
        """
        token = tokens.mint(
            user_id,
            AuthTokenPurpose.password_reset,
            ttl_seconds=self._settings.auth.password_reset_ttl_seconds,
        )
        return f"/reset/{token}"

    def _dev_link_for(self, link: str) -> str | None:
        """Return ``link`` iff nothing else can be trusted to have delivered it.

        The D3.16 rule (see :meth:`request_otp`) applied to email: ``None``
        when the configured :class:`~lemely.auth.email.EmailProvider` reports
        ``delivers_out_of_band = True`` (a real provider), because then a live
        credential must never also leak back through the API. Absence of a
        configured provider is treated the same as "does not deliver" — with
        nothing to deliver it, this return value is the only way anyone could
        ever obtain it, and production always wires
        :class:`~lemely.auth.email.MockEmailProvider` unconditionally, so this
        branch matters only to hermetic tests that construct an
        :class:`AuthService` with no ``email`` collaborator at all.
        """
        delivers = self._email.delivers_out_of_band if self._email is not None else False
        return None if delivers else link

    def _dev_code_for(self, code: str) -> str | None:
        """Return ``code`` iff nothing else can be trusted to have delivered it.

        :meth:`_dev_link_for`'s exact rule, applied to the code (spec
        §4.4/DS15): ``None`` only when the configured
        :class:`~lemely.auth.email.EmailProvider` reports
        ``delivers_out_of_band = True``. The two dev values always agree —
        both are gated on the same provider — so they are set together
        everywhere a caller produces an :class:`AuthResult` or the
        ``resend_verification`` tuple.
        """
        delivers = self._email.delivers_out_of_band if self._email is not None else False
        return None if delivers else code

    def _issue_email_code(self, email: str) -> str:
        """Issue a fresh OTP-store challenge for ``email`` on the ``email`` channel.

        This is the code half of DS15's link-and-code pair: a single-use,
        hashed-at-rest (in the Postgres-backed store), independently-expiring
        credential verifying the exact same fact as the link —
        :meth:`verify_email_code` is its only consumer.
        """
        return self._otp_store.issue(email, channel=OtpChannel.email)

    def _try_send_verification(self, email: str, link: str, code: str) -> None:
        """Best-effort delivery of a verification link and code. Never raises.

        See :meth:`signup`'s docstring (rule 4) for why: a delivery failure
        here must not fail a signup whose GoTrue account already exists. A
        ``None`` email provider (unconfigured — hermetic tests) is a silent
        no-op, matching how every other optional collaborator on this class
        behaves when absent.
        """
        if self._email is None:
            return
        try:
            self._email.send_verification(email, link, code)
        except Exception:
            logger.exception(
                "Verification email to %s could not be sent; the account exists "
                "and verification can still be completed via resend.",
                email,
            )

    def _try_send_password_reset(self, email: str, link: str) -> None:
        """Best-effort delivery of a password-reset link. Never raises.

        See :meth:`request_password_reset`'s docstring for why: unlike
        :meth:`_try_send_verification` (which protects against orphaning a
        just-created account, rule 4), this protects the anti-enumeration
        guarantee (rule 2) — a mail-transport exception for a *known* address
        must not surface any differently than the clean, silent return an
        *unknown* address always gets.
        """
        if self._email is None:
            return
        try:
            self._email.send_password_reset(email, link)
        except Exception:
            logger.exception("Password-reset email to %s could not be sent.", email)

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


def _utcnow() -> datetime:
    """Return the current aware UTC datetime (mirrors ``auth_token_repo``'s own)."""
    return datetime.now(UTC)


__all__ = ["AuthResult", "AuthService", "DeviceContext", "TokenSigner"]
