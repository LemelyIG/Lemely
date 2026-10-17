/*
 * Pure logic for G-07 (`VerifyEmail.tsx`). No React, no DOM — the same split
 * `onboardingData.ts` uses for the S-01/S-02 wizard, and for the same reason:
 * `vitest.config.ts` runs the unit suite in a Node environment with no
 * jsdom/@testing-library (D3.20), so this is what `verifyEmail.test.ts`
 * exercises directly, and it is also the house fix for `oxlint`'s
 * `react/only-export-components` (`.oxlintrc.json`) — a file that exports a
 * component may not also export plain functions/constants without warning,
 * and the fix the warning itself names is exactly this: a second, non-
 * component module. Component behaviour beyond these two decisions is
 * Playwright's job (Task 23), not this file's.
 */

import { portalPathForRole } from "@/lib/auth/RequireAuth"
import type { Session } from "@/lib/auth/storage"

/**
 * Where a confirmed `/verify-email/:token` sends the reader (binding
 * requirement 4: "confirms and routes to the role home").
 *
 * `VerifyEmailResponse` (`authTypes.ts`) is `{ status: "verified" }` and
 * nothing else. The redeem route is public (spec §4.3's API table), so it
 * verifies whichever account the token names — it is not scoped to the
 * caller's own bearer token — and its response carries no role to route on.
 * The only signal this screen has for "the role home" is therefore the
 * browser's own live session, which is a sound read of the path spec §5.1
 * describes (the same person, on the same device they signed up on,
 * following a link in the same browser) but not a guarantee for every path a
 * verification link can be opened from. With no role on the wire to trust
 * instead, routing off the live session is the honest best available answer;
 * a reader with no session at all is sent to sign in rather than guessed at.
 */
export function postVerifyPath(session: Pick<Session, "role"> | null): string {
  if (!session) return "/login"
  return portalPathForRole(session.role)
}

/**
 * The resend button's label, pinned as a pure function because the priority
 * between "counting down" and "in flight" is exactly the kind of ordering
 * that silently inverts in a refactor and only shows up as a flash of wrong
 * text on screen. Cooldown wins: once a send has been accepted, the count is
 * the fact worth showing even while the tail of that same request is still
 * settling `isPending` back to false.
 */
export function resendButtonLabel(state: { cooldownSeconds: number; isPending: boolean }): string {
  if (state.cooldownSeconds > 0) return `Resend link in ${state.cooldownSeconds}s`
  if (state.isPending) return "Sending…"
  return "Resend verification link"
}

/**
 * DS15's typed-code companion to the link: whether the "Verify code" button
 * in `SignedInPending` may be pressed. `/^\d{6}$/` rather than `code.length
 * === 6` — six characters that are not all digits (a pasted fragment with a
 * stray space, say) would satisfy a length check but never a real code, and
 * the field itself only ever contains digits by construction, so this is a
 * belt-and-suspenders check, not a redundant one: it stays correct even if a
 * future caller feeds this function something the field's own `onChange`
 * did not sanitise. The same two-part shape as `resendButtonLabel` above —
 * format plus "not already in flight" — rather than duplicating the
 * server's own attempt-cap or lockout logic, neither of which this function
 * can see.
 */
export function canSubmitCode(code: string, isPending: boolean): boolean {
  return /^\d{6}$/.test(code) && !isPending
}
