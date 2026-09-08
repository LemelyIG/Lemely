"""API DTOs for the auth endpoints (``/api/auth/*``).

Request/response models for signup, login, and the three-step child-issued
parent signup (email code, then password — spec §4). Field names are
camelCase to match the frontend contract, mirroring the other
``schemas_*.py`` modules.
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

    ``acceptedTerms`` (D7.11) records consent to ``/data`` — the data-handling
    page that actually exists, since this repository has no terms-of-service
    document to have "agreed" to. Deliberately carries **no default**: an
    absent field is a pydantic 422 (missing required field), never a silently
    assumed ``False``. A consent checkbox the server does not itself enforce
    would be decorative, and a default here is exactly what would make it so.
    """

    email: str
    password: str
    role: Role
    acceptedTerms: bool
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


class ParentCodeRequestDTO(ApiModel):
    """Request a signup code for the email address opening a parent invite (spec §4).

    ``inviteCode`` names the parent invite this request is scoped to — the
    router re-checks it resolves to a live parent invite before issuing
    anything, so a dead or non-parent code never gets as far as sending mail.
    """

    email: str
    inviteCode: str


class ParentCodeRequestResponseDTO(ApiModel):
    """Acknowledgement that a parent-signup code was issued.

    ``devCode`` is the same developer affordance the retired phone-OTP flow
    used to carry (D3.16), now populated **only** when the configured
    :class:`~lemely.auth.email.EmailProvider` reports
    ``delivers_out_of_band = False`` — a capability gate, not an environment
    check; the UI must render it in an explicitly-labelled developer panel,
    never as ordinary product copy.
    """

    status: Literal["sent"] = "sent"
    devCode: str | None = None


class ParentCodeVerifyDTO(ApiModel):
    """Verify a parent-signup code and receive a proof token (spec §4).

    ``inviteCode`` is carried through unchanged so the minted
    :func:`~lemely.auth.tokens.mint_email_proof_token` can bind the proof to
    the exact same invite the request step named, rather than trusting the
    final signup call to resend it honestly.
    """

    email: str
    inviteCode: str
    code: str


class ParentCodeVerifyResponseDTO(ApiModel):
    """The short-lived receipt that ``email`` completed the signup-code challenge.

    ``proofToken`` (see :func:`~lemely.auth.tokens.mint_email_proof_token`) is
    presented to ``POST /api/auth/parent/signup`` in place of the (single-use,
    already-consumed) code, so the final step never re-verifies a code that
    has already been spent.
    """

    proofToken: str


class ParentSignupDTO(ApiModel):
    """Complete a parent's account creation with the proof token from step two.

    ``acceptedTerms`` carries the identical D7.11 rule
    :class:`SignupRequestDTO` documents — deliberately no default, so a
    missing field is a 422, never a silently assumed ``False``.
    """

    proofToken: str
    password: str
    acceptedTerms: bool
    displayName: str | None = None
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

    ``devLink`` (D7.4/D7.6/D7.7) is the freshly minted email-verification link
    from :meth:`~lemely.auth.service.AuthService.signup`, under the same
    D3.16-derived rule :attr:`ParentCodeRequestResponseDTO.devCode` carries:
    populated **only** when the configured
    :class:`~lemely.auth.email.EmailProvider` does not deliver out of band,
    i.e. only when this response is the sole way to obtain the link. It is
    ``None`` on every other flow that returns this DTO (``login``,
    ``refresh``, the parent signup), none of which mint a verification token
    at all — the parent signup route stamps ``email_verified_at`` directly
    (see :meth:`~lemely.auth.service.AuthService.signup`'s ``email_verified``
    argument) and so never mints one of these either. The UI must render it
    in an explicitly-labelled developer panel, never as ordinary product copy.

    ``devCode`` (spec §4.4/DS15) is the typed code minted alongside the link,
    under the exact same D3.16 rule — the two are always populated together
    or both ``None``.
    """

    accessToken: str
    userId: str
    role: Role
    refreshToken: str | None = None
    devLink: str | None = None
    devCode: str | None = None


class VerifyEmailRequestDTO(ApiModel):
    """Redeem an email-verification token (``/verify-email/:token``, spec §4.4)."""

    token: str


class VerifyEmailCodeRequestDTO(ApiModel):
    """Redeem the typed code sent alongside the link (spec §4.4/DS15).

    Deliberately no matching address field: the caller's own email comes from
    :class:`~lemely.web.deps.AuthContext` (the authenticated session), never a
    body field — the same reason :class:`ResendVerificationResponseDTO`'s
    request has none. The code alone is the credential.
    """

    code: str


class VerifyEmailResponseDTO(ApiModel):
    """Acknowledgement that ``users.email_verified_at`` was stamped."""

    status: Literal["verified"] = "verified"


class ResendVerificationResponseDTO(ApiModel):
    """Acknowledgement that a fresh verification token and code were minted and (re)sent.

    Deliberately no matching request DTO: the caller is read from
    :class:`~lemely.web.deps.AuthContext`, never a body field (an attacker
    could fill a body field with someone else's address).

    ``devLink`` — see :attr:`TokenResponseDTO.devLink`; the same D3.16-derived
    rule, applied to :meth:`~lemely.auth.service.AuthService.resend_verification`.
    ``devCode`` carries the same rule for the code minted alongside it (spec
    §4.4/DS15).
    """

    status: Literal["sent"] = "sent"
    devLink: str | None = None
    devCode: str | None = None


class PasswordResetRequestDTO(ApiModel):
    """Request a password-reset link for ``email``.

    Anti-enumeration is binding here (D7 §4.3): the response is **always**
    200 with the same shape, whether or not ``email`` belongs to an account —
    see :meth:`~lemely.auth.service.AuthService.request_password_reset`.
    """

    email: str


class PasswordResetRequestResponseDTO(ApiModel):
    """Acknowledgement of a password-reset request. Always 200.

    See :class:`PasswordResetRequestDTO`. ``devLink`` — see
    :attr:`TokenResponseDTO.devLink`; the same D3.16-derived
    rule, applied to :meth:`~lemely.auth.service.AuthService.request_password_reset`.
    ``None`` both when a real provider delivered and when ``email`` was
    unknown — the two cases are indistinguishable by design.
    """

    status: Literal["sent"] = "sent"
    devLink: str | None = None


class PasswordResetConfirmDTO(ApiModel):
    """Redeem a password-reset token and set a new credential.

    Confirming (:meth:`~lemely.auth.service.AuthService.reset_password`)
    revokes every outstanding ``auth_tokens`` row for the account **and every
    device session** — the reason for a reset may be a compromise, so the
    account is signed out everywhere, not only on the device completing the
    reset.
    """

    token: str
    newPassword: str


class PasswordResetConfirmResponseDTO(ApiModel):
    """Acknowledgement that the credential was changed and every session revoked."""

    status: Literal["reset"] = "reset"


__all__ = [
    "ApiModel",
    "LoginRequestDTO",
    "ParentCodeRequestDTO",
    "ParentCodeRequestResponseDTO",
    "ParentCodeVerifyDTO",
    "ParentCodeVerifyResponseDTO",
    "ParentSignupDTO",
    "PasswordResetConfirmDTO",
    "PasswordResetConfirmResponseDTO",
    "PasswordResetRequestDTO",
    "PasswordResetRequestResponseDTO",
    "RefreshRequestDTO",
    "ResendVerificationResponseDTO",
    "Role",
    "SignupRequestDTO",
    "TokenResponseDTO",
    "VerifyEmailCodeRequestDTO",
    "VerifyEmailRequestDTO",
    "VerifyEmailResponseDTO",
]
