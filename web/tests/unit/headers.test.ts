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

    /*
     * Cloudflare auto-injects its Web Analytics beacon into every response it
     * proxies, so the host has to be allowed for the beacon to run at all.
     * The host form is deliberate: the injected URL carries a version suffix
     * (`/beacon.min.js/v31edd6df...`), and CSP path matching demands an exact
     * match for a source that does not end in `/`, so the path form
     * Cloudflare's own docs suggest would not match what actually ships.
     * What must never come back is a nonce, a hash, or `unsafe-inline` —
     * asserted above and again here, because a host allowlist and an inline
     * escape hatch are not the same concession.
     */
    it("allows only the Cloudflare beacon host in script-src, never an inline escape hatch", () => {
      expect(cspLine).toContain("script-src 'self' https://static.cloudflareinsights.com;")
      expect(cspLine).not.toMatch(/script-src[^;]*nonce-/)
      expect(cspLine).not.toMatch(/script-src[^;]*sha(256|384|512)-/)
      expect(cspLine).not.toMatch(/script-src[^;]*\*/)
    })

    /*
     * Avatars are V4 signed GCS URLs (`_avatar_url_for` in
     * `lemely/web/routers/me.py`) rendered by `<Avatar src=...>`, so the
     * image load is cross-origin. Without this host the browser blocked
     * every avatar and the initials fallback rendered instead — the exact
     * regression this pins. `data:`/`blob:` stay for the local preview
     * `ProfileSettings` shows while an upload is in flight.
     */
    it("allows the signed-URL avatar host in img-src, and nothing broader", () => {
      expect(cspLine).toContain("img-src 'self' data: blob: https://storage.googleapis.com;")
      expect(cspLine).not.toMatch(/img-src[^;]*\*/)
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
