import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  WaitlistError,
  classifyConfirmFailure,
  confirmWaitlist,
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

describe("confirmWaitlist (the email confirmation link)", () => {
  afterEach(() => vi.unstubAllGlobals())
  const reply = (status: number, body: unknown, headers: Record<string, string> = {}) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers })))

  it("POSTs the token as JSON to /api/waitlist/confirm and returns the status", async () => {
    reply(200, { status: "confirmed" })
    await expect(confirmWaitlist("tok-1")).resolves.toEqual({ status: "confirmed" })
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit]
    expect(url).toBe("/api/waitlist/confirm")
    expect(init.method).toBe("POST")
    expect(JSON.parse(String(init.body))).toEqual({ token: "tok-1" })
  })

  it("returns already_confirmed as it is", async () => {
    reply(200, { status: "already_confirmed" })
    await expect(confirmWaitlist("t")).resolves.toEqual({ status: "already_confirmed" })
  })

  it("reads the code out of an object detail", async () => {
    reply(400, { detail: { code: "expired_token" } })
    const error = await confirmWaitlist("t").catch((e: unknown) => e)
    expect(error).toBeInstanceOf(WaitlistError)
    expect((error as WaitlistError).status).toBe(400)
    expect((error as WaitlistError).code).toBe("expired_token")
  })

  it("still reads a string detail (turnstile_failed)", async () => {
    reply(403, { detail: "turnstile_failed" })
    const error = (await confirmWaitlist("t").catch((e: unknown) => e)) as WaitlistError
    expect(error.code).toBe("turnstile_failed")
  })

  it("classifies every failure the page tells apart", async () => {
    reply(400, { detail: { code: "invalid_token" } })
    expect(classifyConfirmFailure(await confirmWaitlist("t").catch((e: unknown) => e))).toBe("invalid")
    reply(400, { detail: { code: "expired_token" } })
    expect(classifyConfirmFailure(await confirmWaitlist("t").catch((e: unknown) => e))).toBe("expired")
    reply(429, { detail: "slow" }, { "Retry-After": "30" })
    const limited = (await confirmWaitlist("t").catch((e: unknown) => e)) as WaitlistError
    expect(classifyConfirmFailure(limited)).toBe("rate")
    expect(limited.retryAfter).toBe(30)
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))))
    expect(classifyConfirmFailure(await confirmWaitlist("t").catch((e: unknown) => e))).toBe("network")
    reply(500, {})
    expect(classifyConfirmFailure(await confirmWaitlist("t").catch((e: unknown) => e))).toBe("other")
  })

  it("treats a 400 with no known code as an invalid link", () => {
    expect(classifyConfirmFailure(new WaitlistError(400))).toBe("invalid")
  })
})
