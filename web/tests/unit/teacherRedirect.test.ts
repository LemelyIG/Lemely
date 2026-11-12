import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { stripComments } from "./support/jsxSource"

/*
 * F9-D1 · a tutor is a teacher with no class (SPEC decision log: a tutor is a
 * `tutor_profiles` row 1:1 with a teacher user). The old D7.10 first-class gate
 * sent every teacher with zero classes to `/teacher/first-class`, so a tutor
 * with no class could not reach the tutoring screens (T-15 to T-21). The
 * teacher shell no longer has that gate at all (the home route shows the setup
 * screen instead, see `teacherFirstRun.test.ts`), so every tutoring route opens
 * for a zero-class teacher. These checks keep it that way.
 */
describe("TeacherLayout has no first-class gate", () => {
  const WEB = join(import.meta.dirname, "..", "..")
  const source = stripComments(readFileSync(join(WEB, "src/portals/teacher/index.tsx"), "utf8"))

  it("never redirects to /teacher/first-class", () => {
    expect(source).not.toMatch(/teacherFirstClassRedirect/)
    expect(source).not.toMatch(/<Navigate[^>]*first-class/)
    expect(source).not.toMatch(/navigate\(\s*["'`]\/teacher\/first-class/)
  })

  it("mounts the tutoring routes (non-vacuity)", () => {
    const mounted = [...source.matchAll(/path:\s*"(tutoring[^"]*)"/g)].map((m) => m[1])
    expect(mounted.length).toBeGreaterThanOrEqual(6)
    expect(mounted).toContain("tutoring")
  })

  it("lists Tutoring in the sidebar tools", () => {
    expect(source).toMatch(/SIDEBAR_TOOLS[^\n]*"tutoring"/)
  })
})
