import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import type { InvitePreview } from "@/lib/authTypes"
import { AUTH_INVITE_ALREADY_USED, AUTH_INVITE_NOT_FOUND } from "@/lib/authOutcome"
import {
  describeInvitePreview,
  isSeatQuotaExceededError,
  isTerminalRedeemFailure,
  normalizeInviteCode,
  previewErrorCopy,
  redeemFailureMessage,
  SEAT_QUOTA_FULL_MESSAGE,
  signupPathForInvite,
} from "@/lib/hooks/useInvitesApi"

/*
 * Task 18 · pure logic behind G-08 (`portals/auth/JoinWithCode.tsx`). No DOM
 * here per this task's environment note (vitest runs the node environment) —
 * every function under test is exported from `useInvitesApi.ts` precisely so
 * it can be exercised directly, without mounting anything.
 */

describe("normalizeInviteCode", () => {
  it("trims and uppercases", () => {
    expect(normalizeInviteCode("  7hkpx2wcqy  ")).toBe("7HKPX2WCQY")
  })

  it("is a no-op on an already-correct code", () => {
    expect(normalizeInviteCode("7HKPX2WCQY")).toBe("7HKPX2WCQY")
  })

  it("collapses whitespace-only input to empty", () => {
    expect(normalizeInviteCode("   ")).toBe("")
  })
})

describe("describeInvitePreview", () => {
  it("renders a school line and a possessive class line when both are present", () => {
    const preview: InvitePreview = {
      role: "student",
      schoolName: "Al-Nasr Language School",
      className: "Physics 0625",
      teacherName: "Mr Hassan",
    }
    expect(describeInvitePreview(preview)).toEqual([
      "Al-Nasr Language School",
      "Mr Hassan's Physics 0625 class",
    ])
  })

  it("renders a bare seat line when there is a school and no class", () => {
    const preview: InvitePreview = {
      role: "student",
      schoolName: "Al-Nasr Language School",
      className: null,
      teacherName: null,
    }
    expect(describeInvitePreview(preview)).toEqual([
      "Al-Nasr Language School",
      "A student seat at this school",
    ])
  })

  it("says 'teacher place' for a teacher-role seat invite", () => {
    const preview: InvitePreview = {
      role: "teacher",
      schoolName: "Al-Nasr Language School",
      className: null,
      teacherName: null,
    }
    expect(describeInvitePreview(preview)).toEqual([
      "Al-Nasr Language School",
      "A teacher place at this school",
    ])
  })

  it("renders only the class line for an independent teacher's class (D7.2, no school)", () => {
    const preview: InvitePreview = {
      role: "student",
      schoolName: null,
      className: "Y11 Physics",
      teacherName: "Ms Ahmed",
    }
    expect(describeInvitePreview(preview)).toEqual(["Ms Ahmed's Y11 Physics class"])
  })

  it("still names the class when the teacher name is absent", () => {
    const preview: InvitePreview = {
      role: "student",
      schoolName: null,
      className: "Y11 Physics",
      teacherName: null,
    }
    expect(describeInvitePreview(preview)).toEqual(["Y11 Physics class"])
  })

  it("falls back to a generic line rather than an empty card (defensive, schema forbids this)", () => {
    const preview: InvitePreview = {
      role: "student",
      schoolName: null,
      className: null,
      teacherName: null,
    }
    expect(describeInvitePreview(preview)).toEqual(["An invite to Lemely"])
  })

  it("never renders an em dash, matching the UI-spec example's shape without its punctuation", () => {
    const preview: InvitePreview = {
      role: "student",
      schoolName: "Al-Nasr Language School",
      className: "Physics 0625",
      teacherName: "Mr Hassan",
    }
    for (const line of describeInvitePreview(preview)) {
      expect(line).not.toContain("—")
    }
  })
})

describe("signupPathForInvite", () => {
  it("builds the student signup path with the code retained", () => {
    expect(signupPathForInvite("7HKPX2WCQY", "student")).toBe(
      "/signup/student?code=7HKPX2WCQY",
    )
  })

  it("builds the teacher signup path", () => {
    expect(signupPathForInvite("7HKPX2WCQY", "teacher")).toBe(
      "/signup/teacher?code=7HKPX2WCQY",
    )
  })

  it("percent-encodes a code that needs it", () => {
    expect(signupPathForInvite("AB CD", "student")).toBe("/signup/student?code=AB%20CD")
  })
})

describe("isSeatQuotaExceededError", () => {
  it("matches the structured marker", () => {
    expect(isSeatQuotaExceededError({ code: "seat_quota_exceeded" })).toBe(true)
  })

  it("rejects a plain string detail (what the live backend actually sends for a 409 today)", () => {
    expect(isSeatQuotaExceededError("Invite 'ABC' has already been redeemed")).toBe(false)
  })

  it("rejects undefined, null, and an unrelated object shape", () => {
    expect(isSeatQuotaExceededError(undefined)).toBe(false)
    expect(isSeatQuotaExceededError(null)).toBe(false)
    expect(isSeatQuotaExceededError({ code: "email_unverified" })).toBe(false)
  })
})

describe("redeemFailureMessage", () => {
  it("gives the quota-specific copy when the marker is present", () => {
    expect(redeemFailureMessage(new ApiError(409, "Conflict", { code: "seat_quota_exceeded" }))).toBe(
      SEAT_QUOTA_FULL_MESSAGE,
    )
  })

  it("falls through to inviteFailureMessage's already-used copy for the real 409 shape", () => {
    expect(
      redeemFailureMessage(new ApiError(409, "Invite 'ABC' has already been redeemed")),
    ).toBe(AUTH_INVITE_ALREADY_USED)
  })

  it("falls through to inviteFailureMessage for a 404", () => {
    expect(redeemFailureMessage(new ApiError(404, "Unknown code"))).toBe(AUTH_INVITE_NOT_FOUND)
  })
})

describe("isTerminalRedeemFailure", () => {
  it("treats 404 and 409 as terminal", () => {
    expect(isTerminalRedeemFailure(new ApiError(404, "Unknown code"))).toBe(true)
    expect(isTerminalRedeemFailure(new ApiError(409, "Already redeemed"))).toBe(true)
  })

  it("treats a network failure and a 5xx as retryable, not terminal", () => {
    expect(isTerminalRedeemFailure(new ApiError(0, "Failed to fetch"))).toBe(false)
    expect(isTerminalRedeemFailure(new ApiError(500, "Internal Server Error"))).toBe(false)
  })

  it("treats a non-ApiError as retryable", () => {
    expect(isTerminalRedeemFailure(new TypeError("boom"))).toBe(false)
  })
})

describe("previewErrorCopy", () => {
  it("offers a fresh code for a 404, and says so is not retryable", () => {
    const copy = previewErrorCopy(new ApiError(404, "Unknown code"))
    expect(copy.heading).toBe("We couldn't find that invite")
    expect(copy.actionLabel).toBe("Try a different code")
    expect(copy.retryable).toBe(false)
  })

  it("offers a retry for a network failure", () => {
    const copy = previewErrorCopy(new ApiError(0, "Failed to fetch"))
    expect(copy.heading).toBe("Something went wrong")
    expect(copy.actionLabel).toBe("Try again")
    expect(copy.retryable).toBe(true)
  })

  it("offers a retry for a 5xx", () => {
    const copy = previewErrorCopy(new ApiError(503, "Service Unavailable"))
    expect(copy.retryable).toBe(true)
  })
})
