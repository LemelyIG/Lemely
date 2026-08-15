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


__all__ = [
    "Claims",
    "RefreshClaims",
    "decode_refresh_token",
    "decode_token",
    "mint_access_token",
    "mint_otp_token",
    "mint_refresh_token",
    "refresh_audience",
]
