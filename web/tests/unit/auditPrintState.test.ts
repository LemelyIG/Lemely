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

  /*
   * C4/C5 review fix: print and dark-mode emulation are independent
   * Puppeteer calls (`emulateMediaType` / `emulateMediaFeatures`), so a
   * print-only capture can pass while a combined print+dark state would
   * have shown the `@media print` cascade bug (a bare `:root` losing to
   * the dark ladder's `:root[data-theme="dark"]`, since `@media` adds no
   * specificity). This state is the only capture that would have caught it.
   */
  it("captures a combined print+dark state, applying both emulations together", () => {
    expect(src).toContain("student-result-print-dark")

    const captureStart = src.indexOf("student-result-print-dark")
    expect(captureStart).toBeGreaterThan(-1)
    // Look at the surrounding capture block (media type is set just above
    // the slug's first use) rather than the whole file, so this actually
    // proves the two emulations are applied in the SAME pass rather than
    // merely both appearing somewhere in the script.
    const windowStart = Math.max(0, captureStart - 800)
    const captureBlock = src.slice(windowStart, captureStart + 200)
    expect(captureBlock).toMatch(/emulateMediaType\("print"\)/)
    expect(captureBlock).toMatch(/emulateMediaFeatures\(\[\{ name: "prefers-color-scheme", value: "dark" \}\]\)/)
  })
})
