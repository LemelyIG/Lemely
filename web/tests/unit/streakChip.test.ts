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

describe("student/index.tsx", () => {
  const source = sourceOf("src/portals/student/index.tsx")

  it("HeaderStreak's visibility class is on the sm: scale, not an arbitrary min-[640px] value", () => {
    // Scoped to the streak chip's own className (DESIGN.md §14 rule 3), not
    // the whole file — a separate, unrelated `min-[640px]:px-page-desktop`
    // padding breakpoint on the app header belongs to a different task and
    // is out of scope here.
    const xpStreakAt = source.indexOf("<XPStreak")
    expect(xpStreakAt).toBeGreaterThan(-1)
    const nearby = source.slice(Math.max(0, xpStreakAt - 400), xpStreakAt)
    expect(nearby).toContain("sm:inline-flex")
    expect(nearby).not.toContain("min-[640px]")
  })
})
