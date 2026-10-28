import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { skipsFirstClassRedirect } from "@/lib/tutoring/teacherRedirect"
import { teacherFirstClassRedirect } from "@/portals/teacher"
import { stripComments } from "./support/jsxSource"

/*
 * F9-D1 · a tutor is a teacher with no class (SPEC decision log: a tutor is a
 * `tutor_profiles` row 1:1 with a teacher user). The D7.10 first-class gate
 * sent every teacher with zero classes to `/teacher/first-class`, so a real
 * tutor with no class saw "Create your first class" instead of the tutoring
 * screens (T-15 to T-21). The gate now stands aside on every path under
 * `/teacher/tutoring`, on a segment boundary, and nowhere else.
 */

const FIRST_CLASS = "/teacher/first-class"

// Every tutoring route the teacher router mounts (read from the router source below).
const TUTORING_PATHS = [
  "/teacher/tutoring",
  "/teacher/tutoring/",
  "/teacher/tutoring/profile",
  "/teacher/tutoring/availability",
  "/teacher/tutoring/sessions/b1",
  "/teacher/tutoring/preview",
  "/teacher/tutoring/students",
  "/teacher/tutoring/students/s1",
  "/teacher/tutoring/students/s1/",
]

describe("skipsFirstClassRedirect", () => {
  it("is true for /teacher/tutoring and everything under it, with or without a trailing slash", () => {
    for (const path of TUTORING_PATHS) expect(skipsFirstClassRedirect(path), path).toBe(true)
  })

  it("is false for a look-alike that only shares the prefix", () => {
    for (const path of [
      "/teacher/tutoringx",
      "/teacher/tutoring-extra",
      "/teacher/tutoringx/students",
      "/teacher/tutorin",
      "/teacher/xtutoring",
      "/teacher/classes/tutoring",
      "/tutoring",
      "/student/teacher/tutoring",
    ]) {
      expect(skipsFirstClassRedirect(path), path).toBe(false)
    }
  })

  it("is false for the other teacher routes, which keep the gate", () => {
    for (const path of [
      "/teacher",
      "/teacher/",
      "/teacher/classes",
      "/teacher/classes/c1",
      "/teacher/grading",
      "/teacher/review",
      "/teacher/students/s1",
      "/teacher/first-class",
      "",
    ]) {
      expect(skipsFirstClassRedirect(path), path).toBe(false)
    }
  })
})

describe("teacherFirstClassRedirect with the tutoring exemption", () => {
  it("does not send a zero-class teacher away from any tutoring screen", () => {
    for (const path of TUTORING_PATHS) {
      expect(teacherFirstClassRedirect("success", 0, path), path).toBeNull()
    }
  })

  it("still sends a zero-class teacher from every other route, look-alikes included", () => {
    for (const path of ["/teacher", "/teacher/classes", "/teacher/grading", "/teacher/tutoringx", "/teacher/tutoring-extra"]) {
      expect(teacherFirstClassRedirect("success", 0, path), path).toBe(FIRST_CLASS)
    }
  })
})

describe("TeacherLayout wiring", () => {
  const WEB = join(import.meta.dirname, "..", "..")
  const source = stripComments(readFileSync(join(WEB, "src/portals/teacher/index.tsx"), "utf8"))

  it("the gate function consults the helper before it can return the redirect", () => {
    const start = source.indexOf("export function teacherFirstClassRedirect(")
    expect(start, "teacherFirstClassRedirect not found").toBeGreaterThan(-1)
    const body = source.slice(start, source.indexOf("\n}", start))
    const consults = body.search(/skipsFirstClassRedirect\(\s*pathname\s*\)/)
    const returns = body.search(/return\s+"\/teacher\/first-class"/)
    expect(consults, "helper is not called").toBeGreaterThan(-1)
    expect(returns, "redirect return not found").toBeGreaterThan(-1)
    expect(consults).toBeLessThan(returns)
    expect(source).toMatch(/from\s+"@\/lib\/tutoring\/teacherRedirect"/)
  })

  it("the layout passes the live pathname to that gate", () => {
    expect(source).toMatch(/teacherFirstClassRedirect\(\s*classesQuery\.status,[^)]*location\.pathname\s*,?\s*\)/)
  })

  it("mounts the tutoring routes the helper exempts (non-vacuity)", () => {
    const mounted = [...source.matchAll(/path:\s*"(tutoring[^"]*)"/g)].map((m) => m[1])
    expect(mounted.length).toBeGreaterThanOrEqual(6)
    for (const route of mounted) {
      const concrete = `/teacher/${route.replace(/:\w+/g, "x1")}`
      expect(skipsFirstClassRedirect(concrete), concrete).toBe(true)
    }
  })
})
