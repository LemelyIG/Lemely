import { afterEach, describe, expect, it, vi } from "vitest"

import { randomUuid } from "@/lib/uuid"

/*
 * The bug this file pins: `crypto.randomUUID` is secure-context-only, so on a
 * plain-HTTP non-localhost origin it is `undefined`, and the bare call in
 * `getDeviceId` threw "crypto.randomUUID is not a function" on the login path —
 * the sign-in form rendered the TypeError as its error message and no one could
 * log in. Each tier below is therefore a real deployment, not a hypothetical.
 */

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("randomUuid", () => {
  it("uses crypto.randomUUID when the host provides it", () => {
    const randomUUID = vi.fn(() => "11111111-2222-4333-8444-555555555555")
    vi.stubGlobal("crypto", { randomUUID, getRandomValues: vi.fn() })

    expect(randomUuid()).toBe("11111111-2222-4333-8444-555555555555")
    expect(randomUUID).toHaveBeenCalledOnce()
  })

  /* The insecure-context shape: `getRandomValues` is present, `randomUUID` is not. */
  it("falls back to getRandomValues when randomUUID is missing", () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
      bytes.fill(0xff)
      return bytes
    })
    vi.stubGlobal("crypto", { getRandomValues })

    const id = randomUuid()
    expect(getRandomValues).toHaveBeenCalledOnce()
    expect(id).toMatch(UUID_V4)
    // All-ones input, so only the version/variant fields differ from `f`.
    expect(id).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff")
  })

  it("still returns a v4-shaped id with no Web Crypto at all", () => {
    vi.stubGlobal("crypto", undefined)

    expect(randomUuid()).toMatch(UUID_V4)
  })

  it("does not repeat itself", () => {
    const ids = new Set(Array.from({ length: 500 }, randomUuid))
    expect(ids.size).toBe(500)
  })
})
