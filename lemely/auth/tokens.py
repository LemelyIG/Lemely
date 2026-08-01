"""Self-signed Supabase-compatible access tokens (HS256).

The backend is the *sole* token issuer to clients (decision D1.5): every access
token handed to the SPA — email/password login AND parent phone-OTP — is minted
here, self-signed with the shared local HS256 ``jwt_secret`` in GoTrue's claim
shape. GoTrue's own access token (which the local Supabase CLI signs with ES256)
is verified for the password then discarded, never forwarded, so there is exactly
one offline-verifiable validation path.

:func:`mint_access_token` produces the token; :func:`mint_otp_token` is the
phone-OTP-flavoured wrapper; :func:`decode_token` verifies the signature and
``aud`` claim and returns typed :class:`Claims`.
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


def mint_access_token(
    *,
    user_id: uuid.UUID,
    settings: Settings,
    app_role: str,
    provider: str,
    phone: str | None = None,
    email: str | None = None,
    session_id: uuid.UUID | None = None,
    ttl_seconds: int = 3600,
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
        ttl_seconds: Token lifetime in seconds.
        now: Injectable clock for deterministic tests (defaults to ``now(UTC)``).
    """
    issued = now or datetime.now(UTC)
    expires = issued + timedelta(seconds=ttl_seconds)
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
    ttl_seconds: int = 3600,
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


__all__ = ["Claims", "decode_token", "mint_access_token", "mint_otp_token"]
