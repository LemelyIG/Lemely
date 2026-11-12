import { describe, expect, it } from "vitest"

import { canSubmitCode, postVerifyPath, resendButtonLabel } from "@/portals/auth/verifyEmailLogic"

/*
 * G-07 · the two pure decisions `VerifyEmail.tsx` makes, pinned in isolation
 * (`vitest.config.ts` runs the node environment on purpose — see
 * `onboarding.test.ts`/`onboardingData.ts` for the house precedent this
 * follows: pure logic lives in its own sibling module so a component file
 * only ever exports its component).
 *
 * Neither function is exercised end to end by a mounted component here: this
 * suite is for the branching logic itself, not for React Query wiring or DOM
 * output, which is what the Playwright E2E journey (Task 23) covers instead.
 */
describe("postVerifyPath — binding requirement 4 (route to the role home)", () => {
  it("sends a signed-out reader to sign in, never guesses a portal for them", () => {
    // The dangerous wrong implementation defaults to some portal path when
    // there is no session to read a role from. There is nothing to route on
    // in that case (`VerifyEmailResponse` carries no role — see the
    // function's own docstring), so the only honest answer is /login.
    expect(postVerifyPath(null)).toBe("/login")
  })

  it("routes a signed-in student to /student", () => {
    expect(postVerifyPath({ role: "student" })).toBe("/student")
  })

  it("routes a signed-in teacher to /teacher", () => {
    expect(postVerifyPath({ role: "teacher" })).toBe("/teacher")
  })

  it("routes a signed-in school_admin to /school, not /teacher", () => {
    // The two roles that share TEACHER_ROLES in routes.tsx's RequireAuth
    // guard still have distinct *home* paths (portalPathForRole, P4.7) — a
    // wrong implementation that conflates "reaches" with "home" would pass
    // routes.tsx's own guard test while sending a school_admin to the wrong
    // landing screen.
    expect(postVerifyPath({ role: "school_admin" })).toBe("/school")
  })

  it("routes a signed-in platform_admin to /platform", () => {
    expect(postVerifyPath({ role: "platform_admin" })).toBe("/platform")
  })
})

describe("resendButtonLabel — cooldown outranks in-flight", () => {
  it("shows the plain call to action at rest", () => {
    expect(resendButtonLabel({ cooldownSeconds: 0, isPending: false })).toBe(
      "Resend verification link",
    )
  })

  it("shows the sending state while the mutation is in flight and no cooldown is active", () => {
    expect(resendButtonLabel({ cooldownSeconds: 0, isPending: true })).toBe("Sending…")
  })

  it("counts down once a send has been accepted", () => {
    expect(resendButtonLabel({ cooldownSeconds: 12, isPending: false })).toBe(
      "Resend link in 12s",
    )
  })

  it("prefers the countdown over the in-flight label at the seam between them", () => {
    // The moment a resend's onSuccess handler starts the cooldown, the
    // mutation's own isPending flag has not necessarily settled back to
    // false yet on the same render. A wrong implementation that checks
    // isPending first would flash "Sending…" over a countdown that has
    // already started — the exact silent inversion this test exists to
    // catch, per the function's own docstring.
    expect(resendButtonLabel({ cooldownSeconds: 30, isPending: true })).toBe(
      "Resend link in 30s",
    )
  })

  it("counts down to zero and returns to the plain label", () => {
    expect(resendButtonLabel({ cooldownSeconds: 1, isPending: false })).toBe(
      "Resend link in 1s",
    )
    expect(resendButtonLabel({ cooldownSeconds: 0, isPending: false })).toBe(
      "Resend verification link",
    )
  })
})

describe("canSubmitCode — DS15's typed-code companion to the link", () => {
  it("rejects five digits", () => {
    expect(canSubmitCode("12345", false)).toBe(false)
  })

  it("accepts six digits at rest", () => {
    expect(canSubmitCode("123456", false)).toBe(true)
  })

  it("rejects six digits while the mutation is pending", () => {
    expect(canSubmitCode("123456", true)).toBe(false)
  })

  it("rejects non-digit characters even at length six", () => {
    expect(canSubmitCode("12a456", false)).toBe(false)
  })
})
