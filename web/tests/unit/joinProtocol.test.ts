import { describe, expect, it } from "vitest"
import { parseJoinCode } from "@/lib/joinProtocol"

/*
 * Packet A5 — `web+lemely://join/<code>` (`vite/manifest.ts`'s
 * `protocol_handlers`) resolves to `/join/%s`, and the `%s` placeholder is
 * filled with the *whole* invoked URL, not just the trailing code — so the
 * `/join/:code` route's `code` param can arrive as either a bare code or
 * that full URL string. `parseJoinCode` is the one place that tells the two
 * apart; see its own docstring.
 */

describe("parseJoinCode", () => {
  it("extracts the code from a web+lemely://join/<code> URL", () => {
    expect(parseJoinCode("web+lemely://join/ABC123")).toBe("ABC123")
  })

  it("passes a bare code through unchanged", () => {
    expect(parseJoinCode("ABC123")).toBe("ABC123")
  })

  it("decodes a percent-encoded code inside the URL form", () => {
    expect(parseJoinCode("web+lemely://join/AB%2B123")).toBe("AB+123")
  })

  it("passes an empty string through unchanged", () => {
    expect(parseJoinCode("")).toBe("")
  })
})
