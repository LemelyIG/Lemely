import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import {
  WAITLIST_LIMITS,
  WAITLIST_NAME_REQUIRED,
  WAITLIST_NAME_TOO_LONG,
  WAITLIST_PHONE_MESSAGE,
  normaliseWaitlistName,
  normaliseWaitlistPhone,
  parseFieldErrors,
  validateWaitlistName,
  validateWaitlistPhone,
  waitlistFirstName,
} from "../../src/lib/waitlist-api"

/*
 * The client's phone rules and the server's (`lemely.core.waitlist.normalise_phone`) are pinned
 * to ONE fixture, `tests/fixtures/waitlist_phone_cases.json`, which `tests/test_core_waitlist.py`
 * runs against the Python side.
 */
const cases: { raw: string; e164: string | null }[] = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "..", "..", "tests/fixtures/waitlist_phone_cases.json"), "utf8"),
).phone

describe("waitlist phone parity with the server", () => {
  it("has cases", () => expect(cases.length).toBeGreaterThan(10))

  it.each(cases.map((c) => [c.raw === "" ? "<blank>" : c.raw, c] as const))("%s", (_name, c) => {
    expect(normaliseWaitlistPhone(c.raw)).toBe(c.e164)
  })

  it("validate: blank is fine, bad shows the server's message", () => {
    expect(validateWaitlistPhone("")).toBeNull()
    expect(validateWaitlistPhone("   ")).toBeNull()
    expect(validateWaitlistPhone("01001234567")).toBeNull()
    expect(validateWaitlistPhone("12345")).toBe(WAITLIST_PHONE_MESSAGE)
  })
})

describe("parseFieldErrors", () => {
  it("maps a FastAPI 422 to camelCase field messages", () => {
    const body = {
      detail: [
        { loc: ["body", "phone"], msg: "Value error, Enter a mobile number.", type: "value_error" },
        { loc: ["body", "subjects", 0], msg: "Value error, Pick subjects from the list.", type: "x" },
        { loc: ["body", "phone"], msg: "second message ignored", type: "x" },
      ],
    }
    expect(parseFieldErrors(body)).toEqual({
      phone: "Enter a mobile number.",
      subjects: "Pick subjects from the list.",
    })
  })

  it("is empty for anything else", () => {
    expect(parseFieldErrors(null)).toEqual({})
    expect(parseFieldErrors({ detail: "turnstile_failed" })).toEqual({})
  })
})

describe("waitlist name rules (the server's: 1 to 100 characters after trimming, unicode allowed)", () => {
  it("is required: blank or whitespace is refused", () => {
    expect(validateWaitlistName("")).toBe(WAITLIST_NAME_REQUIRED)
    expect(validateWaitlistName("   \t ")).toBe(WAITLIST_NAME_REQUIRED)
  })

  it("accepts one character, the cap, and unicode names", () => {
    expect(validateWaitlistName("A")).toBeNull()
    expect(validateWaitlistName("x".repeat(WAITLIST_LIMITS.name))).toBeNull()
    expect(validateWaitlistName("مريم أحمد")).toBeNull()
    expect(validateWaitlistName("Zoë O'Brien-Smith")).toBeNull()
  })

  it("counts characters after trimming and collapsing, not raw length", () => {
    expect(validateWaitlistName("  " + "x".repeat(WAITLIST_LIMITS.name) + "  ")).toBeNull()
    expect(validateWaitlistName("x".repeat(WAITLIST_LIMITS.name + 1))).toBe(WAITLIST_NAME_TOO_LONG)
    expect(validateWaitlistName("😀".repeat(WAITLIST_LIMITS.name))).toBeNull()
  })

  it("normalises to trimmed text with inner whitespace collapsed", () => {
    expect(normaliseWaitlistName("  Sam   Student ")).toBe("Sam Student")
  })

  it("greets by the first word", () => {
    expect(waitlistFirstName("  Sam   Student ")).toBe("Sam")
    expect(waitlistFirstName("")).toBe("")
  })

  it("maps a server 422 on name to the name field", () => {
    expect(parseFieldErrors({ detail: [{ loc: ["body", "name"], msg: "String should have at least 1 character" }] }).name).toBeTruthy()
  })
})
