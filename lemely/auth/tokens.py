"""Self-signed Supabase-compatible access tokens (HS256), and their refresh tokens.

The backend is the *sole* token issuer to clients (decision D1.5): every access
token handed to the SPA — email/password login AND parent phone-OTP — is minted
here, self-signed with the shared local HS256 ``jwt_secret`` in GoTrue's claim
shape. GoTrue's own access token (which the local Supabase CLI signs with ES256)
is verified for the password then discarded, never forwarded, so there is exactly
one offline-verifiable validation path.

:func:`mint_access_token` produces the token; :func:`mint_otp_token` is the
phone-OTP-flavoured wrapper; :func:`decode_token` verifies the signature and
``aud`` claim and returns typed :class:`Claims`.

Access tokens are short-lived (``auth.access_token_ttl_seconds``), so
:func:`mint_refresh_token` issues the long-lived companion the client redeems at
``POST /api/auth/refresh`` to stay signed in. The two are kept in strictly
separate universes by their ``aud`` claim (:func:`refresh_audience`): a refresh
token presented as a bearer credential fails :func:`decode_token`'s audience
check, so it can never authenticate a route no matter what else it carries. A
refresh token is *only* a claim to a ``devices`` row — it names one in its
``session_id`` and carries the row's current ``refresh_token_id`` as its ``jti``
— so authority to mint a new access token is re-derived from the database on
every redemption, never read out of the token itself.

A third, unrelated kind lives here too: :func:`mint_email_proof_token` /
:func:`decode_email_proof_token` (spec §4). A parent proving an email address
before any account exists has nothing to authenticate as — no user row, no
session — so this is neither an access nor a refresh token; it is a short-lived
receipt that ``email`` completed the signup-code challenge for ``invite_code``,
handed back to the client so the final ``POST /api/auth/parent/signup`` call
can present it instead of the (single-use, already-consumed) code. Same
mechanism as the other two: its own audience (``lemely-email-proof``) and
``typ`` (``"email_proof"``) keep it out of every other token's validator, in
both directions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import jwt

from lemely.runtime.errors import AuthError

if TYPE_CHECKING:
    from lemely.runtime.config import Settings

_ALGORITHM = "HS256"

_REFRESH_TYP = "refresh"
"""Value of a refresh token's ``typ`` claim, checked on decode as belt-and-braces.

The audience separation is what actually keeps the two token kinds apart; this is
a second, explicit signal so a future change to the audience scheme cannot
silently collapse them.
"""

_EMAIL_PROOF_AUDIENCE = "lemely-email-proof"
"""The ``aud`` every email-proof token is minted under (spec §4).

A literal, unlike :func:`refresh_audience`, rather than derived from
``supabase.jwt_audience``: an email-proof token authenticates nothing (there is
no user yet), so it has no relationship to the access-token audience to stay
adjacent to — it only needs to be a value no other token kind uses.
"""

_EMAIL_PROOF_TYP = "email_proof"
"""Value of an email-proof token's ``typ`` claim, the same belt-and-braces
signal :data:`_REFRESH_TYP` is for refresh tokens."""


class TokenError(Exception):
    """Raised by :func:`decode_email_proof_token` on any decode failure.

    Deliberately this module's own exception rather than
    :class:`~lemely.runtime.errors.AuthError`: an email-proof token is not a
    login credential (see the module docstring), so its failures are not an
    *authentication* failure in the sense every other ``AuthError`` site means
    — the caller (the parent-signup route, Task 5) decides what HTTP status
    that becomes, exactly as :class:`~lemely.auth.otp.OtpRateLimitError` and
    :class:`~lemely.auth.cooldown.CooldownError` are raised as their own types
    for their callers to map.
    """


def refresh_audience(settings: Settings) -> str:
    """Return the ``aud`` refresh tokens are minted under.

    Derived from — and deliberately unequal to — the access-token audience, so a
    refresh token fails :func:`decode_token`'s ``audience=`` check and cannot be
    used as a bearer credential.
    """
    return f"{settings.supabase.jwt_audience}:refresh"


@dataclass(frozen=True, slots=True)
class Claims:
    """Decoded, validated claims from a Supabase-compatible access token."""

    sub: str
    role: str
    aud: str
    exp: int
    app_role: str | None = None
    phone: str | None = None
    email: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class EmailProofClaims:
    """Decoded, validated claims from an email-proof token (spec §4).

    ``invite_code`` is carried through unchanged from :func:`mint_email_proof_token`
    so the signup route can re-check the invite is still live at the final step,
    without trusting the client to resend it honestly — the token is the one
    place that binds "this email" to "this invite" together.
    """

    email: str
    invite_code: str


@dataclass(frozen=True, slots=True)
class RefreshClaims:
    """Decoded, validated claims from a refresh token.

    Carries no role, email, or phone on purpose: everything the refreshed access
    token asserts is re-read from ``public.users`` at redemption time, so a role
    changed after sign-in takes effect on the next refresh rather than persisting
    for the token's (long) lifetime.

    ``provider`` is the exception, and belongs here precisely because it is *not*
    mutable state: it records how this session was established (a session opened
    by parent phone-OTP is an OTP session for as long as it lives), so carrying
    it forward is more honest than re-deriving a guess from the user's row.
    """

    sub: str
    session_id: str
    token_id: str
    exp: int
    provider: str = "email"


def mint_access_token(
    *,
    user_id: uuid.UUID,
    settings: Settings,
    app_role: str,
    provider: str,
    phone: str | None = None,
    email: str | None = None,
    session_id: uuid.UUID | None = None,
    ttl_seconds: int | None = None,
    now: datetime | None = None,
) -> str:
    """Mint a self-signed access token mirroring GoTrue's claim shape.

    Carries ``sub``, ``aud`` (from ``supabase.jwt_audience``),
    ``role="authenticated"``, ``exp``, and ``app_metadata.role`` /
    ``app_metadata.provider`` — the same fields GoTrue issues — so the downstream
    validator needs no special case (decision D1.5).

    Args:
        user_id: Mirrored ``public.users`` / ``auth.users`` id (becomes ``sub``).
        settings: Provides the shared ``jwt_secret`` and expected audience.
        app_role: The platform role placed under ``app_metadata.role``.
        provider: The auth provider placed under ``app_metadata.provider``
            (``"email"`` for password login, ``"phone"`` for parent OTP).
        phone: Optional phone number claim.
        email: Optional email claim.
        session_id: Optional device/session id (the ``devices`` row id). When
            present it is carried as a top-level ``session_id`` claim so the auth
            dependency can enforce the 3-device limit by revoking that row (D1.11).
        ttl_seconds: Token lifetime in seconds; defaults to
            ``settings.auth.access_token_ttl_seconds``.
        now: Injectable clock for deterministic tests (defaults to ``now(UTC)``).
    """
    issued = now or datetime.now(UTC)
    ttl = settings.auth.access_token_ttl_seconds if ttl_seconds is None else ttl_seconds
    expires = issued + timedelta(seconds=ttl)
    app_metadata: dict[str, Any] = {"role": app_role, "provider": provider}
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": settings.supabase.jwt_audience,
        "role": "authenticated",
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "app_metadata": app_metadata,
    }
    if phone is not None:
        payload["phone"] = phone
    if email is not None:
        payload["email"] = email
    if session_id is not None:
        payload["session_id"] = str(session_id)
    secret = settings.supabase.jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def mint_otp_token(
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
    """Mint a parent phone-OTP access token (``provider="phone"``).

    Thin wrapper over :func:`mint_access_token` used by the OTP flow and as the
    default :class:`~lemely.auth.service.TokenSigner`.
    """
    return mint_access_token(
        user_id=user_id,
        settings=settings,
        app_role=app_role,
        provider="phone",
        phone=phone,
        email=email,
        session_id=session_id,
        ttl_seconds=ttl_seconds,
        now=now,
    )


def mint_refresh_token(
    *,
    user_id: uuid.UUID,
    settings: Settings,
    session_id: uuid.UUID,
    token_id: str,
    provider: str = "email",
    ttl_seconds: int | None = None,
    now: datetime | None = None,
) -> str:
    """Mint the long-lived refresh token for one signed-in device.

    ``session_id`` is mandatory, unlike on an access token: a refresh token's
    entire authority is "this ``devices`` row is still live", so one with nothing
    to check against would be an unrevocable credential. The flows that mint
    session-less access tokens (hermetic tests, seat-invite signups) therefore
    mint no refresh token at all rather than an unbound one.

    Args:
        user_id: The mirrored ``public.users`` id (becomes ``sub``).
        settings: Provides the shared ``jwt_secret`` and the refresh audience.
        session_id: The ``devices`` row this token is bound to.
        token_id: The row's current ``refresh_token_id``, carried as ``jti``. A
            redemption is accepted only while the row still holds this value, so
            re-logging in on the device supersedes any outstanding token.
        provider: How this session was established (``"email"`` / ``"phone"``),
            carried forward onto each refreshed access token.
        ttl_seconds: Lifetime; defaults to ``settings.auth.refresh_token_ttl_seconds``.
        now: Injectable clock for deterministic tests (defaults to ``now(UTC)``).
    """
    issued = now or datetime.now(UTC)
    ttl = settings.auth.refresh_token_ttl_seconds if ttl_seconds is None else ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": refresh_audience(settings),
        "typ": _REFRESH_TYP,
        "jti": token_id,
        "session_id": str(session_id),
        "provider": provider,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl)).timestamp()),
    }
    secret = settings.supabase.jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_refresh_token(token: str, settings: Settings) -> RefreshClaims:
    """Verify a refresh token and return its typed :class:`RefreshClaims`.

    Validates the signature, the *refresh* audience (so an access token presented
    here is rejected), the ``typ``, and the presence of both the ``session_id``
    binding and the ``jti``. Whether the named device is still live — and whether
    the ``jti`` is still the current one — is the database's call, not this
    function's: see :meth:`~lemely.db.device_repo.DeviceRegistry.redeem_refresh_token`.

    Raises:
        AuthError: The signature is invalid, the token is expired, it is not a
            refresh token, or it is missing its session binding or id.
    """
    secret = settings.supabase.jwt_secret.get_secret_value()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=refresh_audience(settings),
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid refresh token: {exc}") from exc

    if payload.get("typ") != _REFRESH_TYP:
        raise AuthError("Invalid refresh token: not a refresh token")

    sub = payload.get("sub")
    session_id = payload.get("session_id")
    token_id = payload.get("jti")
    exp = payload.get("exp")
    if not sub or not session_id or not token_id or exp is None:
        raise AuthError("Invalid refresh token: missing required claim")
    return RefreshClaims(
        sub=str(sub),
        session_id=str(session_id),
        token_id=str(token_id),
        exp=int(exp),
        provider=str(payload.get("provider") or "email"),
    )


def decode_token(token: str, settings: Settings) -> Claims:
    """Verify a token's signature + audience and return typed :class:`Claims`.

    Raises:
        AuthError: The signature is invalid, the token is expired, the audience
            does not match, or a required claim is missing.
    """
    secret = settings.supabase.jwt_secret.get_secret_value()
    try:
        raw = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=settings.supabase.jwt_audience,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid access token: {exc}") from exc

    payload = raw
    try:
        sub = str(payload["sub"])
        role = str(payload["role"])
        aud = str(payload["aud"])
        exp = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError(f"Access token missing required claim: {exc}") from exc

    app_metadata = payload.get("app_metadata")
    app_role: str | None = None
    if isinstance(app_metadata, dict):
        raw_role = app_metadata.get("role")
        app_role = str(raw_role) if raw_role is not None else None

    phone = payload.get("phone")
    email = payload.get("email")
    session_id = payload.get("session_id")
    return Claims(
        sub=sub,
        role=role,
        aud=aud,
        exp=exp,
        app_role=app_role,
        phone=str(phone) if phone is not None else None,
        email=str(email) if email is not None else None,
        session_id=str(session_id) if session_id is not None else None,
    )


def mint_email_proof_token(
    *,
    email: str,
    invite_code: str,
    settings: Settings,
    ttl_seconds: int = 900,
    now: datetime | None = None,
) -> str:
    """Mint a short-lived receipt that ``email`` completed the signup-code challenge.

    Handed back to the client by ``POST /api/auth/parent/verify-code`` (Task 5)
    so ``POST /api/auth/parent/signup`` can prove the email without re-presenting
    the (single-use, already-consumed) code. Minted under the module's own
    audience and ``typ`` — see the module docstring — so it can never be
    accepted where an access or refresh token is expected, or vice versa.

    Args:
        email: The address that verified. Carried as a plain claim (not a
            ``sub``): there is no user id yet, since the account this proves
            an email for does not exist until signup succeeds.
        invite_code: The parent invite this proof is scoped to, so the
            eventual signup call re-checks the exact same invite is still live
            rather than trusting the client's own claim of which one it used.
        settings: Provides the shared ``jwt_secret``.
        ttl_seconds: Token lifetime; defaults to 900s (fifteen minutes) — long
            enough to fill in the password/name step, short enough that a
            leaked proof token is not a standing liability.
        now: Injectable clock for deterministic tests (defaults to ``now(UTC)``).
    """
    issued = now or datetime.now(UTC)
    expires = issued + timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "email": email,
        "invite_code": invite_code,
        "aud": _EMAIL_PROOF_AUDIENCE,
        "typ": _EMAIL_PROOF_TYP,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    secret = settings.supabase.jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_email_proof_token(token: str, settings: Settings) -> EmailProofClaims:
    """Verify an email-proof token and return its typed :class:`EmailProofClaims`.

    ``options={"require": [...]}`` (final review I-7) makes PyJWT itself
    refuse a token missing any of ``exp``/``iat``/``aud``/``typ`` — without it,
    PyJWT only enforces ``exp`` *when the claim is present*, so a token minted
    with no ``exp`` at all would otherwise decode successfully forever. The
    module's other two decoders never had this gap: :func:`decode_token`
    subscripts ``payload["exp"]`` directly (a missing claim raises
    ``KeyError``, caught below it) and :func:`decode_refresh_token` checks
    ``exp is None`` explicitly. This is defence in depth rather than a live
    hole — :func:`mint_email_proof_token` always sets ``exp``, and forging a
    token without it needs the signing secret — but it closes the one token
    type in this module that lacked the guard its siblings already had.

    Raises:
        TokenError: The signature is invalid, the token is expired, it was not
            minted as an email-proof token (including an access or refresh
            token presented here), or it is missing a required claim.
    """
    secret = settings.supabase.jwt_secret.get_secret_value()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=_EMAIL_PROOF_AUDIENCE,
            options={"require": ["exp", "iat", "aud", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(f"Invalid email proof token: {exc}") from exc

    if payload.get("typ") != _EMAIL_PROOF_TYP:
        raise TokenError("Invalid email proof token: not an email proof token")

    email = payload.get("email")
    invite_code = payload.get("invite_code")
    if not email or not invite_code:
        raise TokenError("Invalid email proof token: missing required claim")
    return EmailProofClaims(email=str(email), invite_code=str(invite_code))


__all__ = [
    "Claims",
    "EmailProofClaims",
    "RefreshClaims",
    "TokenError",
    "decode_email_proof_token",
    "decode_refresh_token",
    "decode_token",
    "mint_access_token",
    "mint_email_proof_token",
    "mint_otp_token",
    "mint_refresh_token",
    "refresh_audience",
]
