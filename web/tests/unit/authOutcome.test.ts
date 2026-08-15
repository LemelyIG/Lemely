import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  AUTH_BAD_CREDENTIALS,
  AUTH_NETWORK_FAILURE,
  AUTH_SERVICE_FAILURE,
  otpRequestFailureMessage,
  otpVerifyFailureMessage,
  signInFailureMessage,
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
