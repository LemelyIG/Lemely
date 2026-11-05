import { describe, expect, it } from "vitest"
import { readTokenBlock, tokenHex } from "../../vite/brandTokens.ts"

describe("alpha in a colour token", () => {
  it("readTokenBlock parses opaque oklch() and hex tokens and leaves an alpha token out", () => {
    const css = ":root {\n  --a: oklch(0.5 0.1 200);\n  --b: #042f4f;\n  --scrim: oklch(0.2 0.03 242 / 0.4);\n}\n"
    const tokens = readTokenBlock(css, ":root")
    expect(tokens.get("a")).toEqual([0.5, 0.1, 200])
    expect(tokens.get("b")).toBeDefined()
    expect(tokens.has("scrim")).toBe(false)
  })

  it("tokenHex throws on a token with an alpha rather than returning it opaque", () => {
    // `--md-scrim` is `oklch(... / 0.4)` in the real index.css.
    expect(() => tokenHex("md-scrim")).toThrow(/--md-scrim.*alpha/)
  })

  it("tokenHex still resolves its opaque neighbours", () => {
    expect(tokenHex("md-primary")).toMatch(/^#[0-9a-f]{6}$/)
  })
})
