"""Authentication endpoints under ``/api/auth``.

Thin HTTP layer over :class:`~lemely.auth.service.AuthService`: signup and login
delegate to GoTrue email/password, and the two OTP routes drive the parent
phone-OTP lifecycle. Domain :class:`~lemely.runtime.errors.AuthError` maps to a
400/401 ``HTTPException`` so credential/OTP failures never surface as a 500.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these
# type imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from lemely.auth.cooldown import CooldownError, CooldownStore
from lemely.auth.mirror import UserMirror
from lemely.auth.otp import OtpRateLimitError
from lemely.auth.service import AuthResult, AuthService, DeviceContext
from lemely.db.device_repo import MAX_DEVICES, DeviceLimitReachedError
from lemely.db.models.enums import Role
from lemely.runtime.errors import AuthError
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_auth_service,
    get_resend_verification_cooldown_store,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
)
from lemely.web.devices import to_device_dto
from lemely.web.schemas_auth import (
    LoginRequestDTO,
    OtpRequestDTO,
    OtpRequestResponseDTO,
    OtpVerifyDTO,
    PasswordResetConfirmDTO,
    PasswordResetConfirmResponseDTO,
    PasswordResetRequestDTO,
    PasswordResetRequestResponseDTO,
    RefreshRequestDTO,
    ResendVerificationResponseDTO,
    SignupRequestDTO,
    TokenResponseDTO,
    VerifyEmailRequestDTO,
    VerifyEmailResponseDTO,
)
from lemely.web.schemas_devices import DeviceLimitChallengeDTO

router = APIRouter(prefix="/api")

# Self-service signup may create a student or a teacher. Elevated roles
# (school_admin / platform_admin) are privileged and MUST NOT be obtainable by
# an anonymous caller — otherwise anyone could POST role="platform_admin" and
# mint an admin token (D1.7). Those two are created by an authenticated admin:
# school_admin via the platform-admin schools surface, teacher-in-a-school via
# the seat/invite flow. Parents authenticate via phone-OTP, not signup.
#
# D7.1 added `teacher` and did not weaken D1.7's rule. D1.7's stated risk is
# *escalation*, and a self-registered teacher escalates nothing: every teacher
# service is ownership-scoped by construction with no super-role bypass
# (D1.6/D1.10), so they reach only classes they created and students who chose
# to type their join code.
_SELF_SERVICE_SIGNUP_ROLES = frozenset({Role.student, Role.teacher})


def _to_token_dto(result: AuthResult) -> TokenResponseDTO:
    """Convert an :class:`AuthResult` into the wire DTO."""
    return TokenResponseDTO(
        accessToken=result.access_token,
        userId=str(result.user_id),
        role=result.role.value,
        refreshToken=result.refresh_token,
        devLink=result.verification_dev_link,
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


def _cooldown_detail(exc: CooldownError) -> str:
    """Human wording for a 429, deliberately not ``str(exc)``.

    ``CooldownError.__str__`` is ``f"Cooldown active for {key!r}; retry in
    {retry_after:.0f}s."`` — a log line, and the ``key`` is the caller's own
    email address (signup, password reset) or their raw user id (resend). It is
    their own data rather than a stranger's, so this is a copy defect and not a
    disclosure one; it is still the exact shape ``lib/*Outcome.ts`` exists to
    keep off a screen, and a ``repr()``'d address is not a sentence anybody
    wrote for a reader.

    ``lemely/auth/otp.py`` already sets the precedent this follows: "OTP already
    sent; retry in 12s." — a human sentence, carrying the one fact the reader
    needs, naming nothing they did not ask about. ``authOutcome.ts``'s rule is
    to keep a 429's server wording *where a human wrote it for a human*, so the
    honest fix is to make that true here rather than to have the client discard
    it.
    """
    return f"Please wait {exc.retry_after:.0f}s before trying again."


@router.post("/auth/signup", response_model=TokenResponseDTO)
def signup(
    body: SignupRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    cooldown: Annotated[CooldownStore, Depends(get_signup_and_reset_cooldown_store)],
    user_agent: Annotated[str | None, Header()] = None,
) -> TokenResponseDTO:
    """Create a self-service **student** or **teacher** account and return a token.

    Only ``student``/``teacher`` may be self-registered; requesting an elevated
    role (``school_admin``/``platform_admin``) is a 403 (D1.7, revised in scope
    but not in spirit by D7.1 — see ``_SELF_SERVICE_SIGNUP_ROLES``'s own
    comment) so signup can never be used for privilege escalation.

    **The per-email cooldown (D7.12) only guards an address that does not yet
    have an account.** ``mirror.get_by_email`` is checked first, read-only,
    before the cooldown is ever touched: a request for an address that is
    already registered mints nothing and sends nothing, so it has no cost for
    the cooldown to throttle, and — the reason this check exists at all — a
    caller who already has an account must see the same actionable **400**
    ("this address is taken, sign in instead") on *every* attempt, never a
    **429** that gives them no way forward; they cannot wait out a window for
    an address that will never become available to them. That duplicate
    conflict is then produced the normal way, by
    :meth:`~lemely.auth.service.AuthService.signup` itself failing against
    GoTrue's own uniqueness constraint — this check never substitutes its own
    judgement for that one, it only decides whether the *attempt* was cheap
    enough to skip the throttle. Only once the address is confirmed unclaimed
    does ``cooldown.check_and_stamp`` run, gating the address's genuinely
    costly path (a real GoTrue write plus a verification send) to a **429**.

    On success, ``accepted_terms`` is threaded through to
    :meth:`~lemely.auth.service.AuthService.signup`, which stamps
    ``users.terms_accepted_at`` (D7.11) and best-effort mints/sends an
    email-verification token (D7.4/D7.7) whose dev link (only when the
    configured provider does not deliver out of band) rides back on
    :attr:`~lemely.web.schemas_auth.TokenResponseDTO.devLink`.
    """
    requested_role = Role(body.role)
    if requested_role not in _SELF_SERVICE_SIGNUP_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Self-service signup can only create a student or teacher account.",
        )
    if mirror.get_by_email(body.email) is None:
        try:
            cooldown.check_and_stamp(body.email)
        except CooldownError as exc:
            raise HTTPException(status_code=429, detail=_cooldown_detail(exc)) from exc
    try:
        result = service.signup(
            body.email,
            body.password,
            requested_role,
            display_name=body.displayName,
            phone=body.phone,
            device=_device_context(body.deviceId, user_agent),
            accepted_terms=body.acceptedTerms,
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


@router.post("/auth/refresh", response_model=TokenResponseDTO)
def refresh(
    body: RefreshRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponseDTO:
    """Exchange a refresh token for a new access token.

    Access tokens are short-lived (``auth.access_token_ttl_seconds``), so the SPA
    redeems here when one expires rather than dumping the user back at the login
    screen every hour. Unauthenticated by design: the credential this route
    exists to replace has expired by the time it is called, so requiring it would
    make the route unreachable exactly when it is needed. The refresh token is
    itself the credential, and it authorises nothing else — a different ``aud``
    means it cannot be presented as a bearer token on any other route.

    Any reason the session is no longer valid — expired, signed out from the
    device list, evicted past the 3-device cap, superseded by a newer login, or
    belonging to a deleted user — is a **401**, which is the client's cue to
    clear its stored session and send the user to sign in.
    """
    try:
        result = service.refresh(body.refreshToken)
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


@router.post("/auth/verify-email", response_model=VerifyEmailResponseDTO)
def verify_email(
    body: VerifyEmailRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifyEmailResponseDTO:
    """Redeem an email-verification token, stamping ``users.email_verified_at``.

    Public (G-07's ``/verify-email/:token`` route, spec §4.4): the token
    itself — single-use, expiring, purpose-scoped (D7.7) — is the credential,
    not a bearer session. An unknown, wrong-purpose, already-used, or expired
    token is a **400**, mirroring the mapping every other credential failure
    on this router already uses (never a 404 or 410 that would hint at
    *which* of those four it was).
    """
    try:
        service.verify_email(body.token)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VerifyEmailResponseDTO()


@router.post("/auth/verify-email/resend", response_model=ResendVerificationResponseDTO)
def resend_verification(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    cooldown: Annotated[CooldownStore, Depends(get_resend_verification_cooldown_store)],
) -> ResendVerificationResponseDTO:
    """Re-mint and (re)send a verification token for the **authenticated caller**.

    Deliberately takes no address in the body: the caller is read from
    :class:`~lemely.web.deps.AuthContext` alone, exactly as
    :meth:`~lemely.auth.service.AuthService.resend_verification`'s own
    docstring requires — a body-supplied address would let an attacker
    trigger a verification send to someone else's inbox. Any signed-in role
    may call this (AUTH_ANY): the route is scoped by *whose token this is*,
    not by platform role.

    A per-user cooldown (D7.12) throttles repeat resends to a **429**,
    mirroring ``/auth/otp/request``'s existing resend-cooldown mapping.
    """
    try:
        cooldown.check_and_stamp(auth.user_id)
    except CooldownError as exc:
        raise HTTPException(status_code=429, detail=_cooldown_detail(exc)) from exc
    try:
        dev_link = service.resend_verification(uuid.UUID(auth.user_id))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResendVerificationResponseDTO(devLink=dev_link)


@router.post("/auth/password-reset/request", response_model=PasswordResetRequestResponseDTO)
def request_password_reset(
    body: PasswordResetRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    cooldown: Annotated[CooldownStore, Depends(get_signup_and_reset_cooldown_store)],
) -> PasswordResetRequestResponseDTO:
    """Request a password-reset link for ``email`` — always answers 200.

    Binding anti-enumeration rule, spec §4.3: the response is identical whether
    or not ``email`` belongs to an account —
    :meth:`~lemely.auth.service.AuthService.request_password_reset` never
    raises and never signals the difference by any other observable means, so
    this handler has no branch to get wrong. A 404 here would be an
    enumeration oracle.

    The per-email cooldown (D7.12, shared with ``/auth/signup`` — see
    ``AuthSettings.signup_and_reset_cooldown_seconds``) is checked *before*
    that call and **does** answer 429 on an address within its window — this
    is a rate limit on the requester's own repeat calls, not a signal about
    the address, so it does not weaken the anti-enumeration guarantee above.
    """
    try:
        cooldown.check_and_stamp(body.email)
    except CooldownError as exc:
        raise HTTPException(status_code=429, detail=_cooldown_detail(exc)) from exc
    dev_link = service.request_password_reset(body.email)
    return PasswordResetRequestResponseDTO(devLink=dev_link)


@router.post("/auth/password-reset/confirm", response_model=PasswordResetConfirmResponseDTO)
def confirm_password_reset(
    body: PasswordResetConfirmDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> PasswordResetConfirmResponseDTO:
    """Redeem a password-reset token and set a new credential.

    An unknown, wrong-purpose, already-used, or expired token is a **400**,
    the same mapping :func:`verify_email` uses. On success this also revokes
    every outstanding ``auth_tokens`` row for the account **and every device
    session** (see
    :meth:`~lemely.auth.service.AuthService.reset_password`'s docstring) —
    the reason for a reset may be a compromise, so the account is signed out
    everywhere, not only on the device completing the reset. The G-06 success
    screen must say so plainly.
    """
    try:
        service.reset_password(body.token, body.newPassword)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PasswordResetConfirmResponseDTO()
