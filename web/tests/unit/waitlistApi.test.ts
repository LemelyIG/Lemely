import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import {
  WAITLIST_PHONE_MESSAGE,
  normaliseWaitlistPhone,
  parseFieldErrors,
  validateWaitlistPhone,
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
