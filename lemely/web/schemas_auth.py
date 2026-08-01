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
    """Email/password login payload (``deviceId`` — see :class:`SignupRequestDTO`)."""

    email: str
    password: str
    deviceId: str | None = None


class OtpRequestDTO(ApiModel):
    """Request an OTP challenge for a parent phone number."""

    phone: str


class OtpVerifyDTO(ApiModel):
    """Verify an OTP code for a parent phone number (``deviceId`` — see signup)."""

    phone: str
    code: str
    deviceId: str | None = None


class TokenResponseDTO(ApiModel):
    """A minted access token plus the resolved user id and role."""

    accessToken: str
    userId: str
    role: Role
    refreshToken: str | None = None


class OtpRequestResponseDTO(ApiModel):
    """Acknowledgement that an OTP was issued (never carries the code)."""

    status: Literal["sent"] = "sent"


__all__ = [
    "ApiModel",
    "LoginRequestDTO",
    "OtpRequestDTO",
    "OtpRequestResponseDTO",
    "OtpVerifyDTO",
    "Role",
    "SignupRequestDTO",
    "TokenResponseDTO",
]
