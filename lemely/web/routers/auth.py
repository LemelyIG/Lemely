"""Authentication endpoints under ``/api/auth``.

Thin HTTP layer over :class:`~lemely.auth.service.AuthService`: signup and login
delegate to GoTrue email/password, and the two OTP routes drive the parent
phone-OTP lifecycle. Domain :class:`~lemely.runtime.errors.AuthError` maps to a
400/401 ``HTTPException`` so credential/OTP failures never surface as a 500.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these
# type imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.auth.otp import OtpRateLimitError
from lemely.auth.service import AuthResult, AuthService
from lemely.db.models.enums import Role
from lemely.runtime.errors import AuthError
from lemely.web.deps import get_auth_service
from lemely.web.schemas_auth import (
    LoginRequestDTO,
    OtpRequestDTO,
    OtpRequestResponseDTO,
    OtpVerifyDTO,
    SignupRequestDTO,
    TokenResponseDTO,
)

router = APIRouter(prefix="/api")

# Self-service signup may only create a plain student account. Elevated roles
# (teacher / school_admin / platform_admin) are privileged and MUST NOT be
# obtainable by an anonymous caller — otherwise anyone could POST role=
# "platform_admin" and mint an admin token (D1.7). Those accounts are created by
# an authenticated admin via the seat/invite flow (later task) and gated behind
# the manual-activation flag. Parents authenticate via phone-OTP, not signup.
_SELF_SERVICE_SIGNUP_ROLES = frozenset({Role.student})


def _to_token_dto(result: AuthResult) -> TokenResponseDTO:
    """Convert an :class:`AuthResult` into the wire DTO."""
    return TokenResponseDTO(
        accessToken=result.access_token,
        userId=str(result.user_id),
        role=result.role.value,
        refreshToken=result.refresh_token,
    )


@router.post("/auth/signup", response_model=TokenResponseDTO)
def signup(
    body: SignupRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponseDTO:
    """Create a self-service **student** account and return a login token.

    Only ``student`` may be self-registered; requesting any elevated role is a 403
    (D1.7) so signup can never be used for privilege escalation.
    """
    requested_role = Role(body.role)
    if requested_role not in _SELF_SERVICE_SIGNUP_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Self-service signup can only create a student account.",
        )
    try:
        result = service.signup(
            body.email,
            body.password,
            requested_role,
            display_name=body.displayName,
            phone=body.phone,
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_token_dto(result)


@router.post("/auth/login", response_model=TokenResponseDTO)
def login(
    body: LoginRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponseDTO:
    """Authenticate an email/password user and return an access token."""
    try:
        result = service.login(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _to_token_dto(result)


@router.post("/auth/otp/request", response_model=OtpRequestResponseDTO)
def request_otp(
    body: OtpRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> OtpRequestResponseDTO:
    """Issue a parent phone-OTP challenge (the code is delivered via SMS).

    A re-request inside the resend cooldown is a 429 (not a 500): the cooldown
    stops a caller resetting the brute-force attempt counter by spamming issues.
    """
    try:
        service.request_otp(body.phone)
    except OtpRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return OtpRequestResponseDTO()


@router.post("/auth/otp/verify", response_model=TokenResponseDTO)
def verify_otp(
    body: OtpVerifyDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponseDTO:
    """Verify an OTP code and return a self-signed parent access token."""
    try:
        result = service.verify_otp(body.phone, body.code)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _to_token_dto(result)
