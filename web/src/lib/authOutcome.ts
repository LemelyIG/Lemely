import { ApiError } from "@/lib/api"

/*
 * P4.7 · What someone is told when they cannot get in.
 *
 * The fifth member of the family, after `correctionOutcome.ts` (P4.2),
 * `friendOutcome.ts` (P4.4), `teacherOutcome.ts` (P4.5) and `parentOutcome.ts`
 * (P4.6). It is the last one written and the first one anybody meets: these
 * sentences are the product's failure voice at the moment a person has not yet
 * seen a single screen of it.
 *
 * Three different rules apply on this surface, and the interesting part is
 * that they disagree with each other. Which one is right depends entirely on
 * what the endpoint chose to put in its `detail`.
 *
 * ── 1. The OTP verify 401 is machine text wearing a sentence's clothes ──────
 *
 * `AuthService.verify_otp` raises `AuthError(f"OTP verification failed:
 * {result.value}")` (`lemely/auth/service.py:320`) and the router passes
 * `str(exc)` through as the 401 detail, so what actually reaches the browser is
 *
 *     OTP verification failed: wrong_code
 *     OTP verification failed: expired
 *     OTP verification failed: locked_out
 *     OTP verification failed: no_challenge
 *
 * and `ParentLogin.tsx` rendered `err.message` verbatim. Its module docstring
 * claimed the opposite in as many words — "the parent reads the actual reason
 * rather than a client-side guess at which it was" — which was true about the
 * *distinction* and false about the words: a parent read an enum member.
 *
 * The distinction is worth keeping, because the four cases genuinely call for
 * four different next actions (retype, resend, wait, start again). So these are
 * mapped rather than flattened, which preserves what the backend knows and
 * fixes what it says. `OtpResult` is the source list
 * (`lemely/auth/otp.py:32`); an unrecognised value falls back to a sentence
 * rather than to the raw string, so a new enum member added server-side cannot
 * leak through this function.
 *
 * ── 2. The OTP request 429 is genuinely well written, and is kept ───────────
 *
 * `OtpRateLimitError` says "OTP already sent; retry in 12s."
 * (`lemely/auth/otp.py:112`) — a real sentence with a real number in it, and
 * nothing written here could improve on it. This is the same call
 * `teacherOutcome.ts` made for its 422 and `friendOutcome.ts` for its send
 * path. The family's rule has never been "always keep the detail" or "never
 * keep it"; it is "keep it where a human wrote it for a human", and that has
 * to be decided per endpoint by reading the endpoint.
 *
 * ── 3. The password 401 is deliberately vague, and that is a security call ──
 *
 * A sign-in failure never says whether the email exists. Distinguishing "no
 * such account" from "wrong password" hands an account-enumeration oracle to
 * anyone with a form and a word list, and this product's users are children.
 * The cost is real and accepted: a parent who mistyped their email gets a
 * slightly less helpful message than they could have.
 */

/** No response at all, as opposed to a bad one. */
export const AUTH_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again."

/** A fault on our side. Worth saying so plainly: on a login screen, an
 * unexplained failure reads as "my account is gone". */
export const AUTH_SERVICE_FAILURE =
  "Something went wrong on our side, not with your account. Trying again is safe."

/** Deliberately does not say which half was wrong. See note 3 above. */
export const AUTH_BAD_CREDENTIALS =
  "That email and password don't match an account. Check both and try again."

/**
 * `OtpResult` (`lemely/auth/otp.py`) to a sentence, keeping the backend's
 * distinction and losing its vocabulary.
 *
 * `no_challenge` is the odd one: it means the server has no live code for this
 * number at all, which from the reader's side is indistinguishable from an
 * expired one, so it says the thing that is true either way and offers the
 * action that fixes both.
 */
const OTP_FAILURES: Record<string, string> = {
  wrong_code: "That code doesn't match. Check the message and type it again.",
  expired: "That code has expired. Ask for a new one and we'll text it straight away.",
  locked_out:
    "Too many tries with that code. Ask for a new one, and it will start counting again.",
  no_challenge:
    "We don't have a code waiting for that number. Ask for a new one and we'll text it straight away.",
}

/** The prefix `AuthService.verify_otp` puts in front of the enum value. */
const OTP_PREFIX = "OTP verification failed:"

/**
 * Turn a failed sign-in into a sentence.
 *
 * Used by the email/password form and by the device-limit confirmation, which
 * is the same request with one flag flipped.
 */
export function signInFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // `request()` wraps a fetch rejection as ApiError(0, …), so status 0 is
    // this codebase's spelling of "no response at all".
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status === 401) return AUTH_BAD_CREDENTIALS
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    return "We couldn't sign you in just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't sign you in just then. Trying again usually sorts it."
}

/**
 * Turn a failed OTP *verify* into a sentence, mapping the enum the backend
 * sends rather than printing it.
 */
export function otpVerifyFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (typeof err.detail === "string" && err.detail.startsWith(OTP_PREFIX)) {
      const reason = err.detail.slice(OTP_PREFIX.length).trim()
      // An unmapped value falls through to the generic sentence rather than
      // being shown: a member added to `OtpResult` later must not become copy.
      if (reason in OTP_FAILURES) return OTP_FAILURES[reason]
    }
    if (err.status === 401) return OTP_FAILURES.wrong_code
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't check that code just then. Ask for a new one and try again."
}

/**
 * Turn a failed OTP *request* into a sentence.
 *
 * The 429 keeps the server's own wording, which names the seconds remaining
 * and is better than anything written here. Everything else is ours.
 */
export function otpRequestFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status === 429 && typeof err.detail === "string" && err.detail.trim() !== "") {
      return err.detail.trim()
    }
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 400 || err.status === 422) {
      return "We couldn't send a code to that number. Check the digits and the country, then try again."
    }
    return "We couldn't send your code just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't send your code just then. Trying again usually sorts it."
}
