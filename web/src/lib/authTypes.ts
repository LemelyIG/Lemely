/*
 * TS interfaces mirroring lemely/web/schemas_auth.py field-for-field
 * (camelCase). Keep these in lockstep with the backend DTOs — see that module
 * for the authoritative field docs.
 */

export type Role = "student" | "parent" | "teacher" | "school_admin" | "platform_admin"

export interface SignupRequest {
  email: string
  password: string
  role: Role
  /**
   * D7.11: consent to `/data`, the data-handling page that actually exists
   * (this repository has no terms-of-service document to have "agreed" to).
   * Required, with no default — mirroring `SignupRequestDTO.acceptedTerms`'s
   * own refusal to default it, an absent field is a 422 server-side, never a
   * silently assumed `false`. A consent checkbox the server does not itself
   * enforce would be decorative, and a default here is exactly what would
   * make it so.
   */
  acceptedTerms: boolean
  displayName?: string | null
  phone?: string | null
  deviceId?: string | null
}

export interface LoginRequest {
  email: string
  password: string
  deviceId?: string | null
  /** Agreed to sign the oldest device out (the second half of D5.12's 409 handshake). */
  confirmDeviceEviction?: boolean
}

export interface OtpRequestBody {
  phone: string
}

export interface OtpVerifyBody {
  phone: string
  code: string
  deviceId?: string | null
}

export interface TokenResponse {
  accessToken: string
  userId: string
  role: Role
  refreshToken: string | null
  /**
   * The freshly minted email-verification link (D7.4/D7.6/D7.7), present only
   * on a `/auth/signup` response — every other flow returning this shape
   * (`login`, `refresh`, `otp/verify`) mints no verification token and this
   * is always `null`. Non-`null` itself only when the configured
   * `EmailProvider` does not deliver out of band — the same D3.16 rule
   * `OtpRequestResponse.devCode` below follows; with a real provider
   * configured this is always `null` and no live link crosses the wire.
   * Render it in an explicitly-labelled developer panel, never as ordinary
   * product copy.
   */
  devLink: string | null
  /**
   * The typed 6-digit code minted alongside `devLink` (spec §4.4/DS15) —
   * the same D3.16 rule, populated and cleared together with it: both
   * `null` with a real provider configured, both non-null only when nothing
   * delivers out of band. Render it in the same developer panel as the
   * link, never as ordinary product copy.
   */
  devCode: string | null
}

export interface OtpRequestResponse {
  status: "sent"
  /**
   * §G-05's developer affordance (D3.16). Non-null **only** when the configured
   * SMS provider does not deliver out of band (the offline mock) — with a real
   * gateway the backend always sends null. Render it in an explicitly-labelled
   * developer panel, never as ordinary product copy.
   */
  devCode: string | null
}

/** `POST /auth/verify-email` body — redeem a single-use verification token
 * (G-07's `/verify-email/:token`, spec §4.4). */
export interface VerifyEmailBody {
  token: string
}

/**
 * `POST /auth/verify-email/code` body (spec §4.4/DS15) — redeem the typed
 * 6-digit code minted alongside the link. Authenticated: the address comes
 * from the caller's own session server-side, never a body field, so there is
 * deliberately no matching field here either — the code alone is the
 * credential.
 */
export interface VerifyEmailCodeBody {
  code: string
}

/** Acknowledgement that `users.email_verified_at` was stamped. */
export interface VerifyEmailResponse {
  status: "verified"
}

/**
 * `POST /auth/verify-email/resend` response. Authenticated and deliberately
 * bodyless — the caller is read from the session, never a request field (a
 * body-supplied address would let an attacker trigger a verification send to
 * someone else's inbox) — so there is no matching `...Body` type here.
 */
export interface ResendVerificationResponse {
  status: "sent"
  /**
   * The freshly re-minted verification link — see `TokenResponse.devLink`
   * for the D3.16 rule this follows, applied here to
   * `AuthService.resend_verification`. Render it in an explicitly-labelled
   * developer panel, never as ordinary product copy.
   */
  devLink: string | null
  /** The typed 6-digit code re-minted alongside `devLink` — see
   * `TokenResponse.devCode` for the D3.16/DS15 rule this follows. */
  devCode: string | null
}

/** `POST /auth/password-reset/request` body. */
export interface PasswordResetRequestBody {
  email: string
}

/**
 * Always 200 whether or not `email` belongs to an account — the binding
 * anti-enumeration rule spec §4.3 states explicitly for this route.
 */
export interface PasswordResetRequestResponse {
  status: "sent"
  /**
   * The freshly minted password-reset link — see `TokenResponse.devLink` for
   * the D3.16 rule this follows. `null` both when a real provider delivered
   * it *and* when `email` named no account at all: this route's
   * anti-enumeration guarantee depends on those two cases staying
   * indistinguishable here, so this field is not only a developer affordance
   * but part of that guarantee. Render it in an explicitly-labelled
   * developer panel, never as ordinary product copy.
   */
  devLink: string | null
}

/**
 * `POST /auth/password-reset/confirm` body. Confirming revokes every
 * outstanding `auth_tokens` row for the account **and every device
 * session** — the G-06 success screen must say so plainly.
 */
export interface PasswordResetConfirmBody {
  token: string
  newPassword: string
}

/** Acknowledgement that the credential changed and every session was revoked. */
export interface PasswordResetConfirmResponse {
  status: "reset"
}

/**
 * G-08's pre-account preview (`GET /api/invites/{code}`, public) — what the
 * code's holder is about to join. Mirrors `InvitePreviewDTO`
 * (`lemely/web/schemas_invites.py`): every field here is something the
 * holder already learned from whoever handed them the code, so there is
 * deliberately no id, no roster and no seat/enrolment count.
 */
export interface InvitePreview {
  role: "student" | "teacher"
  schoolName: string | null
  className: string | null
  teacherName: string | null
}

/**
 * The stable, machine-readable 403 marker `deps.require_verified_email`
 * raises when D7.5's soft gate refuses an unverified account (today, only
 * `POST /student/correct`). Its own docstring calls this out as "a stable,
 * machine-readable marker (never prose) the frontend's `lib/authOutcome.ts`-
 * family outcome modules match on" — `isEmailUnverifiedError` below is that
 * match, and `authOutcome.ts`'s `verificationFailureMessage` is the one
 * sentence it produces.
 */
export interface EmailUnverifiedError {
  code: "email_unverified"
}

/**
 * Narrow an `ApiError.detail` onto the email-unverified marker, mirroring
 * `isDeviceLimitChallenge` (`deviceTypes.ts`) for the same reason: a 403's
 * `detail` here is a structured object, not a string — `ApiError.message` is
 * already the generic `403 Forbidden` status line by the time it reaches a
 * caller (see `api.ts`'s non-string-`detail` branch) — so telling this 403
 * apart from any other requires reading the object's shape, never its text.
 */
export function isEmailUnverifiedError(detail: unknown): detail is EmailUnverifiedError {
  if (typeof detail !== "object" || detail === null) return false
  return (detail as Partial<EmailUnverifiedError>).code === "email_unverified"
}
