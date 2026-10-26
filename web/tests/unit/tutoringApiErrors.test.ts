import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { ApiError, parseErrorBody } from "@/lib/api"
import {
  TUTORING_ERROR_CODES,
  TUTORING_ERROR_COPY,
  isAccessEnded,
  isTutoringError,
  tutoringErrorOf,
} from "@/lib/tutoring/apiErrors"

/*
 * T11: every refusal code SPEC §b.2 lists in a route's status column maps to a
 * typed error. The codes are read out of the SPEC's route tables as text (the
 * last cell of each of the 70 rows), never written out a second time here.
 *
 * A code counts when it is a backticked snake_case word, or a `"code":"x"`
 * body, inside a clause that starts with a status number (`409 …`, `422 …`).
 * Prose after the clause (R1's "Not behind `require_verified_email`") and
 * illustrations (`e.g.` groups, A11's `booking_cancelled`) are not codes.
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

/** Split on `;` and `. ` at bracket depth 0 and outside backticks. */
function clausesOf(text: string): string[] {
  const clauses: string[] = []
  let depth = 0
  let inTicks = false
  let current = ""
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (ch === "`") inTicks = !inTicks
    if (!inTicks) {
      if (ch === "(") depth++
      if (ch === ")") depth--
    }
    const boundary = !inTicks && depth === 0 && (ch === ";" || (ch === "." && /\s/.test(text[i + 1] ?? " ")))
    if (boundary) {
      clauses.push(current)
      current = ""
    } else {
      current += ch
    }
  }
  clauses.push(current)
  return clauses.map((c) => c.trim()).filter((c) => c.length > 0)
}

interface ParsedCodes {
  rows: number
  codes: Set<string>
}

function parseRefusalCodes(spec: string): ParsedCodes {
  const start = spec.indexOf("### b.2 Routes")
  const end = spec.indexOf("### b.3 DTOs")
  expect(start).toBeGreaterThan(-1)
  expect(end).toBeGreaterThan(start)
  const codes = new Set<string>()
  let rows = 0
  for (const line of spec.slice(start, end).split("\n")) {
    if (!line.startsWith("|")) continue
    const cells = line.split(/(?<!\\)\|/).map((cell) => cell.trim())
    if (!/^(?:P|SP|S|T|PA|R|B|A)\d+$/.test(cells[1] ?? "")) continue
    rows++
    const cell = cells[cells.length - 2] ?? ""
    const text = cell.replace(/incl\./g, "incl").replace(/\(e\.g\.[^()]*\)/g, "")
    for (const clause of clausesOf(text)) {
      if (!/^\d{3}\b/.test(clause)) continue
      // Only what follows the first 4xx is a refusal: A3's "200 (`pending_review`
      // → listed; `suspended` → listed as `reinstated`)" describes the success.
      const refusal = /\b4\d\d\b/.exec(clause)
      if (!refusal) continue
      for (const tick of clause.slice(refusal.index).matchAll(/`([^`]+)`/g)) {
        const token = tick[1]
        if (/^[a-z]+(?:_[a-z]+)*$/.test(token)) codes.add(token)
        const body = /"code":\s*"([a-z_]+)"/.exec(token)
        if (body) codes.add(body[1])
      }
    }
  }
  return { rows, codes }
}

const PARSED = parseRefusalCodes(SPEC)

/** Codes the backend sends that §b.2's status column does not spell out:
 * SPEC §0 "Errors" (`email_unverified`), the tutor-route preamble
 * (`no_tutor_profile`), `lemely/web/tutoring_http.py` / `deps_tutoring.py`
 * (`not_found`, `invalid_cursor`, `invalid_area`, `invalid_day`), the tutor
 * profile repository (`lemely/db/tutor_profile_repo.py`: `not_a_teacher`,
 * `invalid_profile`, `invalid_public_name`, `invalid_modes`, `invalid_subjects`,
 * `invalid_rules`) and the review repository (`lemely/db/tutor_review_repo.py`:
 * `not_pending`, `reply_empty`, `empty_update`) and the booking service
 * (`lemely/db/booking_repo.py`: `location_required`, `text_too_long`,
 * `note_empty`, `student_required`, `invalid_starts_at`, `invalid_window`,
 * `invalid_duration`), each sent as `detail.code` through `tutoring_error`
 * (`routers/tutor_profile.py`, `tutoring_reviews.py`, the booking routes). */
const NOT_IN_STATUS_COLUMN = [
  // Sent to a TUTOR on accept (draft or rejected profile; an active block). The
  // student routes return the directory's 404 instead, so SPEC §i.7 removed both
  // from the status column.
  "tutor_not_listed",
  "blocked",
  "email_unverified",
  "no_tutor_profile",
  "not_found",
  "invalid_cursor",
  "invalid_area",
  "invalid_day",
  "not_a_teacher",
  "invalid_profile",
  "invalid_public_name",
  "invalid_modes",
  "invalid_subjects",
  "invalid_rules",
  "not_pending",
  "reply_empty",
  "empty_update",
  "location_required",
  "text_too_long",
  "note_empty",
  "student_required",
  "invalid_starts_at",
  "invalid_window",
  "invalid_duration",
] as const

describe("SPEC §b.2 refusal codes (the spine)", () => {
  it("reads the status cell of all 70 route rows", () => {
    expect(PARSED.rows).toBe(70)
  })

  it("finds a plausible number of codes (at least 30)", () => {
    expect(PARSED.codes.size).toBeGreaterThanOrEqual(30)
  })

  it("does not take prose or illustrations for codes", () => {
    for (const notACode of ["require_verified_email", "booking_cancelled", "booking_completed", "awaiting_outcome", "no_show", "starts_at", "pending_review", "reinstated"]) {
      expect(PARSED.codes.has(notACode), notACode).toBe(false)
    }
  })

  it("reads the code out of a JSON body (T20) and out of a parenthesis (T11)", () => {
    expect(PARSED.codes.has("access_ended")).toBe(true)
    expect(PARSED.codes.has("meeting_link_not_allowed")).toBe(true)
  })
})

describe("every refusal code maps to a typed error", () => {
  it("knows every code in the status column", () => {
    const known = new Set<string>(TUTORING_ERROR_CODES)
    const unmapped = [...PARSED.codes].filter((code) => !known.has(code))
    expect(unmapped).toEqual([])
  })

  it("lists the codes outside the status column, and nothing else", () => {
    const extras = TUTORING_ERROR_CODES.filter((code) => !PARSED.codes.has(code)).sort()
    expect(extras).toEqual([...NOT_IN_STATUS_COLUMN].sort())
  })

  it("maps each code, from a 409 and from a 422, to the same typed error", () => {
    expect(TUTORING_ERROR_CODES.length).toBeGreaterThanOrEqual(PARSED.codes.size)
    for (const code of TUTORING_ERROR_CODES) {
      for (const status of [409, 422]) {
        const mapped = tutoringErrorOf(new ApiError(status, "plain", { code, message: "server words" }))
        expect(mapped, `${status} ${code}`).not.toBeNull()
        expect(mapped?.code).toBe(code)
        expect(mapped?.status).toBe(status)
        expect(mapped?.message).toBe(TUTORING_ERROR_COPY[code])
      }
    }
  })

  it("has one sentence of copy per code and none to spare", () => {
    expect(Object.keys(TUTORING_ERROR_COPY).sort()).toEqual([...TUTORING_ERROR_CODES].sort())
    for (const code of TUTORING_ERROR_CODES) {
      const copy = TUTORING_ERROR_COPY[code]
      expect(copy.length, code).toBeGreaterThan(10)
      expect(copy, code).toMatch(/[.]$/)
    }
  })

  it("keeps the copy inside the copy rules", () => {
    for (const code of TUTORING_ERROR_CODES) {
      const copy = TUTORING_ERROR_COPY[code]
      expect(copy, code).not.toMatch(/[—!]/)
      expect(copy, code).not.toMatch(/\b(?:improvements?|verified)\b/i)
      expect(copy, code).not.toMatch(/\$|£|\bEGP\b|\bfee\b/i)
    }
  })

  it("reads a code that went through the real error-body parser", () => {
    const text = JSON.stringify({ detail: { code: "slot_taken", message: "That time was just taken." } })
    const { message, detail, body } = parseErrorBody(409, "Conflict", text)
    const mapped = tutoringErrorOf(new ApiError(409, message, detail, undefined, body))
    expect(mapped?.code).toBe("slot_taken")
  })

  it("reads email_unverified, whose detail carries no message", () => {
    const text = JSON.stringify({ detail: { code: "email_unverified" } })
    const { message, detail, body } = parseErrorBody(403, "Forbidden", text)
    expect(tutoringErrorOf(new ApiError(403, message, detail, undefined, body))?.code).toBe("email_unverified")
  })

  it("carries Retry-After on a 429", () => {
    const mapped = tutoringErrorOf(new ApiError(429, "slow down", { code: "too_many_requests" }, 30))
    expect(mapped?.code).toBe("too_many_requests")
    expect(mapped?.retryAfter).toBe(30)
  })
})

describe("what is not a typed tutoring error", () => {
  it("is null for a code the contract does not list", () => {
    expect(tutoringErrorOf(new ApiError(409, "x", { code: "invented_code" }))).toBeNull()
  })

  it("is null for a FastAPI validation list", () => {
    const detail = [{ loc: ["body", "stars"], msg: "must be at most 5", type: "less_than_equal" }]
    expect(tutoringErrorOf(new ApiError(422, "422 Unprocessable Entity", detail))).toBeNull()
  })

  it("is null for a plain string detail, a missing detail and a non-ApiError", () => {
    expect(tutoringErrorOf(new ApiError(409, "slot_taken", "slot_taken"))).toBeNull()
    expect(tutoringErrorOf(new ApiError(409, "409 Conflict"))).toBeNull()
    expect(tutoringErrorOf(new Error("slot_taken"))).toBeNull()
    expect(tutoringErrorOf(null)).toBeNull()
  })

  it("is null for a server error that happens to carry a code", () => {
    expect(tutoringErrorOf(new ApiError(500, "x", { code: "slot_taken" }))).toBeNull()
  })

  it("is null when the code is not a string", () => {
    expect(tutoringErrorOf(new ApiError(409, "x", { code: 7 }))).toBeNull()
  })
})

describe("isTutoringError and isAccessEnded", () => {
  it("matches one code", () => {
    const error = new ApiError(409, "x", { code: "pending_limit" })
    expect(isTutoringError(error, "pending_limit")).toBe(true)
    expect(isTutoringError(error, "slot_taken")).toBe(false)
    expect(isTutoringError(new Error("x"), "pending_limit")).toBe(false)
  })

  it("is true only for a 403 access_ended (T20), not for the 409 a blocked accept gets (T11)", () => {
    expect(isAccessEnded(new ApiError(403, "x", { code: "access_ended" }))).toBe(true)
    expect(isAccessEnded(new ApiError(409, "x", { code: "access_ended" }))).toBe(false)
    expect(isAccessEnded(new ApiError(403, "x", { code: "email_unverified" }))).toBe(false)
    expect(isAccessEnded(new ApiError(404, "x", { code: "not_found" }))).toBe(false)
    expect(isAccessEnded(undefined)).toBe(false)
  })
})
