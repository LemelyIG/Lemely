/*
 * Pure logic for `SignupParent.tsx` (design spec §5, superseding D3.11's
 * phone-OTP parent login). No React, no DOM — the same split
 * `passwordResetLogic.ts` and `signupDetailsLogic.ts` use, and for the same
 * two reasons: `vitest.config.ts` runs the unit suite in a Node environment
 * with no jsdom (D3.20), so this is what `signupParentLogic.test.ts`
 * exercises directly; and `oxlint`'s `react/only-export-components` warns on
 * a file that exports a component alongside anything else, which a second,
 * non-component module is the rule's own suggested fix for.
 *
 * `MIN_PASSWORD_LENGTH` and `passwordStrength` are imported from
 * `signupDetailsLogic.ts` rather than re-declared here — one floor and one
 * strength meter for the whole product, not a second copy that could drift
 * from G-03's.
 */

import { ApiError } from "@/lib/api"
import {
  AUTH_NETWORK_FAILURE,
  AUTH_SERVICE_FAILURE,
  AUTH_SIGNUP_REJECTED,
  otpRequestFailureMessage,
  otpVerifyFailureMessage,
} from "@/lib/authOutcome"
import { MIN_PASSWORD_LENGTH } from "./signupDetailsLogic"

/**
 * The three states `SignupParent.tsx` renders, derived rather than tracked as
 * a fourth, independent piece of state that could drift from the two facts
 * that actually decide it: whether a code has been sent (`codeSentTo`) and
 * whether that code has been verified (`proofToken`). "Change email"/"Change
 * number"-style back navigation is just clearing the later fact — going from
 * `password` back to `code` clears `proofToken`, and `code` back to `email`
 * clears `codeSentTo` — so there is never a fourth state this function has to
 * reconcile against those two.
 */
export interface ParentSignupProgress {
  /** The email a code was last successfully sent to, or `null` before the
   * first successful `request-code` call this visit. */
  codeSentTo: string | null
  /** The proof token from a successful `verify-code` call, or `null` before
   * one exists (including after a fresh code request invalidates the old
   * one). */
  proofToken: string | null
}

export function parentSignupStep(progress: ParentSignupProgress): "email" | "code" | "password" {
  if (progress.proofToken) return "password"
  if (progress.codeSentTo) return "code"
  return "email"
}

/** Loose but sufficient for a client-side hint, matching
 * `signupDetailsLogic.ts`'s own pattern — the server is the real validator. */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export interface ParentEmailStepErrors {
  email?: string
}

/**
 * Step 1's validation: email only. `displayName` is never checked here — it
 * is optional on the wire (`ParentSignupBody.displayName?`), so this screen
 * must not invent a requirement the backend does not have.
 */
export function validateParentEmailStep(email: string): ParentEmailStepErrors {
  const trimmed = email.trim()
  if (trimmed.length === 0) return { email: "Enter your email address." }
  if (!EMAIL_PATTERN.test(trimmed)) return { email: "Enter a valid email address." }
  return {}
}

export interface ParentPasswordStepErrors {
  password?: string
}

/** Step 3's validation: the same floor `signupDetailsLogic.ts` enforces for
 * every other self-service signup, so a parent account is never held to a
 * looser standard than a student or teacher one. */
export function validateParentPasswordStep(password: string): ParentPasswordStepErrors {
  if (password.length === 0) return { password: "Enter a password." }
  if (password.length < MIN_PASSWORD_LENGTH) {
    return { password: `Use at least ${MIN_PASSWORD_LENGTH} characters.` }
  }
  return {}
}

/**
 * Gate for the developer-only code panel on step 2. Mirrors
 * `passwordResetDevPanel` (`passwordResetLogic.ts`) exactly, applied here to
 * `ParentCodeRequestResponse.devCode` rather than `devLink`: the panel exists
 * only when the configured `EmailProvider` did not deliver out of band, and a
 * real provider makes this stop existing on its own, with no client-side
 * environment flag to keep in sync.
 */
export function parentSignupDevPanel(devCode: string | null): { visible: boolean; code: string | null } {
  return devCode === null ? { visible: false, code: null } : { visible: true, code: devCode }
}

/** §5's required copy for a missing or dead invite code — shown instead of
 * the whole three-step form, both when `/signup/parent` is opened with no
 * `?code=` at all and when the code named turns out not to resolve to a live
 * parent invite (a 404 from any of the three parent-signup routes). */
export function parentInviteMissingCopy(): { heading: string; body: string; actionLabel: string } {
  return {
    heading: "This invite link doesn't work",
    body: "The code in this link is missing, expired, or already used. Ask your child to send you a fresh one.",
    actionLabel: "Enter a different code",
  }
}

export interface ParentRequestCodeFailure {
  /** Empty when `deadInvite` is true — the caller swaps the whole screen for
   * `parentInviteMissingCopy()`'s panel instead of rendering this inline. */
  message: string
  /** The invite named by `?code=` does not resolve to a live parent invite
   * (404) — indistinguishable, by the same anti-enumeration design
   * `previewErrorCopy` documents (`useInvitesApi.ts`), from a code that never
   * existed at all. */
  deadInvite: boolean
  /** The email already has an account (400) — the caller offers a sign-in
   * link alongside the message rather than a generic rejection. */
  hasAccount: boolean
}

/**
 * Turn a failed `POST /auth/parent/request-code` into what step 1 should do
 * about it. The two branches specific to this route — a 404 that means "the
 * invite died, swap the whole screen", a 400 that means "this email already
 * has an account" — are handled here; everything else (network loss, the
 * cooldown/rate-limit 429, a 5xx, the generic fallback) is delegated to
 * `otpRequestFailureMessage` (`authOutcome.ts`) rather than re-implemented.
 * That function already owns exactly this shape of classification for the
 * phone-OTP request this route replaces, and its 429 branch already keeps
 * the backend's own human-written detail verbatim — review round 1 found the
 * first cut of this function had quietly duplicated that logic instead of
 * calling it, the same "layer route-specific classification on top of, not
 * inside, the shared module" reasoning `useInvitesApi.ts`'s own
 * `redeemFailureMessage` follows for `inviteFailureMessage`.
 *
 * Only reached for a status `otpRequestFailureMessage` would otherwise map
 * to its own 400/422 branch ("check the digits and the country") — that
 * copy is phone-specific and wrong here, which is exactly why 400 is
 * intercepted above it rather than falling through.
 */
export function parentRequestCodeFailure(err: unknown): ParentRequestCodeFailure {
  if (err instanceof ApiError) {
    if (err.status === 404) return { message: "", deadInvite: true, hasAccount: false }
    if (err.status === 400) {
      return {
        message: "That email already has a Lemely account. Sign in, then open this invite again to add this child.",
        deadInvite: false,
        hasAccount: true,
      }
    }
  }
  return { message: otpRequestFailureMessage(err), deadInvite: false, hasAccount: false }
}

export interface ParentVerifyCodeFailure {
  message: string
  /** The email gained an account in the window between this step's own
   * `request-code` call and this one (400) — the caller offers a sign-in
   * link alongside the message, the same `hasAccount` shape
   * `parentRequestCodeFailure` above already gives its own 400. */
  hasAccount: boolean
}

/**
 * Turn a failed `POST /auth/parent/verify-code` into what step 2 should do
 * about it. The dead-invite 404 is handled by the caller the same way
 * `parentRequestCodeFailure`'s `deadInvite` is (`SignupParent.tsx`'s own
 * `handleVerify`) — this function is only reached once that branch has
 * already been ruled out.
 *
 * The 400 this route can return — `routers/auth.py`'s `verify_parent_code`
 * re-checks the email is still unclaimed before it ever touches the OTP
 * store (final review I-1's ordering), so its only 400 is
 * `_EMAIL_TAKEN_DETAIL`: the address gained an account in the window since
 * this same email's own `request-code` call. Left to fall through to
 * `otpVerifyFailureMessage`'s generic "we couldn't check that code" copy,
 * the reader would be told to retry a code that can never succeed — the
 * account isn't unclaimed anymore, no code will fix that — so it is
 * intercepted here with parent-specific copy instead, the same
 * "layer route-specific classification on top of, not inside, the shared
 * module" reasoning `parentRequestCodeFailure` above already follows for
 * `otpRequestFailureMessage`. Everything else (network loss, a wrong code,
 * a 5xx, the generic fallback) is delegated to `otpVerifyFailureMessage`
 * (`authOutcome.ts`) unchanged.
 */
export function parentVerifyCodeFailure(err: unknown): ParentVerifyCodeFailure {
  if (err instanceof ApiError && err.status === 400) {
    return {
      message: "This address now has a Lemely account. Sign in and open your invite instead.",
      hasAccount: true,
    }
  }
  return { message: otpVerifyFailureMessage(err), hasAccount: false }
}

/**
 * Turn a failed `POST /auth/parent/signup` into a sentence for step 3. A 404
 * here (the invite died between verify and this final call) is handled by
 * the caller the same way `parentRequestCodeFailure`'s `deadInvite` is — this
 * function is only reached once that branch has already been ruled out.
 */
export function parentSignupFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 401) {
      return "That took too long and your verification expired. Start again with your email address."
    }
    if (err.status === 400) return AUTH_SIGNUP_REJECTED
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't create your account just then. Trying again usually sorts it."
}
