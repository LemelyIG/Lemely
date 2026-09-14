import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * C4 (Task 11): `web/scripts/audit.mjs` gains print-media capture.
 *
 * Source-text only — this script drives a real headless browser
 * (Puppeteer) against a running preview server and seeded backend; nothing
 * about it is exercisable from this Node-environment unit runner (D3.20).
 *
 * Reality-check (recorded here because the plan's prose named the wrong
 * API): `audit.mjs` imports `puppeteer`, not `playwright`
 * (`import puppeteer from "puppeteer"`). Puppeteer's media-emulation call is
 * `page.emulateMediaType(type)`, not Playwright's `page.emulateMedia({
 * media })` — the shape `web/e2e/reduced-motion.spec.ts` uses is a
 * *Playwright* spec, a different tool from this script. This test pins the
 * call this file actually makes.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const src = readFileSync(join(ROOT, "scripts/audit.mjs"), "utf8")

describe("audit.mjs print-media capture", () => {
  it("emulates print media before a print-state capture", () => {
    expect(src).toMatch(/emulateMediaType/)
  })

  it("captures the student-result-print state", () => {
    expect(src).toMatch(/student-result-print/)
  })
})
