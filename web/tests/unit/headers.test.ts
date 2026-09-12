import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

/**
 * Packet A6 — the static-asset security headers (Cloudflare Pages/Workers
 * Static Assets reads `public/_headers` verbatim; see also nginx.conf and
 * worker/index.ts for the same five headers applied to the other two
 * deploy targets this product ships).
 */

const ROOT = fileURLToPath(new URL("../../", import.meta.url))
const headers = readFileSync(join(ROOT, "public/_headers"), "utf8")

describe("public/_headers", () => {
  it("applies to every path via the /* block", () => {
    expect(headers).toMatch(/^\/\*\s*$/m)
  })

  it("sets Strict-Transport-Security with a one-year max-age and includeSubDomains", () => {
    expect(headers).toContain("Strict-Transport-Security: max-age=31536000; includeSubDomains")
  })

  it("sets X-Content-Type-Options: nosniff", () => {
    expect(headers).toContain("X-Content-Type-Options: nosniff")
  })

  it("sets Referrer-Policy: strict-origin-when-cross-origin", () => {
    expect(headers).toContain("Referrer-Policy: strict-origin-when-cross-origin")
  })

  it("sets Permissions-Policy denying microphone/geolocation/interest-cohort, allowing camera on self", () => {
    expect(headers).toContain(
      "Permissions-Policy: camera=(self), microphone=(), geolocation=(), interest-cohort=()",
    )
  })

  describe("Content-Security-Policy", () => {
    const cspLine = headers.split("\n").find((line) => line.includes("Content-Security-Policy:"))

    it("is present", () => {
      expect(cspLine).toBeDefined()
    })

    it("defaults to self and never allows unsafe-inline in script-src", () => {
      expect(cspLine).toContain("default-src 'self'")
      expect(cspLine).toContain("script-src 'self'")
      expect(cspLine).not.toMatch(/script-src[^;]*unsafe-inline/)
    })

    it("blocks framing entirely and disables plugin content", () => {
      expect(cspLine).toContain("frame-ancestors 'none'")
      expect(cspLine).toContain("object-src 'none'")
    })

    it("locks down base-uri and form-action", () => {
      expect(cspLine).toContain("base-uri 'none'")
      expect(cspLine).toContain("form-action 'self'")
    })
  })
})
