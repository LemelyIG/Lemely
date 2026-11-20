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

export const PHONE_REQUIRED_MESSAGE = "Enter a mobile number."
export const PHONE_INVALID_MESSAGE =
  "Enter a valid mobile number, for example 01012345678 or +201012345678."

/** The checkout sentence. Not an error in the field's voice: it explains why a payment stopped. */
export const PHONE_CHECKOUT_HEADING = "Add your mobile number to continue"
export const PHONE_CHECKOUT_BODY = "We need a mobile number on your account before you can pay. Nothing was charged."

export type PhoneErrorCode = "phone_required" | "phone_invalid"

/*
 * The rule this file keeps: the client never refuses a number the server would store. The server
 * hands the text to libphonenumber, which skips leading junk, ignores trailing punctuation, treats a
 * full-width plus as a plus and ignores invisible formatting characters, so every check below runs on
 * a cleaned copy and refuses only what the server refuses for certain (nothing, letters, a `;`, far too
 * few digits, over 40 characters). Everything about which numbers are real mobiles stays server-side.
 */

/** Invisible formatting characters (`\p{Cf}`: LRM/RLM, the embedding and isolate marks, zero-width
 * joiners). Contacts apps put these around a copied number, and nobody can see them to remove them. */
const INVISIBLE = /\p{Cf}/gu

/** Arabic-Indic (U+0660..) and Persian (U+06F0..) digits, as the server reads them. */
const EASTERN_DIGITS: Record<string, string> = Object.fromEntries(
  Array.from({ length: 10 }, (_, n) => [
    [String.fromCharCode(0x0660 + n), String(n)],
    [String.fromCharCode(0x06f0 + n), String(n)],
  ]).flat(),
)

/** The number as it should be sent and checked: invisible marks gone, a full-width plus made a
 * plus, trimmed. Nothing else is changed, so what the person typed is still what they see. */
export function cleanPhoneInput(raw: string): string {
  return raw.replace(INVISIBLE, "").replace(/\uff0b/g, "+").trim()
}

/** `cleanPhoneInput` with eastern digits as ASCII, for questions about what the number says. */
function asciiDigits(raw: string): string {
  return cleanPhoneInput(raw).replace(/[\u0660-\u0669\u06f0-\u06f9]/g, (d) => EASTERN_DIGITS[d] ?? d)
}

/** True while the typed value has no explicit country code, so the "+20" default applies. */
export function usesDefaultPrefix(raw: string): boolean {
  const value = asciiDigits(raw)
  if (value.startsWith("+") || value.startsWith("00")) return false
  // A bare "20" number ("201012345678") already carries the country code, 12 digits in all.
  const digits = value.replace(/\D/g, "")
  return !(digits.startsWith("20") && digits.length >= 12)
}

/**
 * Called when the field loses focus; the result is written back. It cleans the value, and with the
 * "+20" shown in front it drops a leading national zero ("01012345678" would read as "+20 0101..."),
 * in Arabic and Persian digits as well. The server reads both the same way. A "00" (international
 * dialling prefix) is left alone.
 */
export function tidyPhoneInput(raw: string): string {
  const value = cleanPhoneInput(raw)
  if (!usesDefaultPrefix(value)) return value
  const ascii = asciiDigits(value)
  if (ascii.startsWith("0") && !ascii.startsWith("00")) return value.slice(1).trimStart()
  return value
}

/** Fewest digits any real number has once its `00` or `+` is set aside (checked against every
 * region's example mobile in libphonenumber). */
const MIN_DIGITS = 7
/** The server refuses longer text outright; there is no digit limit of its own below that. */
const MAX_LENGTH = 40

/**
 * The error to show before sending, or `undefined`. Deliberately lenient: it rejects only what no
 * number can be and leaves every judgement about a real number, and about it being a mobile, to the
 * server.
 */
export function validatePhoneField(raw: string): string | undefined {
  const value = asciiDigits(raw)
  if (value.length === 0) return PHONE_REQUIRED_MESSAGE
  if (value.length > MAX_LENGTH || /[\p{L};]/u.test(value)) return PHONE_INVALID_MESSAGE
  // A leading 00 is the international dialling prefix, not part of the number.
  const digits = value.replace(/\D/g, "").replace(/^00/, "")
  if (digits.length < MIN_DIGITS) return PHONE_INVALID_MESSAGE
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
