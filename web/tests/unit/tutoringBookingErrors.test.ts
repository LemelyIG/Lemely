import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { TUTORING_ERROR_CODES, TUTORING_ERROR_COPY, tutoringErrorOf } from "@/lib/tutoring/apiErrors"
import { CONTACT_DETAILS_MESSAGE } from "@/lib/tutoring/safetyNoticeCopy"
import {
  BOOKING_REFUSALS,
  TUTOR_UNAVAILABLE_MESSAGE,
  bookingRefusalFor,
  bookingRefusalOf,
  isTutorHidden,
} from "@/lib/tutoring/bookingErrors"

/*
 * T22: every refusal SP6 can send maps to the S-35 copy of the SPEC. The codes
 * are read out of SPEC §b.2's SP6 row and the sentences out of S-35, never
 * written out a second time here; T11's union (`TUTORING_ERROR_CODES`) is the
 * only code table, and `bookingErrors.ts` refines it, it does not copy it.
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

/** The SP6 row of §b.2, status cell: the codes it names after each status number. */
function sp6Codes(): string[] {
  const row = SPEC.split("\n").find((line) => line.startsWith("| SP6 |"))
  if (!row) throw new Error("SP6 row not found in SPEC §b.2")
  const cells = row.split(/(?<!\\)\|/).map((cell) => cell.trim())
  const status = cells[cells.length - 2] ?? ""
  const codes = new Set<string>()
  for (const tick of status.matchAll(/`([a-z]+(?:_[a-z]+)*)`/g)) codes.add(tick[1])
  return [...codes]
}

/** The S-35 "Interactions" paragraph. */
function s35Interactions(): string {
  const start = SPEC.indexOf("**S-35 ·")
  const from = SPEC.indexOf("**Interactions.**", start)
  const end = SPEC.indexOf("\n", from)
  return SPEC.slice(from, end)
}

/** `code`: "sentence" pairs in S-35, plus the bare `429: "sentence"`. */
function s35Copy(): Map<string, string> {
  const text = s35Interactions()
  const copy = new Map<string, string>()
  for (const m of text.matchAll(/`([a-z_]+)`: "([^"]+)"/g)) copy.set(m[1], m[2])
  const rate = /429: "([^"]+)"/.exec(text)
  if (rate) copy.set("too_many_requests", rate[1])
  return copy
}

const SP6 = sp6Codes()
const S35 = s35Copy()

const apiError = (status: number, code: string | null): ApiError =>
  new ApiError(status, `HTTP ${status}`, code === null ? undefined : { code, message: "server words" })

describe("the SP6 refusals", () => {
  it("reads a plausible set out of the SPEC row (non-vacuity)", () => {
    expect(SP6.length).toBeGreaterThanOrEqual(12)
    expect(SP6).toContain("slot_taken")
    expect(SP6).toContain("pending_limit")
    expect(SP6).toContain("too_many_requests")
    expect(S35.size).toBeGreaterThanOrEqual(5)
  })

  it("every code SP6 lists is in T11's union and has a handling of its own here", () => {
    for (const code of SP6) {
      expect(TUTORING_ERROR_CODES as readonly string[], `${code} is not in T11's union`).toContain(code)
      expect(Object.keys(BOOKING_REFUSALS), `${code} has no booking handling`).toContain(code)
    }
  })

  it("handles nothing T11 does not define (no second code table)", () => {
    for (const code of Object.keys(BOOKING_REFUSALS)) {
      expect(TUTORING_ERROR_CODES as readonly string[], `${code} is not in T11's union`).toContain(code)
    }
  })

  it("answers every code in T11's union with a sentence, so no failure is left without words", () => {
    expect(TUTORING_ERROR_CODES.length).toBeGreaterThan(50)
    for (const code of TUTORING_ERROR_CODES) {
      const refusal = bookingRefusalFor(code)
      expect(refusal.code).toBe(code)
      expect(refusal.message.length, code).toBeGreaterThan(0)
    }
  })

  it("uses S-35's sentence wherever the SPEC fixes one", () => {
    for (const [code, sentence] of S35) {
      if (code === "already_pending") continue
      expect(bookingRefusalFor(code as keyof typeof BOOKING_REFUSALS).message, code).toBe(sentence)
    }
    expect(bookingRefusalFor("slot_taken").message).toBe(S35.get("slot_taken"))
    expect(bookingRefusalFor("student_busy").message).toBe(S35.get("student_busy"))
    expect(bookingRefusalFor("pending_limit").message).toBe(S35.get("pending_limit"))
    expect(bookingRefusalFor("email_unverified").message).toBe(S35.get("email_unverified"))
    expect(bookingRefusalFor("too_many_requests").message).toBe(S35.get("too_many_requests"))
  })

  it("shows the contact-details sentence of SPEC §d, not the generic one", () => {
    const rules = SPEC.slice(SPEC.indexOf("**Rules for every screen below.**"))
    const sentence = /`contact_details_not_allowed` shows "([^"]+)"/.exec(rules)?.[1]
    expect(sentence).toBeDefined()
    expect(bookingRefusalFor("contact_details_not_allowed").message).toBe(sentence)
    expect(bookingRefusalFor("contact_details_not_allowed").message).toBe(CONTACT_DETAILS_MESSAGE)
    expect(bookingRefusalFor("contact_details_not_allowed").message).not.toBe(
      TUTORING_ERROR_COPY.contact_details_not_allowed,
    )
  })

  it("falls back to T11's own sentence for a code S-35 gives no wording", () => {
    for (const code of ["not_linked", "not_self", "not_bookable", "beyond_horizon", "note_not_allowed_for_parent"] as const) {
      expect(S35.has(code)).toBe(false)
      expect(bookingRefusalFor(code).message).toBe(TUTORING_ERROR_COPY[code])
    }
  })

  it("tells the screen what to do next, in a way the SPEC describes", () => {
    expect(bookingRefusalFor("slot_taken").action).toBe("refresh_slots")
    expect(bookingRefusalFor("student_busy").action).toBe("choose_another_time")
    expect(bookingRefusalFor("already_pending").action).toBe("open_requests")
    expect(bookingRefusalFor("email_unverified").action).toBe("verify_email")
    expect(bookingRefusalFor("safety_notice_required").action).toBe("show_safety_notice")
    expect(bookingRefusalFor("contact_details_not_allowed").field).toBe("note")
    expect(bookingRefusalFor("note_not_allowed_for_parent").field).toBe("note")
    // S-35 says the already-pending refusal links to the request; the link text is the screen's.
    expect(S35_PENDING_MENTIONS_LINK).toBe(true)
  })
})

const S35_PENDING_MENTIONS_LINK = /`already_pending`: link to the request/.test(s35Interactions())

describe("a tutor who is hidden from the student", () => {
  const spec = SPEC.slice(SPEC.indexOf("**S-34 ·"))
  const notListed = /Not listed: "([^"]+)"/.exec(spec)?.[1]

  it("reads S-34's own sentence", () => {
    expect(notListed).toBeDefined()
    expect(TUTOR_UNAVAILABLE_MESSAGE).toBe(notListed)
  })

  it("is one answer for an unlisted, paused, suspended, closed, unknown or blocked tutor, and never implies a block", () => {
    for (const code of ["not_found", "tutor_not_listed", "blocked"] as const) {
      const refusal = bookingRefusalFor(code)
      expect(refusal.message, code).toBe(TUTOR_UNAVAILABLE_MESSAGE)
      expect(refusal.action, code).toBe("tutor_unavailable")
    }
    expect(TUTOR_UNAVAILABLE_MESSAGE.toLowerCase()).not.toContain("block")
    expect(TUTOR_UNAVAILABLE_MESSAGE.toLowerCase()).not.toContain("suspend")
  })

  it("recognises the 404 whatever body it came with", () => {
    expect(isTutorHidden(apiError(404, "not_found"))).toBe(true)
    expect(isTutorHidden(apiError(404, null))).toBe(true)
    expect(isTutorHidden(apiError(404, "tutor_not_listed"))).toBe(true)
    expect(isTutorHidden(apiError(409, "slot_taken"))).toBe(false)
    expect(isTutorHidden(apiError(500, null))).toBe(false)
    expect(isTutorHidden(new Error("boom"))).toBe(false)
  })
})

describe("reading a failed call", () => {
  it("turns T11's typed error into a refusal with the status it came with", () => {
    const refusal = bookingRefusalOf(apiError(409, "slot_taken"))
    expect(refusal).not.toBeNull()
    expect(refusal?.code).toBe("slot_taken")
    expect(refusal?.status).toBe(409)
    expect(refusal?.message).toBe(S35.get("slot_taken"))
    expect(tutoringErrorOf(apiError(409, "slot_taken"))?.code).toBe(refusal?.code)
  })

  it("never shows the server's words", () => {
    expect(bookingRefusalOf(apiError(409, "pending_limit"))?.message).not.toContain("server words")
  })

  it("answers a 403 email_unverified from SP2 or SP6 with the verify action", () => {
    const refusal = bookingRefusalOf(apiError(403, "email_unverified"))
    expect(refusal?.action).toBe("verify_email")
  })

  it("is null for a failure that is not a tutoring refusal, so the screen shows its generic copy", () => {
    expect(bookingRefusalOf(new Error("network"))).toBeNull()
    expect(bookingRefusalOf(new ApiError(0, "fetch failed"))).toBeNull()
    expect(bookingRefusalOf(apiError(500, null))).toBeNull()
    expect(bookingRefusalOf(apiError(409, "a_code_nobody_defined"))).toBeNull()
  })

  it("carries Retry-After on a 429", () => {
    const limited = new ApiError(429, "slow down", { code: "too_many_requests" }, 3600)
    expect(bookingRefusalOf(limited)?.retryAfter).toBe(3600)
  })
})
