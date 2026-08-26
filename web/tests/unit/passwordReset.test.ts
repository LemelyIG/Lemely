import { describe, expect, it } from "vitest"

import {
  PASSWORD_RESET_SUCCESS_BODY,
  passwordResetDevPanel,
  passwordResetSentBody,
  showResetSuccess,
} from "@/portals/auth/passwordResetLogic"

/*
 * G-06 · the pure decisions `PasswordReset.tsx` makes, pinned in isolation
 * (`vitest.config.ts` runs the node environment on purpose — see
 * `onboarding.test.ts`/`onboardingData.ts` and `verifyEmail.test.ts`/
 * `verifyEmailLogic.ts` for the house precedent this follows: pure logic
 * lives in its own sibling module so a component file only ever exports its
 * component).
 *
 * Two of Task 17's four binding requirements are security decisions and are
 * the reason this file exists rather than being skipped as "just copy":
 *
 *   - Requirement 1 (anti-enumeration): the confirmation screen must say the
 *     same thing whether or not the address exists.
 *   - Requirement 2: the success screen must state that all devices have
 *     been signed out.
 *
 * Neither function is exercised end to end by a mounted component here: this
 * suite is for the branching/copy logic itself, not for React Query wiring
 * or DOM output, which is what the Playwright E2E journey (Task 23) covers
 * instead.
 */

describe("passwordResetSentBody — Requirement 1 (anti-enumeration wording)", () => {
  it("frames the outcome as conditional on the account existing, never asserts it", () => {
    // The dangerous wrong implementation this guards against is a sentence
    // that states existence as fact ("We found your account and sent a
    // link"), which is exactly the oracle `request_password_reset`'s own
    // 200-either-way behaviour exists to close.
    expect(passwordResetSentBody("student@example.com")).toMatch(/^if an account exists/i)
  })

  it("never asserts that a mail was sent, only that a reset was started", () => {
    // Requirement 3, restated for this specific string: `deps.py` wires
    // MockEmailProvider unconditionally, so an unconditional "we sent" or
    // "we emailed" claim here would be false in every real deployment of
    // this code, the same defect `routes.tsx` records against ParentLogin's
    // CodeStep ("We sent a 6-digit code to ...").
    const body = passwordResetSentBody("student@example.com")
    expect(body).not.toMatch(/we('| ha)ve sent|we emailed|an email was sent/i)
  })

  it("produces byte-identical output for a real address and a made-up one", () => {
    // This is Requirement 1's sharpest test: the same function call, with
    // only the typed address varying, standing in for "account exists" vs
    // "account does not exist" — because the function's SIGNATURE (email in,
    // nothing else) makes those two cases literally the same code path.
    // Substituting the address back out proves nothing besides it differs
    // between the two calls, which is exactly what the caller themselves
    // already knows (they typed it) and is not an enumeration signal.
    const known = passwordResetSentBody("real.student@example.com")
    const unknown = passwordResetSentBody("nobody.here@example.com")
    expect(known.replace("real.student@example.com", "@")).toBe(
      unknown.replace("nobody.here@example.com", "@"),
    )
  })

  it("mentions checking email, so the reader knows where to look next", () => {
    expect(passwordResetSentBody("a@b.com")).toMatch(/email/i)
  })
})

describe("passwordResetDevPanel — Requirement 3 (devLink developer affordance)", () => {
  it("is hidden when devLink is null (a real provider delivered, or no such account)", () => {
    // Both of `request_password_reset`'s null cases collapse to the same
    // "hidden" outcome here, on purpose (authTypes.ts's own comment on
    // `PasswordResetRequestResponse.devLink`): a caller of this function has
    // no way to ask, and must have no way to ask, which of the two it was.
    expect(passwordResetDevPanel(null)).toEqual({ visible: false, link: null })
  })

  it("surfaces the link when devLink is present (the offline mock provider)", () => {
    expect(passwordResetDevPanel("/reset/abc123token")).toEqual({
      visible: true,
      link: "/reset/abc123token",
    })
  })
})

describe("PASSWORD_RESET_SUCCESS_BODY — Requirement 2 (every device signed out)", () => {
  it("states plainly that every device has been signed out", () => {
    // The property this whole constant exists to pin: `reset_password`
    // revokes every device row unconditionally (lemely/auth/service.py, step
    // 3), because the reason for a reset may be a compromise. A screen that
    // changed the password and said nothing about it would turn a stated
    // security property into a confusing surprise on someone's phone later
    // — exactly the failure mode Task 17 names this requirement to prevent.
    expect(PASSWORD_RESET_SUCCESS_BODY).toMatch(/every device/i)
    expect(PASSWORD_RESET_SUCCESS_BODY).toMatch(/signed out/i)
  })

  it("confirms the password itself changed, not only the device sign-out", () => {
    // A message that ONLY talked about devices, with no confirmation the
    // password change itself succeeded, would leave the actual point of the
    // screen unstated.
    expect(PASSWORD_RESET_SUCCESS_BODY).toMatch(/password is saved/i)
  })
})

describe("showResetSuccess — guards against a stale success from a different token", () => {
  const TOKEN_A = "token-a-live-and-unused"
  const TOKEN_B = "token-b-a-different-reset-link"

  it("is false before any submission has succeeded", () => {
    expect(showResetSuccess(false, undefined, TOKEN_A)).toBe(false)
  })

  it("is true once the confirm call for THIS token has succeeded", () => {
    expect(showResetSuccess(true, TOKEN_A, TOKEN_A)).toBe(true)
  })

  it("is false when the last succeeded call was for a DIFFERENT token", () => {
    // The regression case the whole function exists for: React Router does
    // not remount `PasswordResetConfirm` merely because `:token` changed
    // (e.g. browser back/forward between two `/reset/:token` visits), so a
    // wrong implementation that only checked `isSuccess` would show
    // "Password changed" for a link nobody has actually redeemed yet.
    expect(showResetSuccess(true, TOKEN_A, TOKEN_B)).toBe(false)
  })

  it("is false for an empty (missing) current token even if isSuccess is somehow true", () => {
    expect(showResetSuccess(true, TOKEN_A, "")).toBe(false)
  })
})
