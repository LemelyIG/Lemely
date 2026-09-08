"""Authentication endpoints under ``/api/auth``.

Thin HTTP layer over :class:`~lemely.auth.service.AuthService`: signup and login
delegate to GoTrue email/password, and the three ``/auth/parent/*`` routes drive
the child-issued parent signup (spec §4) — a six-digit email code, then a
password, in place of the retired phone-OTP flow. Domain
:class:`~lemely.runtime.errors.AuthError` maps to a 400/401 ``HTTPException`` so
credential failures never surface as a 500.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these
# type imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from lemely.auth.cooldown import CooldownError, CooldownStoreProtocol
from lemely.auth.mirror import UserMirror
from lemely.auth.otp import OtpRateLimitError
from lemely.auth.service import AuthResult, AuthService, DeviceContext
from lemely.auth.tokens import TokenError, decode_email_proof_token, mint_email_proof_token
from lemely.db.device_repo import MAX_DEVICES, DeviceLimitReachedError
from lemely.db.invite_repo import InviteNotFoundError, InviteService
from lemely.db.models.enums import InviteRole, Role
from lemely.runtime.config import Settings
from lemely.runtime.errors import AuthError
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_auth_service,
    get_invite_service,
    get_resend_verification_cooldown_store,
    get_settings,
    get_signup_and_reset_cooldown_store,
    get_user_mirror,
)
from lemely.web.devices import to_device_dto
from lemely.web.schemas_auth import (
    LoginRequestDTO,
    ParentCodeRequestDTO,
    ParentCodeRequestResponseDTO,
    ParentCodeVerifyDTO,
    ParentCodeVerifyResponseDTO,
    ParentSignupDTO,
    PasswordResetConfirmDTO,
    PasswordResetConfirmResponseDTO,
    PasswordResetRequestDTO,
    PasswordResetRequestResponseDTO,
    RefreshRequestDTO,
    ResendVerificationResponseDTO,
    SignupRequestDTO,
    TokenResponseDTO,
    VerifyEmailCodeRequestDTO,
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
# the seat/invite flow. Parents authenticate via the three ``/auth/parent/*``
# routes below (spec §4), gated on holding a live parent invite rather than
# on this allowlist — `/auth/signup` itself never creates one.
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
        devCode=result.verification_dev_code,
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


def _require_live_parent_invite(invite_service: InviteService, code: str) -> None:
    """Refuse a dead or non-parent invite with the same 404 an unknown code gets.

    Used by all three ``/auth/parent/*`` routes (spec §4): a code that does
    not resolve at all and a code that resolves to something other than a
    live parent invite (a seat/class invite, or one already expired) must
    read identically, so an anonymous caller learns nothing about *why* a
    given code failed — the same disclosure discipline
    :meth:`~lemely.db.invite_repo.InviteService.preview`'s own docstring
    binds itself to (rule 4), extended here to "is this a parent invite" as
    well as "does the code exist". The detail wording matches
    :class:`~lemely.db.invite_repo.InviteNotFoundError`'s own exactly, for
    the identical reason.
    """
    try:
        preview = invite_service.preview(code)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if preview.role is not InviteRole.parent:
        raise HTTPException(status_code=404, detail=f"Unknown code: {code!r}")


@router.post("/auth/signup", response_model=TokenResponseDTO)
def signup(
    body: SignupRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    cooldown: Annotated[CooldownStoreProtocol, Depends(get_signup_and_reset_cooldown_store)],
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


@router.post("/auth/parent/request-code", response_model=ParentCodeRequestResponseDTO)
def request_parent_code(
    body: ParentCodeRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    cooldown: Annotated[CooldownStoreProtocol, Depends(get_signup_and_reset_cooldown_store)],
) -> ParentCodeRequestResponseDTO:
    """Issue a signup code to the email address opening a parent invite (spec §4).

    The invite named by ``inviteCode`` must resolve to a live parent invite —
    any other outcome (unknown code, expired, or a seat/class invite) is the
    same **404** an unknown code gets, via
    :func:`_require_live_parent_invite`.

    **Duplicate-address check runs before the cooldown, mirroring
    :func:`signup`'s own ordering exactly** (see that function's docstring for
    the reasoning in full): ``mirror.get_by_email`` is read-only and free, so
    an address that already has an account gets the same actionable **400**
    on every attempt rather than a 429 it can never wait out — only once the
    address is confirmed unclaimed does ``cooldown.check_and_stamp`` run,
    throttling the genuinely costly path (a real code mint plus a send) to a
    **429**.

    ``devCode`` is populated only when the configured
    :class:`~lemely.auth.email.EmailProvider` does not deliver out of band —
    see :class:`~lemely.web.schemas_auth.ParentCodeRequestResponseDTO` and
    D3.16.
    """
    _require_live_parent_invite(invite_service, body.inviteCode)
    if mirror.get_by_email(body.email) is not None:
        raise HTTPException(
            status_code=400,
            detail="This email already has an account. Sign in, then open the invite again.",
        )
    try:
        cooldown.check_and_stamp(body.email)
    except CooldownError as exc:
        raise HTTPException(status_code=429, detail=_cooldown_detail(exc)) from exc
    try:
        dev_code = service.request_parent_signup_code(body.email)
    except OtpRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return ParentCodeRequestResponseDTO(devCode=dev_code)


@router.post("/auth/parent/verify-code", response_model=ParentCodeVerifyResponseDTO)
def verify_parent_code(
    body: ParentCodeVerifyDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ParentCodeVerifyResponseDTO:
    """Verify a parent-signup code and mint the proof token for the final step (spec §4).

    A wrong, expired, or locked-out code is a **401** carrying the service's
    own detail (mirrors every other credential failure this router maps).
    The invite is re-checked live *after* the code verifies — never before —
    so a caller who mistypes the code never learns anything about the
    invite's state from a response that only depends on the code.
    """
    try:
        service.verify_parent_signup_code(body.email, body.code)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _require_live_parent_invite(invite_service, body.inviteCode)
    proof_token = mint_email_proof_token(
        email=body.email, invite_code=body.inviteCode, settings=settings
    )
    return ParentCodeVerifyResponseDTO(proofToken=proof_token)


@router.post("/auth/parent/signup", response_model=TokenResponseDTO)
def parent_signup(
    body: ParentSignupDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    user_agent: Annotated[str | None, Header()] = None,
) -> TokenResponseDTO:
    """Create the parent's account from a verified proof token and link it (spec §4).

    Three steps, each able to fail independently: decoding ``proofToken``
    (→ **401** on any failure — expired, wrong audience, tampered — via
    :class:`~lemely.auth.tokens.TokenError`), re-checking the invite it names
    is still live (→ **404**, :func:`_require_live_parent_invite` again — a
    code can expire or be revoked in the minutes between verifying the email
    and completing this step), then :meth:`~lemely.auth.service.AuthService.signup`
    itself (→ **400** on an ``AuthError`` — chiefly the address being taken,
    though that should be rare given step one already checked it).
    ``email_verified=True`` is passed because the proof token *is* that
    verification — asking the parent to also click a mailed link would be
    asking them to prove the same address twice.

    **Honest gap, the same shape seat invites already carry.** The GoTrue
    account creation and :meth:`~lemely.db.invite_repo.InviteService.redeem`
    (which performs the actual link, inside its own transaction with
    :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session`) are two
    separate calls, not one database transaction — a failure between them
    leaves a real, working parent account that is not yet linked to the
    child. There is no special recovery path for this: the account exists,
    and re-presenting the exact same code at ``/join/:code`` while signed in
    (spec §2 rule 4) redeems it the normal way.
    """
    try:
        claims = decode_email_proof_token(body.proofToken, settings)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _require_live_parent_invite(invite_service, claims.invite_code)
    try:
        result = service.signup(
            claims.email,
            body.password,
            Role.parent,
            display_name=body.displayName,
            device=_device_context(body.deviceId, user_agent),
            accepted_terms=body.acceptedTerms,
            email_verified=True,
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invite_service.redeem(result.user_id, claims.invite_code, caller_role=Role.parent)
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


@router.post("/auth/verify-email/code", response_model=VerifyEmailResponseDTO)
def verify_email_code(
    body: VerifyEmailCodeRequestDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifyEmailResponseDTO:
    """Verify the **authenticated caller's** email by code (DS15). 400 on any failure.

    The second route through §4.4/DS15's link-and-code pair: authenticated
    (any signed-in role, AUTH_ANY) rather than public like ``/verify-email``,
    because the code alone — six digits — is far weaker as a bearer credential
    than the link's opaque token, so it is only ever redeemed against the
    caller's *own* session, read from :class:`~lemely.web.deps.AuthContext`,
    never a body field. A wrong, expired, or locked-out code is a **400** with
    the same non-revealing detail :func:`verify_email` uses.
    """
    try:
        service.verify_email_code(uuid.UUID(auth.user_id), body.code)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VerifyEmailResponseDTO()


@router.post("/auth/verify-email/resend", response_model=ResendVerificationResponseDTO)
def resend_verification(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    cooldown: Annotated[CooldownStoreProtocol, Depends(get_resend_verification_cooldown_store)],
) -> ResendVerificationResponseDTO:
    """Re-mint and (re)send a verification link and code for the **authenticated caller**.

    Deliberately takes no address in the body: the caller is read from
    :class:`~lemely.web.deps.AuthContext` alone, exactly as
    :meth:`~lemely.auth.service.AuthService.resend_verification`'s own
    docstring requires — a body-supplied address would let an attacker
    trigger a verification send to someone else's inbox. Any signed-in role
    may call this (AUTH_ANY): the route is scoped by *whose token this is*,
    not by platform role.

    A per-user cooldown (D7.12) throttles repeat resends to a **429**,
    mirroring ``/auth/parent/request-code``'s own resend-cooldown mapping.

    **A second, independent 429 source.** ``AuthService.resend_verification``
    now also issues a fresh email-channel code
    (:meth:`~lemely.auth.service.AuthService._issue_email_code`), and the OTP
    store's own resend cooldown (``otp_min_resend_seconds`` — shared with the
    parent-signup-code challenge, since both are "prove you control this
    inbox" challenges on the same channel) can reject that issue with
    :class:`~lemely.auth.otp.OtpRateLimitError` — distinct from, and not
    prevented by, the ``cooldown`` check above: the D7.12 store is stamped
    only *on* a resend call, so a caller's very first resend (no D7.12 stamp
    yet) can still land inside the OTP store's own window if it follows the
    ``signup`` that already issued a code for the same address moments
    earlier. Mapped to the same 429 :func:`request_parent_code` already uses
    for the identical exception on the parent-signup-code channel, rather
    than left to surface as an unhandled 500.
    """
    try:
        cooldown.check_and_stamp(auth.user_id)
    except CooldownError as exc:
        raise HTTPException(status_code=429, detail=_cooldown_detail(exc)) from exc
    try:
        dev_link, dev_code = service.resend_verification(uuid.UUID(auth.user_id))
    except OtpRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResendVerificationResponseDTO(devLink=dev_link, devCode=dev_code)


@router.post("/auth/password-reset/request", response_model=PasswordResetRequestResponseDTO)
def request_password_reset(
    body: PasswordResetRequestDTO,
    service: Annotated[AuthService, Depends(get_auth_service)],
    cooldown: Annotated[CooldownStoreProtocol, Depends(get_signup_and_reset_cooldown_store)],
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
