/*
 * Pure logic for G-06 (`PasswordReset.tsx`). No React, no DOM — the same
 * split `onboardingData.ts` uses for the S-01/S-02 wizard and
 * `verifyEmailLogic.ts` uses for G-07, and for the same reason:
 * `vitest.config.ts` runs the unit suite in a Node environment with no
 * jsdom/@testing-library (D3.20), so this is what `passwordReset.test.ts`
 * exercises directly, and it is also the house fix for `oxlint`'s
 * `react/only-export-components` (`.oxlintrc.json`) — a file that exports a
 * component may not also export plain functions/constants without warning,
 * and the fix the warning itself names is exactly this: a second, non-
 * component module. Component behaviour beyond these decisions is
 * Playwright's job (Task 23), not this file's.
 *
 * The three functions and one constant below carry the two security
 * decisions Task 17 is binding on:
 *
 *   - `passwordResetSentBody` and `passwordResetDevPanel` together are the
 *     UI half of the anti-enumeration rule (Requirement 1): the confirmation
 *     screen says the same thing whether or not the address exists, and
 *     never claims a mail was sent (Requirement 3).
 *   - `PASSWORD_RESET_SUCCESS_BODY` states plainly that every device has
 *     been signed out (Requirement 2).
 *   - `showResetSuccess` is not a security decision itself, but the guard
 *     that keeps the success state honest per-token — see its own docstring.
 */

/**
 * The confirmation copy for `/reset` once a request has been submitted.
 *
 * Pure and kept pinned to Requirement 1 (spec's anti-enumeration wording
 * rule) by construction, not by a future editor's care: the function takes
 * only the email the visitor typed, so there is no parameter through which
 * "does this account exist" could ever reach the string it returns.
 * `AuthService.request_password_reset` answers 200 either way and mints
 * nothing for an unknown address — its own docstring calls the two outcomes
 * "indistinguishable by design" — and this function is the UI's half of
 * that: it has no data path by which its output could differ between an
 * address that exists and one that does not. Echoing the typed address back
 * is not a leak; the visitor already knows what they typed, the same
 * reasoning `ParentLogin.tsx`'s `CodeStep` relies on when it echoes the
 * phone number back.
 *
 * Also the load-bearing half of Requirement 3 (never claim a mail was
 * sent): `deps.py` wires `MockEmailProvider()` unconditionally, so an
 * unconditional "we sent"/"we emailed" claim would be false in every real
 * deployment of this code, the exact defect `routes.tsx` records against
 * `ParentLogin`'s own `CodeStep` ("We sent a 6-digit code to ..."). This
 * sentence never asserts delivery happened; it says only what is true in
 * every case, that a reset was started for an account that exists.
 */
export function passwordResetSentBody(email: string): string {
  return (
    `If an account exists for ${email}, we've started a password reset for it. ` +
    "Look for an email with a link to set a new password. The link stays active for about an hour."
  )
}

/**
 * Gate for the developer-only reset-link panel on `/reset`.
 *
 * Mirrors §G-05's `devCode` handling exactly (D3.16, applied to email by
 * D7.6): the panel exists only when `devLink` is non-null, i.e. only when
 * the configured `EmailProvider` did not deliver out of band. A real
 * provider, once one is ever configured, makes the backend return `null`
 * unconditionally and this panel stops existing on its own — no client-side
 * environment flag to keep in sync.
 *
 * Worth being explicit about the tension with `passwordResetSentBody`
 * above: `devLink` is non-null exactly when the address is known AND
 * nothing has reached an inbox (`PasswordResetRequestResponse.devLink`'s own
 * comment in `authTypes.ts`), so as long as `MockEmailProvider` is the only
 * provider ever wired, the PRESENCE of this panel is itself correlated with
 * account existence, in a way `passwordResetSentBody`'s output deliberately
 * is not. That is not a gap this function introduces or can close — the
 * panel is exactly what Requirement 3 and the D3.16 `devCode` precedent
 * instruct building, and `deps.py`'s wiring is backend and out of scope here
 * — but it is recorded rather than left for a future reader to rediscover,
 * the same way the SMS mock's own honesty gap is recorded in `routes.tsx`.
 */
export function passwordResetDevPanel(
  devLink: string | null,
): { visible: boolean; link: string | null } {
  return devLink === null ? { visible: false, link: null } : { visible: true, link: devLink }
}

/**
 * Requirement 2. `AuthService.reset_password` revokes every outstanding
 * `auth_tokens` row AND every device session (`lemely/auth/service.py`, step
 * 3 of its own docstring) because the reason for a reset may be a
 * compromise. Surfacing that here, in plain language, is the difference
 * between a stated security property and a stranger's phone quietly signing
 * out later with no explanation attached. A constant, not a function: this
 * copy is static and true regardless of which device or account triggered
 * it, so there is nothing to parameterise.
 */
export const PASSWORD_RESET_SUCCESS_BODY =
  "Your new password is saved. For safety, every device that was signed in to your account " +
  "has now been signed out, so sign in again wherever you use Lemely."

/**
 * Whether `/reset/:token` should show its success view.
 *
 * `isSuccess` alone is not enough. `PasswordResetConfirm` cannot rely on
 * local `useState` the way `PasswordResetRequest` safely does for its own
 * "which view" decision, because `/reset` has no dynamic segment to
 * distinguish "fresh mount" from "same mount, new resource" and
 * `/reset/:token` does: React Router does not remount a routed component
 * merely because its own `:token` param changed, so local state keyed on
 * nothing would carry a SUCCEEDED flag from one token onto a DIFFERENT
 * token viewed in the same tab (reachable via the browser's back/forward
 * history across two `/reset/:token` visits). This closes that instead: it
 * is true only when the last successful call's own token matches the token
 * currently in the URL, so switching the URL without a fresh submission
 * cannot show success for a token nothing was actually confirmed for.
 */
export function showResetSuccess(
  isSuccess: boolean,
  succeededToken: string | undefined,
  currentToken: string,
): boolean {
  return isSuccess && currentToken !== "" && succeededToken === currentToken
}
