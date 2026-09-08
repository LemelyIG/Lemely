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
import { AUTH_NETWORK_FAILURE, AUTH_SERVICE_FAILURE, AUTH_SIGNUP_REJECTED } from "@/lib/authOutcome"
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
 * about it. Not folded into `authOutcome.ts`: that module owns sentences
 * shared across screens, and every branch here is specific to this one route
 * (a 400 that means "this email already has an account", a 404 that means
 * "swap the whole screen", a 429 whose `detail` is already a sentence a human
 * wrote) — the same reasoning `useInvitesApi.ts`'s own `redeemFailureMessage`
 * gives for layering route-specific classification on top of, rather than
 * inside, the shared module.
 */
export function parentRequestCodeFailure(err: unknown): ParentRequestCodeFailure {
  if (err instanceof ApiError) {
    if (err.status === 404) return { message: "", deadInvite: true, hasAccount: false }
    if (err.status === 400) {
      return {
        message: "That email already has a Lemely account. Sign in to add this child from there instead.",
        deadInvite: false,
        hasAccount: true,
      }
    }
    // The backend's own cooldown/rate-limit detail is a sentence a human
    // wrote ("retry in 12s"), kept verbatim — the same call
    // `otpRequestFailureMessage` makes for the OTP request 429 it replaces.
    if (err.status === 429 && typeof err.detail === "string" && err.detail.trim() !== "") {
      return { message: err.detail.trim(), deadInvite: false, hasAccount: false }
    }
    if (err.status === 0) return { message: AUTH_NETWORK_FAILURE, deadInvite: false, hasAccount: false }
    if (err.status >= 500) return { message: AUTH_SERVICE_FAILURE, deadInvite: false, hasAccount: false }
  }
  if (err instanceof TypeError) return { message: AUTH_NETWORK_FAILURE, deadInvite: false, hasAccount: false }
  return {
    message: "We couldn't send a code just then. Trying again usually sorts it.",
    deadInvite: false,
    hasAccount: false,
  }
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
