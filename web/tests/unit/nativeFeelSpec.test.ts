import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Packet B7 (Task 12) · source-text pins for the native-feel e2e spec and its
 * Playwright device projects. The spec itself is the test (it drives a real
 * browser against a real build) — this file only pins the wiring vitest can
 * see without a browser: the spec names the five signed-out routes the plan
 * requires, both device projects exist in playwright.config.ts, and the spec
 * asserts on `requestfailed` (Assertion 9's zero-network-failure proof).
 */

const ROOT = join(process.cwd())

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("native-feel.spec.ts names the required routes", () => {
  const source = sourceOf("e2e/native-feel.spec.ts")

  it.each(["/login", "/signup", "/reset", "/join", "/settings/notifications"])(
    "names %s",
    (route) => {
      expect(source).toContain(route)
    },
  )

  it("uses failedRequests, whose helper watches requestfailed events", () => {
    expect(source).toContain("failedRequests(page)")
    expect(sourceOf("e2e/native-feel.helpers.ts")).toContain("requestfailed")
  })
})

describe("playwright.config.ts declares both native-feel device projects", () => {
  const source = sourceOf("playwright.config.ts")

  it("declares the iphone-15 project", () => {
    expect(source).toContain(`name: "iphone-15"`)
  })

  it("declares the pixel-7 project", () => {
    expect(source).toContain(`name: "pixel-7"`)
  })

  it("scopes native-feel.spec.ts to the device projects only", () => {
    expect(source).toContain(String.raw`testMatch: /native-feel\.spec\.ts/`)
    expect(source).toContain(String.raw`testIgnore: /native-feel\.spec\.ts/`)
  })
})
