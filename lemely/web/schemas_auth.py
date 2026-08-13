"""API DTOs for the auth endpoints (``/api/auth/*``).

Request/response models for signup, login, and the two-step parent phone-OTP
flow. Field names are camelCase to match the frontend contract, mirroring the
other ``schemas_*.py`` modules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Role = Literal["student", "parent", "teacher", "school_admin", "platform_admin"]


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SignupRequestDTO(ApiModel):
    """Email/password signup payload.

    ``deviceId`` is the stable client fingerprint the SPA mints once and stores
    locally; when supplied the login is registered against the 3-device limit and
    a re-login on the same device reuses its slot (D1.11).
    """

    email: str
    password: str
    role: Role
    displayName: str | None = None
    phone: str | None = None
    deviceId: str | None = None


class LoginRequestDTO(ApiModel):
    """Email/password login payload (``deviceId`` — see :class:`SignupRequestDTO`).

    ``confirmDeviceEviction`` is the second half of the D5.12 handshake: a login
    that would consume a fourth device slot answers **409** with the account's
    signed-in devices and mints nothing, and the client re-sends the same login
    with this flag set once the user has confirmed the sign-out.
    """

    email: str
    password: str
    deviceId: str | None = None
    confirmDeviceEviction: bool = False


class OtpRequestDTO(ApiModel):
    """Request an OTP challenge for a parent phone number."""

    phone: str


class OtpVerifyDTO(ApiModel):
    """Verify an OTP code for a parent phone number (``deviceId`` — see signup)."""

    phone: str
    code: str
    deviceId: str | None = None


class RefreshRequestDTO(ApiModel):
    """Redeem a refresh token for a new access token.

    Deliberately the only field: the endpoint is unauthenticated (the access token
    it exists to replace is expired by definition) and takes no user id — who the
    caller is comes from the device row the token names, never from the request.
    """

    refreshToken: str


class TokenResponseDTO(ApiModel):
    """A minted access token plus the resolved user id and role.

    ``refreshToken`` is present on every real sign-in and is echoed back unchanged
    by ``/auth/refresh`` (refresh tokens do not rotate). It is ``None`` only for
    the flows that register no device and so have nothing to bind one to.
    """

    accessToken: str
    userId: str
    role: Role
    refreshToken: str | None = None


class OtpRequestResponseDTO(ApiModel):
    """Acknowledgement that an OTP was issued.

    ``devCode`` is the §G-05 developer affordance (D3.16) and is populated **only**
    when the configured :class:`~lemely.auth.sms.SmsProvider` reports
    ``delivers_out_of_band = False`` — i.e. when nothing reached the handset and
    this response is the only way to obtain the code. With a real SMS gateway
    configured it is always ``None`` and no live code crosses the wire. It is a
    capability gate, not an environment check; the UI must render it in an
    explicitly-labelled developer panel, never as ordinary product copy.
    """

    status: Literal["sent"] = "sent"
    devCode: str | None = None


__all__ = [
    "ApiModel",
    "LoginRequestDTO",
    "OtpRequestDTO",
    "OtpRequestResponseDTO",
    "OtpVerifyDTO",
    "RefreshRequestDTO",
    "Role",
    "SignupRequestDTO",
    "TokenResponseDTO",
]
