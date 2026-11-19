import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * C3a (Task 6) · the streak chip must show somewhere between the header
 * (>= sm) and Overview's greeting (< sm), never both, and the header's
 * breakpoint must be on the Tailwind scale (`sm:`) rather than an arbitrary
 * value (`min-[640px]:`) — DESIGN.md §14 rule 3.
 */

const ROOT = join(process.cwd())

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("Overview.tsx", () => {
  const source = sourceOf("src/portals/student/screens/Overview.tsx")

  it("renders XPStreak", () => {
    expect(source).toContain("<XPStreak")
  })

  it("hides its streak chip at sm and above (sm:hidden), the inverse of the header's", () => {
    const xpAt = source.indexOf("<XPStreak")
    expect(xpAt).toBeGreaterThan(-1)
    const nearby = source.slice(Math.max(0, xpAt - 400), xpAt)
    expect(nearby).toContain("sm:hidden")
  })
})

describe("student shell", () => {
  // Portal shell spec §1 "Removed": the header streak is gone; the streak lives
  // in the Overview page (its hero, in the Overview plan).
  it("no longer renders a streak chip in the shell", () => {
    expect(sourceOf("src/portals/student/index.tsx")).not.toContain("<XPStreak")
    expect(sourceOf("src/portals/student/shell.tsx")).not.toContain("<XPStreak")
  })
})
