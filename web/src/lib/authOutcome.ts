import { ApiError } from "@/lib/api"
import { isEmailUnverifiedError } from "@/lib/authTypes"

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
 *
 * ── D7's six routes, added by Task 13 (spec §4.6) ────────────────────────────
 *
 * `signUpFailureMessage`, `verificationFailureMessage`, `resetFailureMessage`
 * and `inviteFailureMessage` cover `/signup`, `/verify-email` (confirm and
 * resend), `/reset` (request and confirm) and G-08's invite preview/redeem.
 * Each function owns every route its screen calls rather than one function
 * per route — `verificationFailureMessage` and `resetFailureMessage` each
 * speak for two endpoints, the same way `otpRequestFailureMessage` and
 * `otpVerifyFailureMessage` above split by screen, not by request.
 *
 * ── 4. The new cooldown 429 is NOT the OTP 429, on purpose ──────────────────
 *
 * Note 2 kept the OTP-request 429 verbatim because `OtpRateLimitError` is a
 * sentence a human wrote. D7.12 reuses the OTP cooldown's *mechanism*
 * (`CooldownStore`, shared by signup, `verify-email/resend` and
 * `password-reset/request`) but not its manners:
 * `CooldownError.__str__` (`lemely/auth/cooldown.py`) is
 *
 *     Cooldown active for 'someone@example.com'; retry in 30s.
 *
 * — a `repr()`'d key (an email address for two of these routes, a raw user id
 * for the third, from `resend_verification`'s `cooldown.check_and_stamp(auth.
 * user_id)`) inside what reads as a log line, not copy. Keeping it would put a
 * reader's own address back on screen in Python quote marks, which is both
 * ugly and exactly the kind of machine text note 1 exists to keep off a
 * screen — so unlike note 2's 429, this one is *not* kept. `AUTH_COOLDOWN_
 * ACTIVE` is written once and reused by all three callers: the cause and the
 * fix (wait a moment) are identical regardless of which key was throttled.
 *
 * ── 5. A verify/reset token's 400 does not say which of four reasons ────────
 *
 * `AuthService.verify_email` and `.reset_password` both redeem a token via
 * `AuthTokenService.redeem`, which raises one of `TokenNotFound`,
 * `TokenAlreadyUsed` or `TokenExpired` (`lemely/db/auth_token_repo.py`) —
 * each collapsed into the same `AuthError` and the same **400** by the
 * router's own docstring, deliberately: "never a 404 or 410 that would hint
 * at *which* of those four it was." A reader cannot act differently on
 * "unknown" versus "already used" versus "expired" anyway — all four are
 * fixed the same way, by asking for a new link — so `AUTH_LINK_EXPIRED` says
 * the thing that is true of all four rather than guessing which applies, the
 * same move `OTP_FAILURES.no_challenge` above makes for its own
 * indistinguishable pair.
 *
 * `reset_password` has a fifth, unrelated 400 source: GoTrue itself rejecting
 * the new password via `admin_update_user_password`
 * (`GoTrue admin-update-password failed (422): ...`, `lemely/auth/gotrue.py`).
 * This function cannot tell that apart from a token failure by status code
 * alone, and does not try to — both collapse to `AuthError` and 400 with no
 * shared, stable shape to key on, only two differently-wrapped strings. A
 * token failure is overwhelmingly the common real-world 400 here; GoTrue
 * rejecting a password the client already validated is the rare edge. "Ask
 * for a new link" leaves a reader in that rare case no worse off — they
 * re-enter the flow and retry with a different password — rather than
 * chasing a second prefix match as fragile as the first, for a sentence about
 * their password that would not even be wrong, only mistimed.
 *
 * ── 6. `email_unverified` is a field, never a sentence ───────────────────────
 *
 * D7.5's soft gate (`deps.require_verified_email`) 403s with
 * `detail={"code": "email_unverified"}` — deliberately structured, per that
 * function's own docstring, "a stable, machine-readable marker (never prose)
 * the frontend's `lib/authOutcome.ts`-family outcome modules match on."
 * `isEmailUnverifiedError` (`authTypes.ts`) narrows `ApiError.detail` onto it
 * the same way `isDeviceLimitChallenge` (`deviceTypes.ts`) narrows the
 * device-limit 409 — a field check, not a string search.
 * `verificationFailureMessage` checks it first, ahead of the generic 403/400
 * handling, because it is a status neither of *this* function's own two
 * routes ever themselves produces (neither `/verify-email` nor its resend can
 * 403) — it only ever arrives here because some other screen's failed
 * request (today, only `POST /student/correct`) was handed to this function
 * too, wanting the one sentence this module already owns for "you are not
 * verified yet."
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
 * A signup the server refused (400). Mirrors `signInFailureMessage`'s
 * deliberate vagueness (note 3) for the reason spec §4.3 states explicitly:
 * "the signup conflict for an already-registered address is worded to offer
 * a route to sign in without confirming the address is held." This function
 * cannot tell that case apart from GoTrue rejecting the address or password
 * for some other reason (see the D7 header above), so one sentence has to be
 * honest for both — it neither confirms nor denies an existing account, and
 * gives the reader a move either way.
 */
export const AUTH_SIGNUP_REJECTED =
  "We couldn't create an account with those details. If you already have one, sign in instead. Otherwise, check what you entered and try again."

/**
 * D7.12's shared cooldown, reused verbatim by `signUpFailureMessage`,
 * `verificationFailureMessage` and `resetFailureMessage`. See note 4 above
 * for why `CooldownError`'s own wording is not kept the way note 2's 429 is.
 */
export const AUTH_COOLDOWN_ACTIVE = "You've just tried that. Wait a few seconds and try again."

/**
 * A verification or password-reset link the server would not redeem —
 * unknown, wrong-purpose, already used, or actually expired (and, on the
 * reset side, one further cause with no sentence of its own — see note 5
 * above). True of all of them, and the fix is the same for all of them.
 */
export const AUTH_LINK_EXPIRED =
  "That link has expired or already been used. Ask for a new one and we'll send it straight away."

/**
 * G-07's typed-code failure, the code-shaped counterpart to
 * `AUTH_LINK_EXPIRED`.
 *
 * `POST /auth/verify-email/code` collapses wrong, expired and locked-out into
 * one non-revealing 400 (deliberately — see the route's own docstring), so
 * this names all three rather than guessing which applied, exactly as
 * `AUTH_LINK_EXPIRED` does for its four causes. It exists at all because
 * reusing `AUTH_LINK_EXPIRED` here told someone who had typed six digits that
 * their *link* had expired, when they may never have opened one.
 */
export const AUTH_CODE_REJECTED =
  "That code didn't work — it may be wrong, expired, or already used. Ask for a new email and we'll send one straight away."

/**
 * D7.5's soft gate, reached from outside this module's own two routes — see
 * note 6 above. Written to make sense wherever `require_verified_email`
 * eventually guards something, not only today's one route.
 */
export const AUTH_EMAIL_UNVERIFIED =
  "Verify your email before you can do that. Check your inbox for the link, or ask for a new one."

/** `GET /api/invites/{code}` or `POST /api/invites/{code}/redeem` naming no
 * live invite or class join code. */
export const AUTH_INVITE_NOT_FOUND = "We couldn't find an invite for that code. Check it and try again."

/** `POST /api/invites/{code}/redeem` on a code someone else already redeemed. */
export const AUTH_INVITE_ALREADY_USED =
  "That invite has already been used. Ask whoever sent it for a fresh one."

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

/**
 * Turn a failed `POST /auth/signup` into a sentence. See `AUTH_SIGNUP_
 * REJECTED`'s own comment for the 400 case, and note 4 above for the 429.
 */
export function signUpFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status === 429) return AUTH_COOLDOWN_ACTIVE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 400) return AUTH_SIGNUP_REJECTED
    return "We couldn't create your account just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't create your account just then. Trying again usually sorts it."
}

/**
 * Turn a failed email-verification action into a sentence — G-07's own
 * `/auth/verify-email` (confirm) and `/auth/verify-email/resend`, plus any
 * other screen's 403 against D7.5's gate (note 6 above). G-07's third route,
 * `/auth/verify-email/code`, has its own `verificationCodeFailureMessage`
 * below, because its 400 means something this one's 400 copy denies. Checked in that
 * order: the marker first, because it is the one status this function's own
 * two routes never themselves produce.
 */
export function verificationFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status === 403 && isEmailUnverifiedError(err.detail)) return AUTH_EMAIL_UNVERIFIED
    if (err.status === 429) return AUTH_COOLDOWN_ACTIVE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 400) return AUTH_LINK_EXPIRED
    return "We couldn't verify your email just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't verify your email just then. Trying again usually sorts it."
}

/**
 * Turn a failed `POST /auth/verify-email/code` into a sentence.
 *
 * Separate from `verificationFailureMessage` for one reason: the 400. That
 * function's 400 is `AUTH_LINK_EXPIRED`, which is right for the two routes it
 * serves and wrong here — the person typed a code and may never have opened a
 * link, so being told the link expired is simply untrue. Every other status
 * maps identically, and deliberately so: this is the same screen.
 */
export function verificationCodeFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status === 403 && isEmailUnverifiedError(err.detail)) return AUTH_EMAIL_UNVERIFIED
    if (err.status === 429) return AUTH_COOLDOWN_ACTIVE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 400) return AUTH_CODE_REJECTED
    return "We couldn't check that code just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't check that code just then. Trying again usually sorts it."
}

/**
 * Turn a failed password-reset action into a sentence — G-06's
 * `/auth/password-reset/request` and `/auth/password-reset/confirm` alike.
 * See note 5 above for why the 400 does not try to tell the two very
 * different causes `reset_password` can raise apart.
 */
export function resetFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status === 429) return AUTH_COOLDOWN_ACTIVE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 400) return AUTH_LINK_EXPIRED
    return "We couldn't reset your password just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't reset your password just then. Trying again usually sorts it."
}

/**
 * Turn a failed G-08 invite preview or redeem into a sentence. No
 * enumeration concern here the way signup and sign-in have one: an invite
 * code is not an account credential, and a 404/409 reveals nothing about any
 * person, only about the code itself.
 */
export function inviteFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return AUTH_NETWORK_FAILURE
    if (err.status >= 500) return AUTH_SERVICE_FAILURE
    if (err.status === 404) return AUTH_INVITE_NOT_FOUND
    if (err.status === 409) return AUTH_INVITE_ALREADY_USED
    return "We couldn't use that invite just then. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return AUTH_NETWORK_FAILURE
  return "We couldn't use that invite just then. Trying again usually sorts it."
}
