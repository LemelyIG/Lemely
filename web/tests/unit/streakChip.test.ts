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

describe("Home top row", () => {
  // Lane L1: the streak chip became Home's streak pill. It must still be a
  // real link to the student's training log (Me), on every viewport.
  const source = sourceOf("src/portals/student/home/HomeTopRow.tsx")

  it("renders the streak pill as a Link to Me", () => {
    expect(source).toContain("<Link")
    expect(source).toContain("to={pill.to}")
  })

  it("never hides the pill at a breakpoint", () => {
    const pillAt = source.indexOf("to={pill.to}")
    expect(source.slice(pillAt, pillAt + 400)).not.toMatch(/\b(?:sm|md|lg|xl):hidden\b/)
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
