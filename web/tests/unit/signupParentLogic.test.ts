import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { AUTH_NETWORK_FAILURE, AUTH_SERVICE_FAILURE, AUTH_SIGNUP_REJECTED } from "@/lib/authOutcome"
import {
  parentInviteMissingCopy,
  parentRequestCodeFailure,
  parentSignupDevPanel,
  parentSignupFailureMessage,
  parentSignupStep,
  validateParentEmailStep,
  validateParentPasswordStep,
} from "@/portals/auth/signupParentLogic"

/*
 * Pure logic behind `SignupParent.tsx` (design spec §5). No DOM, matching
 * this project's vitest environment (node) — every function here is exported
 * from `signupParentLogic.ts` precisely so it can be exercised directly.
 */

describe("parentSignupStep", () => {
  it("starts at the email step with nothing sent or verified", () => {
    expect(parentSignupStep({ codeSentTo: null, proofToken: null })).toBe("email")
  })

  it("moves to the code step once a code has been sent", () => {
    expect(parentSignupStep({ codeSentTo: "parent@example.com", proofToken: null })).toBe("code")
  })

  it("moves to the password step once the code is verified", () => {
    expect(
      parentSignupStep({ codeSentTo: "parent@example.com", proofToken: "proof-token" }),
    ).toBe("password")
  })

  it("a proof token wins even if codeSentTo were somehow cleared", () => {
    expect(parentSignupStep({ codeSentTo: null, proofToken: "proof-token" })).toBe("password")
  })
})

describe("validateParentEmailStep", () => {
  it("requires an email", () => {
    expect(validateParentEmailStep("")).toEqual({ email: "Enter your email address." })
    expect(validateParentEmailStep("   ")).toEqual({ email: "Enter your email address." })
  })

  it("rejects an obviously malformed address", () => {
    expect(validateParentEmailStep("not-an-email")).toEqual({
      email: "Enter a valid email address.",
    })
  })

  it("accepts a well-formed address", () => {
    expect(validateParentEmailStep("parent@example.com")).toEqual({})
  })
})

describe("validateParentPasswordStep", () => {
  it("requires a password", () => {
    expect(validateParentPasswordStep("")).toEqual({ password: "Enter a password." })
  })

  it("enforces the same floor as student/teacher signup", () => {
    expect(validateParentPasswordStep("short1")).toEqual({
      password: "Use at least 8 characters.",
    })
  })

  it("accepts a password at or above the floor", () => {
    expect(validateParentPasswordStep("longenoughpassword")).toEqual({})
  })
})

describe("parentSignupDevPanel — mirrors passwordResetDevPanel", () => {
  it("is hidden with no dev code", () => {
    expect(parentSignupDevPanel(null)).toEqual({ visible: false, code: null })
  })

  it("is visible and carries the code when present", () => {
    expect(parentSignupDevPanel("482913")).toEqual({ visible: true, code: "482913" })
  })
})

describe("parentInviteMissingCopy", () => {
  it("names the fix rather than only the problem", () => {
    const copy = parentInviteMissingCopy()
    expect(copy.heading.length).toBeGreaterThan(0)
    expect(copy.body).toMatch(/fresh one/i)
    expect(copy.actionLabel).toMatch(/different code/i)
  })
})

describe("parentRequestCodeFailure", () => {
  it("flags a 404 as a dead invite, with no inline message", () => {
    const failure = parentRequestCodeFailure(new ApiError(404, "Unknown code"))
    expect(failure.deadInvite).toBe(true)
    expect(failure.message).toBe("")
  })

  it("flags a 400 as an existing account, without confirming it", () => {
    const failure = parentRequestCodeFailure(new ApiError(400, "Bad Request"))
    expect(failure.hasAccount).toBe(true)
    expect(failure.deadInvite).toBe(false)
    expect(failure.message.length).toBeGreaterThan(0)
  })

  /**
   * `otpRequestFailureMessage`'s 429 branch (final review I-4) no longer
   * forwards the server detail verbatim — one of its two possible sources
   * is `OtpRateLimitError`'s "OTP already sent; retry in 12s.", and "OTP" is
   * not a word this screen may show a parent typing an email address. Only
   * the seconds carry through, wrapped in a sentence written for this
   * reader; see `authOutcome.test.ts` for the full behaviour.
   */
  it("keeps the seconds from a 429's own detail, without echoing raw server wording", () => {
    const detail = "OTP already sent; retry in 12s."
    const failure = parentRequestCodeFailure(new ApiError(429, detail, detail))
    expect(failure.message).not.toBe(detail)
    expect(failure.message).not.toContain("OTP")
    expect(failure.message).toContain("12")
  })

  it("maps transport and server failures to the shared sentences", () => {
    expect(parentRequestCodeFailure(new ApiError(0, "x")).message).toBe(AUTH_NETWORK_FAILURE)
    expect(parentRequestCodeFailure(new TypeError("x")).message).toBe(AUTH_NETWORK_FAILURE)
    expect(parentRequestCodeFailure(new ApiError(500, "x")).message).toBe(AUTH_SERVICE_FAILURE)
  })
})

describe("parentSignupFailureMessage", () => {
  it("tells the reader to start again on an expired proof (401)", () => {
    expect(parentSignupFailureMessage(new ApiError(401, "Unauthorized"))).toMatch(/start again/i)
  })

  it("uses the shared signup-rejected sentence for a 400", () => {
    expect(parentSignupFailureMessage(new ApiError(400, "Bad Request"))).toBe(AUTH_SIGNUP_REJECTED)
  })

  it("maps transport and server failures to the shared sentences", () => {
    expect(parentSignupFailureMessage(new ApiError(0, "x"))).toBe(AUTH_NETWORK_FAILURE)
    expect(parentSignupFailureMessage(new ApiError(500, "x"))).toBe(AUTH_SERVICE_FAILURE)
  })
})
