import { describe, expect, it } from "vitest"
import {
  passwordResetDevPanel,
  passwordResetSentBody,
  showResetSuccess,
} from "@/portals/auth/PasswordReset"

/*
 * G-06 · Task 17. Three pure functions, each pinning one of the binding
 * requirements a JSX read alone cannot enforce:
 *
 *   - `passwordResetSentBody`  Requirement 1 (identical wording regardless
 *     of whether the address exists).
 *   - `passwordResetDevPanel`  Requirement 3 (never claim a mail was sent;
 *     the developer affordance only ever appears when the backend says
 *     nothing else could have delivered it).
 *   - `showResetSuccess`       the guard that keeps a stale success from one
 *     reset link from bleeding onto a different one viewed in the same tab
 *     (module docstring, "Why the two screens pick their 'which view' logic
 *     differently").
 *
 * `environment: "node"` (vitest.config.ts) — no DOM here, which is exactly
 * right for these: all three are plain functions of their arguments, with no
 * component to mount.
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

  it("echoes back only the email the caller passed in, nothing else varies with it", () => {
    // The function's SIGNATURE is the enforcement mechanism for Requirement
    // 1: it takes an email and nothing else, so there is no parameter an
    // account-exists flag could ever be threaded through. This test proves
    // the two outputs differ ONLY in the substituted address, never in
    // surrounding structure — the shape a caller that started branching on
    // a second, hidden argument would break.
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
