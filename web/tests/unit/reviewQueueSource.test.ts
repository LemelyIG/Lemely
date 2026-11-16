import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")
const tsx = readdirSync(DIR).filter((f) => f.endsWith(".tsx"))

describe("review screens source", () => {
  it("uses design tokens, never raw colours", () => {
    for (const f of tsx) {
      const src = readFileSync(join(DIR, f), "utf8")
      expect(src, f).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
      expect(src, f).not.toMatch(/\boklch\(\s*0?\.\d/)
    }
  })
  it("gives every animation a reduced-motion fallback", () => {
    const css = readFileSync(join(DIR, "review.css"), "utf8")
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
    for (const name of ["lm-rq-bump", "lm-rq-skel"]) {
      expect(css).toContain(`@keyframes ${name}`)
    }
    expect(css).toMatch(/prefers-reduced-motion: reduce\)[\s\S]*animation: none/)
  })
  it("never shows Binny outside the calm states", () => {
    const col = readFileSync(join(DIR, "QueueColumn.tsx"), "utf8")
    expect(col).not.toMatch(/<Binny\b/)
  })
})
