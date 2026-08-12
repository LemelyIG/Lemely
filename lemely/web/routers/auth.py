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

from fastapi import APIRouter, Depends, Header, HTTPException

from lemely.auth.otp import OtpRateLimitError
from lemely.auth.service import AuthResult, AuthService, DeviceContext
from lemely.db.device_repo import MAX_DEVICES, DeviceLimitReachedError
from lemely.db.models.enums import Role
from lemely.runtime.errors import AuthError
from lemely.web.deps import get_auth_service
from lemely.web.devices import to_device_dto
from lemely.web.schemas_auth import (
    LoginRequestDTO,
    OtpRequestDTO,
    OtpRequestResponseDTO,
    OtpVerifyDTO,
    SignupRequestDTO,
    TokenResponseDTO,
)
from lemely.web.schemas_devices import DeviceLimitChallengeDTO

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


def _device_context(client_device_id: str | None, user_agent: str | None) -> DeviceContext:
    """Build the per-login device metadata for the 3-device limit (D1.11).

    A login always carries a context so it registers a device; ``client_device_id``
    (from the request body) lets a re-login on the same device reuse its slot, and
    ``user_agent`` is stored for the device-management view.
    """
    return DeviceContext(client_device_id=client_device_id, user_agent=user_agent)


def _to_challenge(exc: DeviceLimitReachedError) -> DeviceLimitChallengeDTO:
    """Build G-10's body from the devices the registry refused to evict past.

    ``exc.devices`` is most-recently-active first, so the device a confirmed retry
    would sign out is the **last** one — named explicitly rather than left for the
    client to re-derive, which is how a UI ends up promising to sign out a device
    the server would keep.
    """
    return DeviceLimitChallengeDTO(
        maxDevices=MAX_DEVICES,
        devices=[to_device_dto(row) for row in exc.devices],
        oldestDeviceId=str(exc.devices[-1].device_id),
    )


@router.post("/auth/signup", response_model=TokenResponseDTO)
def signup(
    body: SignupRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    user_agent: Annotated[str | None, Header()] = None,
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
            device=_device_context(body.deviceId, user_agent),
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_token_dto(result)


@router.post("/auth/login", response_model=TokenResponseDTO)
def login(
    body: LoginRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    user_agent: Annotated[str | None, Header()] = None,
) -> TokenResponseDTO:
    """Authenticate an email/password user and return an access token.

    Registers the login against the 3-device limit (D1.11). A login that would
    consume a **fourth** slot answers **409** with the account's signed-in devices
    and mints no token, evicting nothing; the client shows G-10 and re-sends the
    same login with ``confirmDeviceEviction`` once the user has agreed (D5.12).
    The credential is verified *before* that list is produced, so no unauthenticated
    caller can enumerate a stranger's devices.
    """
    try:
        result = service.login(
            body.email,
            body.password,
            device=_device_context(body.deviceId, user_agent),
            confirm_device_eviction=body.confirmDeviceEviction,
        )
    except DeviceLimitReachedError as exc:
        raise HTTPException(status_code=409, detail=_to_challenge(exc).model_dump()) from exc
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

    ``devCode`` is populated only by an SMS provider that does not deliver out of
    band (the offline mock) — see :class:`OtpRequestResponseDTO` and D3.16.
    """
    try:
        dev_code = service.request_otp(body.phone)
    except OtpRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return OtpRequestResponseDTO(devCode=dev_code)


@router.post("/auth/otp/verify", response_model=TokenResponseDTO)
def verify_otp(
    body: OtpVerifyDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    user_agent: Annotated[str | None, Header()] = None,
) -> TokenResponseDTO:
    """Verify an OTP code and return a self-signed parent access token.

    Registers the login against the 3-device limit, evicting the oldest session
    beyond three (D1.11).
    """
    try:
        result = service.verify_otp(
            body.phone,
            body.code,
            device=_device_context(body.deviceId, user_agent),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _to_token_dto(result)
