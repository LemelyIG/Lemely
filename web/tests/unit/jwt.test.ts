import { describe, expect, it } from "vitest"
import { isTokenExpired, tokenExpiresAt } from "@/lib/auth/jwt"

/*
 * Client-side reading of a token's `exp` (P6, the session-expiry fix).
 *
 * This helper decides whether the SPA bothers sending a token and whether a
 * stored session is worth keeping, so both directions of getting it wrong are
 * user-visible: too eager and it signs people out who were fine, too lax and it
 * renders a portal in which every request 401s. The bias is deliberate and
 * pinned below — when the token is unreadable, the server decides.
 */

function encode(payload: Record<string, unknown>): string {
  return `header.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.signature`
}

const NOW = Date.UTC(2026, 7, 12, 12, 0, 0)

describe("tokenExpiresAt", () => {
  it("reads exp as epoch milliseconds", () => {
    expect(tokenExpiresAt(encode({ exp: 1_800_000_000 }))).toBe(1_800_000_000_000)
  })

  it("decodes a payload padded oddly by base64url", () => {
    // base64url strips `=` padding; `atob` rejects an unpadded string, so a
    // payload whose length lands wrong must still decode. Varying the subject
    // length walks the encoded string through every remainder mod 4.
    for (let n = 1; n <= 8; n += 1) {
      const token = encode({ exp: 1_800_000_000, sub: "x".repeat(n) })
      expect(tokenExpiresAt(token)).toBe(1_800_000_000_000)
    }
  })

  it("survives a non-ASCII claim", () => {
    // Decoded via UTF-8 bytes rather than `atob` straight into JSON.parse, which
    // would mangle this into invalid JSON and lose the expiry with it.
    const token = encode({ exp: 1_800_000_000, email: "aurélie@example.com" })
    expect(tokenExpiresAt(token)).toBe(1_800_000_000_000)
  })

  it.each([
    ["not a jwt at all", "opaque-token"],
    ["a jwt with no payload segment", "header"],
    ["a payload that is not base64", "header.!!!!.sig"],
    ["a payload that is not JSON", `header.${Buffer.from("nope").toString("base64url")}.sig`],
    ["a token carrying no exp", encode({ sub: "abc" })],
    ["an exp that is not a number", encode({ exp: "soon" })],
  ])("returns null for %s", (_label, token) => {
    expect(tokenExpiresAt(token)).toBeNull()
  })
})

describe("isTokenExpired", () => {
  it("is false for a token with time left", () => {
    expect(isTokenExpired(encode({ exp: NOW / 1000 + 600 }), NOW)).toBe(false)
  })

  it("is true once exp has passed", () => {
    expect(isTokenExpired(encode({ exp: NOW / 1000 - 1 }), NOW)).toBe(true)
  })

  it("treats the final seconds before exp as already gone", () => {
    // A token that dies mid-flight is indistinguishable to the user from one
    // that was dead on arrival, so the skew window refreshes early instead.
    expect(isTokenExpired(encode({ exp: NOW / 1000 + 5 }), NOW)).toBe(true)
    expect(isTokenExpired(encode({ exp: NOW / 1000 + 120 }), NOW)).toBe(false)
  })

  it("keeps a token it cannot read, rather than discarding a live session", () => {
    // The signature is never checked here — only the server can actually
    // validate. Guessing "expired" for an unfamiliar shape would sign out a
    // user whose session was perfectly good.
    expect(isTokenExpired("opaque-token", NOW)).toBe(false)
    expect(isTokenExpired(encode({ sub: "abc" }), NOW)).toBe(false)
  })
})
