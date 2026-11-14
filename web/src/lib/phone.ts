import { ApiError } from "@/lib/api"

/*
 * Phone numbers on the client (UD-11: every account has one, format-checked only).
 *
 * The server is the validator: it parses with libphonenumber, region EG, and stores E.164. Nothing
 * here tries to be that. This file does three smaller jobs: it decides when the "+20" default is
 * shown, it catches an empty or obviously-not-a-number field before a round trip, and it reads the
 * server's two stable codes (`phone_required`, `phone_invalid`) back into sentences. Match on the
 * code, never on the server's message: the message is written for client authors.
 *
 * Kept as plain functions (no React) for the reason every `*Outcome.ts` module here is: the web
 * runner is `environment: "node"`, so a rule inside a component can only be pinned by reading its
 * source.
 */

/** The country code a number with no `+` or `00` is read as. Matches the server's default region. */
export const DEFAULT_PHONE_PREFIX = "+20"

export const PHONE_REQUIRED_MESSAGE = "Enter a phone number."
export const PHONE_INVALID_MESSAGE =
  "Enter a valid phone number, for example 01012345678 or +201012345678."

/** The checkout sentence. Not an error in the field's voice: it explains why a payment stopped. */
export const PHONE_CHECKOUT_HEADING = "Add your phone number to continue"
export const PHONE_CHECKOUT_BODY = "We need a phone number on your account before you can pay. Nothing was charged."

export type PhoneErrorCode = "phone_required" | "phone_invalid"

/** True while the typed value has no explicit country code, so the "+20" default applies. */
export function usesDefaultPrefix(raw: string): boolean {
  const value = raw.trimStart()
  return !(value.startsWith("+") || value.startsWith("00"))
}

/**
 * Called when the field loses focus. With the "+20" shown in front, a leading national zero
 * ("01012345678") would read as "+20 0101...", so it is dropped from view. The server reads
 * both the same way. A "00" (international dialling prefix) is left alone.
 */
export function tidyPhoneInput(raw: string): string {
  const value = raw.trim()
  if (value.startsWith("0") && !value.startsWith("00")) return value.slice(1).trimStart()
  return value
}

/** Digits, spaces, dots, dashes and brackets, with one optional leading `+`. */
const SHAPE = /^\+?[\p{Nd}\s().-]+$/u
const MIN_DIGITS = 7
const MAX_DIGITS = 15

/**
 * The error to show before sending, or `undefined`. Deliberately lenient: it rejects only what no
 * number can be (empty, letters, too few or too many digits) and leaves every judgement about a
 * real country's rules to the server.
 */
export function validatePhoneField(raw: string): string | undefined {
  const value = raw.trim()
  if (value.length === 0) return PHONE_REQUIRED_MESSAGE
  if (!SHAPE.test(value)) return PHONE_INVALID_MESSAGE
  // `\d` is ASCII-only in JavaScript even with the `u` flag; the server also reads Arabic-Indic digits.
  const digits = (value.match(/\p{Nd}/gu) ?? []).length
  if (digits < MIN_DIGITS || digits > MAX_DIGITS) return PHONE_INVALID_MESSAGE
  return undefined
}

/**
 * The phone code on a 422, or `null`. FastAPI's own validation 422s carry `detail` as a list, so
 * the object check is what tells this refusal apart from those.
 */
export function phoneErrorCode(err: unknown): PhoneErrorCode | null {
  if (!(err instanceof ApiError) || err.status !== 422) return null
  const detail = err.detail
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) return null
  const code = (detail as { code?: unknown }).code
  return code === "phone_required" || code === "phone_invalid" ? code : null
}

/** The field sentence for a server code. */
export function phoneErrorMessage(code: PhoneErrorCode): string {
  return code === "phone_invalid" ? PHONE_INVALID_MESSAGE : PHONE_REQUIRED_MESSAGE
}

/**
 * True for checkout's own refusal: 422 `phone_required` from a payment route. The same code and
 * status as an empty field, so the caller's context (a checkout, not a form) is what makes this a
 * "you have no number on file" rather than "you left it blank".
 */
export function isCheckoutPhoneRequired(err: unknown): boolean {
  return phoneErrorCode(err) === "phone_required"
}
