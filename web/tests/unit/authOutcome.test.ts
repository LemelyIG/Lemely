import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  AUTH_BAD_CREDENTIALS,
  AUTH_CODE_REJECTED,
  AUTH_COOLDOWN_ACTIVE,
  AUTH_EMAIL_UNVERIFIED,
  AUTH_INVITE_ALREADY_USED,
  AUTH_INVITE_NOT_FOUND,
  AUTH_LINK_EXPIRED,
  AUTH_NETWORK_FAILURE,
  AUTH_SERVICE_FAILURE,
  AUTH_SIGNUP_REJECTED,
  inviteFailureMessage,
  otpRequestFailureMessage,
  otpVerifyFailureMessage,
  resetFailureMessage,
  signInFailureMessage,
  signUpFailureMessage,
  verificationCodeFailureMessage,
  verificationFailureMessage,
} from "@/lib/authOutcome"

/*
 * P4.7 · the product's failure voice at the moment nobody has seen a screen of
 * it yet.
 */

/** Every member of `OtpResult` (`lemely/auth/otp.py:32`) except `ok`, in the
 * exact wire form `AuthService.verify_otp` produces. */
const OTP_DETAILS = [
  "OTP verification failed: wrong_code",
  "OTP verification failed: expired",
  "OTP verification failed: locked_out",
  "OTP verification failed: no_challenge",
]

describe("signInFailureMessage", () => {
  it("names a lost connection as a connection problem", () => {
    expect(signInFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
    expect(signInFailureMessage(new TypeError("Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
  })

  it("says a 5xx is ours, not the reader's account", () => {
    expect(signInFailureMessage(new ApiError(500, "Internal Server Error"))).toBe(
      AUTH_SERVICE_FAILURE,
    )
  })

  /**
   * The security call, asserted rather than left to the copy.
   *
   * Distinguishing "no such account" from "wrong password" is an
   * account-enumeration oracle, and this product's users are children. The
   * message must be the same whichever half was wrong, and it must not echo a
   * backend detail that might distinguish them.
   */
  it("never reveals whether the email exists", () => {
    const noAccount = new ApiError(401, "Unauthorized", "No user with that email")
    const wrongPassword = new ApiError(401, "Unauthorized", "Invalid password for user")
    expect(signInFailureMessage(noAccount)).toBe(AUTH_BAD_CREDENTIALS)
    expect(signInFailureMessage(wrongPassword)).toBe(AUTH_BAD_CREDENTIALS)
    expect(signInFailureMessage(noAccount)).toBe(signInFailureMessage(wrongPassword))
    expect(AUTH_BAD_CREDENTIALS).not.toMatch(/email exists|no account|no user|password is/i)
  })

  /**
   * `request()` falls back to `` `${res.status} ${res.statusText}` `` when a
   * body carries no string detail, and this screen rendered `error.message`
   * verbatim, so a failed sign-in could put "401 Unauthorized" on screen.
   */
  it("never renders the status-text fallback", () => {
    const err = new ApiError(401, "401 Unauthorized")
    expect(signInFailureMessage(err)).not.toContain("401")
    expect(signInFailureMessage(err)).not.toContain("Unauthorized")
  })
})

describe("otpVerifyFailureMessage", () => {
  /**
   * The defect this module was written for: `ParentLogin` rendered
   * `err.message` verbatim, so a parent read `OTP verification failed:
   * wrong_code`.
   */
  it("never leaks the enum member or the machine prefix", () => {
    for (const detail of OTP_DETAILS) {
      const message = otpVerifyFailureMessage(new ApiError(401, detail, detail))
      expect(message, detail).not.toContain("OTP verification failed")
      expect(message, detail).not.toMatch(/wrong_code|no_challenge|locked_out|_/)
    }
  })

  /** The backend's distinction is the part worth keeping: four situations that
   * call for four different next actions must not collapse into one sentence. */
  it("keeps the four cases distinct", () => {
    const messages = OTP_DETAILS.map((detail) =>
      otpVerifyFailureMessage(new ApiError(401, detail, detail)),
    )
    expect(new Set(messages).size).toBe(4)
  })

  it("says what to do about each one", () => {
    const of = (reason: string) =>
      otpVerifyFailureMessage(
        new ApiError(401, "e", `OTP verification failed: ${reason}`),
      )
    expect(of("wrong_code")).toMatch(/again/i)
    expect(of("expired")).toMatch(/new one/i)
    expect(of("locked_out")).toMatch(/new one/i)
    expect(of("no_challenge")).toMatch(/new one/i)
  })

  /**
   * A member added to `OtpResult` server-side must not become copy. This is the
   * inversion of the mapping: an unknown reason falls through to a written
   * sentence rather than to the raw string.
   */
  it("does not render an unrecognised enum member added later", () => {
    const message = otpVerifyFailureMessage(
      new ApiError(401, "e", "OTP verification failed: device_mismatch"),
    )
    expect(message).not.toContain("device_mismatch")
    expect(message).toMatch(/code/i)
  })

  it("still handles the transport failures", () => {
    expect(otpVerifyFailureMessage(new ApiError(0, "x"))).toBe(AUTH_NETWORK_FAILURE)
    expect(otpVerifyFailureMessage(new ApiError(503, "x"))).toBe(AUTH_SERVICE_FAILURE)
  })
})

describe("otpRequestFailureMessage", () => {
  /**
   * The other half of the judgement. `OtpRateLimitError` says "OTP already
   * sent; retry in 12s." — a real sentence with a real number, written by a
   * human for a human. Replacing it would lose the seconds, which is the only
   * fact the reader wants.
   */
  it("keeps the 429's own wording, because a human wrote it", () => {
    const detail = "OTP already sent; retry in 12s."
    expect(otpRequestFailureMessage(new ApiError(429, detail, detail))).toBe(detail)
  })

  it("does not keep a 429 with an empty detail", () => {
    const message = otpRequestFailureMessage(new ApiError(429, "429 Too Many Requests", ""))
    expect(message).not.toContain("429")
    expect(message).toMatch(/code/i)
  })

  it("writes its own sentence for a rejected number", () => {
    for (const status of [400, 422]) {
      const message = otpRequestFailureMessage(
        new ApiError(status, "e", "value is not a valid phone number"),
      )
      expect(message, String(status)).not.toContain("valid phone number")
      expect(message, String(status)).toMatch(/country/i)
    }
  })

  it("still handles the transport failures", () => {
    expect(otpRequestFailureMessage(new ApiError(0, "x"))).toBe(AUTH_NETWORK_FAILURE)
    expect(otpRequestFailureMessage(new TypeError("x"))).toBe(AUTH_NETWORK_FAILURE)
    expect(otpRequestFailureMessage(new ApiError(500, "x"))).toBe(AUTH_SERVICE_FAILURE)
  })
})

describe("signUpFailureMessage", () => {
  it("names a lost connection as a connection problem", () => {
    expect(signUpFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
    expect(signUpFailureMessage(new TypeError("Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
  })

  it("says a 5xx is ours, not the reader's account", () => {
    expect(signUpFailureMessage(new ApiError(500, "Internal Server Error"))).toBe(
      AUTH_SERVICE_FAILURE,
    )
  })

  /**
   * D7.12's cooldown is shared plumbing (`CooldownStore`) but not shared
   * manners: `CooldownError.__str__` (`lemely/auth/cooldown.py`) is
   * `Cooldown active for 'x@y.com'; retry in 30s.` — a `repr()`'d email
   * inside a log line, not a sentence a human wrote for a human. Unlike
   * `otpRequestFailureMessage`'s 429 (kept verbatim, above), this one must
   * not be.
   */
  it("does not leak the cooldown's raw wording or the throttled address", () => {
    const detail = "Cooldown active for 'shown@example.com'; retry in 30s."
    const message = signUpFailureMessage(new ApiError(429, detail, detail))
    expect(message).toBe(AUTH_COOLDOWN_ACTIVE)
    expect(message).not.toContain("shown@example.com")
    expect(message).not.toContain("Cooldown active")
  })

  /**
   * Spec §4.3's binding rule, asserted the same way `signInFailureMessage`'s
   * own enumeration test is (above): the message must be identical whichever
   * of the two very differently-worded GoTrue rejections actually happened,
   * must never echo the address, and must never assert the account exists —
   * only offer signing in as one of two possible next steps.
   */
  it("never confirms the address is already registered", () => {
    const duplicate = new ApiError(
      400,
      "Bad Request",
      'GoTrue admin-create failed (422): {"msg":"A user with this email address has already been registered"}',
    )
    const otherRejection = new ApiError(
      400,
      "Bad Request",
      'GoTrue admin-create failed (422): {"msg":"Password should be at least 6 characters"}',
    )
    expect(signUpFailureMessage(duplicate)).toBe(AUTH_SIGNUP_REJECTED)
    expect(signUpFailureMessage(otherRejection)).toBe(AUTH_SIGNUP_REJECTED)
    expect(signUpFailureMessage(duplicate)).toBe(signUpFailureMessage(otherRejection))
    expect(signUpFailureMessage(duplicate)).not.toContain("@")
    expect(AUTH_SIGNUP_REJECTED).not.toMatch(/already (been )?registered|account exists/i)
  })

  it("still offers a route forward for a 403 an honest client can never trigger", () => {
    // `_SELF_SERVICE_SIGNUP_ROLES` makes this unreachable through `SignupVariables`
    // (`AuthContext.tsx`), but the function must still resolve to a sentence
    // rather than throw or fall through to nothing.
    const message = signUpFailureMessage(new ApiError(403, "Forbidden", "role escalation"))
    expect(message).not.toContain("role escalation")
    expect(message.length).toBeGreaterThan(0)
  })
})

describe("verificationFailureMessage", () => {
  it("names a lost connection as a connection problem", () => {
    expect(verificationFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(
      AUTH_NETWORK_FAILURE,
    )
    expect(verificationFailureMessage(new TypeError("Failed to fetch"))).toBe(
      AUTH_NETWORK_FAILURE,
    )
  })

  it("says a 5xx is ours, not the reader's account", () => {
    expect(verificationFailureMessage(new ApiError(503, "Service Unavailable"))).toBe(
      AUTH_SERVICE_FAILURE,
    )
  })

  /**
   * `deps.require_verified_email`'s 403 (`lemely/web/deps.py`) carries
   * `detail={"code": "email_unverified"}` — a structured object, never a
   * string. That function's own docstring calls this a "stable,
   * machine-readable marker (never prose)" for exactly this function to key
   * on, and it is Task 10's route (`POST /student/correct`) that produces it,
   * not either of this function's own two routes.
   */
  it("routes an email_unverified 403 to the verification message", () => {
    const err = new ApiError(403, "403 Forbidden", { code: "email_unverified" })
    expect(verificationFailureMessage(err)).toBe(AUTH_EMAIL_UNVERIFIED)
  })

  /** A 403 that is not the marker — wrong code, no detail, or a string that
   * merely mentions it — must not be mistaken for it. */
  it("does not treat every 403 as the email_unverified marker", () => {
    const wrongCode = new ApiError(403, "403 Forbidden", { code: "something_else" })
    const noDetail = new ApiError(403, "403 Forbidden")
    const stringDetail = new ApiError(403, "403 Forbidden", "email_unverified")
    expect(verificationFailureMessage(wrongCode)).not.toBe(AUTH_EMAIL_UNVERIFIED)
    expect(verificationFailureMessage(noDetail)).not.toBe(AUTH_EMAIL_UNVERIFIED)
    expect(verificationFailureMessage(stringDetail)).not.toBe(AUTH_EMAIL_UNVERIFIED)
  })

  /** `verify-email/resend`'s cooldown is the same `CooldownError` signup's
   * is, keyed here by the caller's own user id rather than an email — still
   * not fit to print (see `signUpFailureMessage`'s matching test above). */
  it("does not leak the cooldown's raw wording or the throttled user id", () => {
    const detail = "Cooldown active for '4c1e2b8a-0000-4000-8000-000000000000'; retry in 30s."
    const message = verificationFailureMessage(new ApiError(429, detail, detail))
    expect(message).toBe(AUTH_COOLDOWN_ACTIVE)
    expect(message).not.toContain("4c1e2b8a")
    expect(message).not.toContain("Cooldown active")
  })

  /**
   * `AuthTokenService.redeem`'s three failure modes
   * (`lemely/db/auth_token_repo.py`) reach the router as the same 400, and
   * `AuthService.verify_email`'s own docstring says why this function must
   * not try to recover the distinction: "the distinction was for the token
   * service's own tests to make", not for a reader here. All three raw
   * reasons must vanish, and all three must produce one identical sentence.
   */
  it("collapses every verify-email token failure to the same plain sentence", () => {
    const detailStrings = [
      "Email verification failed: Token has expired.",
      "Email verification failed: Token has already been redeemed.",
      "Email verification failed: No live token matches this token and purpose.",
    ]
    const messages = detailStrings.map((d) => verificationFailureMessage(new ApiError(400, d, d)))
    for (const [i, message] of messages.entries()) {
      expect(message, detailStrings[i]).toBe(AUTH_LINK_EXPIRED)
      expect(message, detailStrings[i]).not.toContain("Token")
    }
    expect(new Set(messages).size).toBe(1)
  })

  /*
   * DS15's typed code is a different credential from the link, so its failure
   * must not borrow the link's sentence. `verify_email_code` collapses wrong,
   * expired and locked-out into one non-revealing 400
   * (`lemely/web/routers/auth.py`), so the three still produce one identical
   * message — but it is the code's message, and it never says "link".
   */
  it("tells a code failure it was the code, not a link", () => {
    const detailStrings = [
      "Email verification failed: wrong_code",
      "Email verification failed: expired",
      "Email verification failed: locked_out",
    ]
    const messages = detailStrings.map((d) =>
      verificationCodeFailureMessage(new ApiError(400, d, d)),
    )
    for (const [i, message] of messages.entries()) {
      expect(message, detailStrings[i]).toBe(AUTH_CODE_REJECTED)
      // The bug this guards: a typed code reported as an expired *link*.
      expect(message, detailStrings[i]).not.toContain("link")
      expect(message, detailStrings[i]).not.toBe(AUTH_LINK_EXPIRED)
      // No raw backend identifier reaches the reader. Only the snake_case
      // tokens are forbidden — "expired" is ordinary English and belongs in
      // the sentence; it is `wrong_code` as a literal that must never show.
      expect(message, detailStrings[i]).not.toMatch(/wrong_code|locked_out/)
      expect(message, detailStrings[i]).not.toContain("Email verification failed")
    }
    expect(new Set(messages).size).toBe(1)
  })

  it("maps a code failure's other statuses exactly as the link route does", () => {
    expect(verificationCodeFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(
      AUTH_NETWORK_FAILURE,
    )
    expect(verificationCodeFailureMessage(new TypeError("Failed to fetch"))).toBe(
      AUTH_NETWORK_FAILURE,
    )
    expect(verificationCodeFailureMessage(new ApiError(429, "Slow down"))).toBe(
      AUTH_COOLDOWN_ACTIVE,
    )
    expect(verificationCodeFailureMessage(new ApiError(503, "Service Unavailable"))).toBe(
      AUTH_SERVICE_FAILURE,
    )
  })

  it("says the link may have expired, and offers a new one", () => {
    expect(AUTH_LINK_EXPIRED).toMatch(/expired/i)
    expect(AUTH_LINK_EXPIRED).toMatch(/new one/i)
  })
})

describe("resetFailureMessage", () => {
  it("names a lost connection as a connection problem", () => {
    expect(resetFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
    expect(resetFailureMessage(new TypeError("Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
  })

  it("says a 5xx is ours, not the reader's account", () => {
    expect(resetFailureMessage(new ApiError(500, "Internal Server Error"))).toBe(
      AUTH_SERVICE_FAILURE,
    )
  })

  /** `password-reset/request`'s cooldown is D7.12's shared mechanism again —
   * see `signUpFailureMessage`'s matching test for why it is not kept. */
  it("does not leak the cooldown's raw wording or the throttled address", () => {
    const detail = "Cooldown active for 'reset@example.com'; retry in 30s."
    const message = resetFailureMessage(new ApiError(429, detail, detail))
    expect(message).toBe(AUTH_COOLDOWN_ACTIVE)
    expect(message).not.toContain("reset@example.com")
    expect(message).not.toContain("Cooldown active")
  })

  it("collapses a reset-token failure to the same sentence verify-email uses", () => {
    const detail = "Password reset failed: Token has expired."
    expect(resetFailureMessage(new ApiError(400, detail, detail))).toBe(AUTH_LINK_EXPIRED)
  })

  /**
   * `reset_password` has a second, unrelated 400 source: GoTrue itself
   * rejecting the new password (`admin_update_user_password`,
   * `lemely/auth/gotrue.py`), which arrives with a completely different
   * wrapping (`GoTrue admin-update-password failed (...)`) and is not a
   * token problem at all. Documented as a deliberate simplification, not an
   * oversight: this function cannot tell the two apart from status code
   * alone, so both get the same honest-enough "ask for a new link" answer.
   */
  it("also uses the link-expired sentence for GoTrue's own password rejection", () => {
    const detail = 'GoTrue admin-update-password failed (422): {"msg":"Password too short"}'
    const message = resetFailureMessage(new ApiError(400, detail, detail))
    expect(message).toBe(AUTH_LINK_EXPIRED)
    expect(message).not.toContain("too short")
  })
})

describe("inviteFailureMessage", () => {
  it("names a lost connection as a connection problem", () => {
    expect(inviteFailureMessage(new ApiError(0, "Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
    expect(inviteFailureMessage(new TypeError("Failed to fetch"))).toBe(AUTH_NETWORK_FAILURE)
  })

  it("says a 5xx is ours, not the reader's account", () => {
    expect(inviteFailureMessage(new ApiError(502, "Bad Gateway"))).toBe(AUTH_SERVICE_FAILURE)
  })

  it("does not leak the raw code on an unknown invite", () => {
    const detail = "Unknown code: 'ABC123'"
    const message = inviteFailureMessage(new ApiError(404, detail, detail))
    expect(message).toBe(AUTH_INVITE_NOT_FOUND)
    expect(message).not.toContain("ABC123")
  })

  it("does not leak the raw code on an already-redeemed invite", () => {
    const detail = "Invite 'ABC123' has already been redeemed"
    const message = inviteFailureMessage(new ApiError(409, detail, detail))
    expect(message).toBe(AUTH_INVITE_ALREADY_USED)
    expect(message).not.toContain("ABC123")
  })
})
