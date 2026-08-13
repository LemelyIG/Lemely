import { describe, expect, it } from "vitest"

import { navGroups, crumbs, resolveCrumb } from "@/portals/student/data"
import { navItems, resolveTrail } from "@/portals/teacher/data"
import { studentRoute } from "@/portals/student"
import { teacherRoute } from "@/portals/teacher"

/*
 * P3.1 · the IA restructure (DECISION D1.1-5), pinned.
 *
 * These are navigation *facts*, and navigation facts are the ones that rot
 * silently. The student portal already learned this the expensive way twice:
 * `/student/plan` gained a `:subjectCode` segment and its breadcrumb fell
 * through to a bare "Home" for a whole phase, because a wrong-but-valid crumb
 * trips no typecheck, no axe rule and no threshold. The same is true of a nav
 * entry pointing at a route that no longer exists — React Router renders the
 * link happily and only a human clicking it finds out.
 *
 * So the cross-checks below are the point of this file: every nav destination
 * is asserted to be a route the router actually mounts, and every linked
 * breadcrumb likewise. A future phase that renames a route breaks a test here
 * rather than a link in production.
 */

/** Route paths the student portal actually mounts, as absolute pathnames. */
const studentRoutePaths = (studentRoute.children ?? []).map((child) =>
  child.index ? "/student" : `/student/${(child as { path: string }).path}`,
)

/** Same for the teacher portal, flattened one level for nested children. */
const teacherRoutePaths = (teacherRoute.children ?? []).flatMap((child) => {
  const base = child.index ? "/teacher" : `/teacher/${(child as { path: string }).path}`
  const nested = (child.children ?? []).map((grand) =>
    grand.index ? base : `/teacher/${(child as { path: string }).path}/${(grand as { path: string }).path}`,
  )
  return [base, ...nested]
})

/**
 * Does a concrete pathname match a route pattern with `:params` in it?
 * Small on purpose — this is a test helper, not a router.
 */
function matchesSomeRoute(pathname: string, patterns: string[]): boolean {
  return patterns.some((pattern) => {
    const regex = new RegExp(
      `^${pattern.replace(/:[^/]+/g, "[^/]+").replace(/\//g, "\\/")}$`,
    )
    return regex.test(pathname)
  })
}

describe("student nav — D1.1 and D1.3", () => {
  const allItems = navGroups.flatMap((group) => group.items)

  it("no longer offers the internal 'Elsewhere' group to students", () => {
    expect(navGroups.map((group) => group.label)).not.toContain("Elsewhere")
  })

  /*
   * The three surfaces that group contained are internal or orphaned, and none
   * of them belongs in a student's sidebar. Asserted by destination rather
   * than by group label so that re-adding one of them under a different
   * heading still fails.
   */
  it.each(["/student/onboard", "/student/landing", "/student/directions"])(
    "does not link %s from anywhere in the nav",
    (path) => {
      expect(allItems.map((item) => item.to)).not.toContain(path)
    },
  )

  /*
   * D1.1's explicit condition: the *routes* survive, only the nav entries go.
   * Onboarding is redirected into, and `scripts/audit.mjs` visits
   * `/student/directions` by path. Removing the routes would break both.
   */
  it.each(["/student/onboard", "/student/landing", "/student/directions"])(
    "keeps %s mounted as a deep-linkable route",
    (path) => {
      expect(studentRoutePaths).toContain(path)
    },
  )

  it("gives students an in-app path to their notifications (D1.3)", () => {
    expect(allItems.map((item) => item.to)).toContain("/student/notifications")
  })

  /*
   * The defect that made D1.3 worth testing rather than just doing: adding a
   * nav entry for a route with no entry in the `crumbs` map renders a
   * confident, wrong "Home" in the header, exactly as `/student/plan` once did.
   */
  it("resolves a real breadcrumb for every nav destination, never the bare default", () => {
    for (const item of allItems) {
      // `/student` is legitimately "Home"; everything else must differ from it.
      if (item.to === "/student") continue
      expect(resolveCrumb(item.to), `crumb for ${item.to}`).not.toBe("Home")
    }
  })

  it("points every nav entry at a route the router mounts", () => {
    for (const item of allItems) {
      expect(
        matchesSomeRoute(item.to, studentRoutePaths),
        `${item.to} is not a mounted student route`,
      ).toBe(true)
    }
  })

  it("has no crumb entry for a pathname no route can produce", () => {
    for (const path of Object.keys(crumbs)) {
      expect(
        matchesSomeRoute(path, studentRoutePaths),
        `crumbs has ${path}, which no route mounts`,
      ).toBe(true)
    }
  })
})

describe("teacher nav — D1.2", () => {
  it("gives the confidence-review queue a persistent nav entry", () => {
    expect(navItems.map((item) => item.to)).toContain("/teacher/review")
  })

  it("places Review directly after Grading, the order the work happens in", () => {
    const paths = navItems.map((item) => item.to)
    expect(paths.indexOf("/teacher/review")).toBe(paths.indexOf("/teacher/grading") + 1)
  })

  it("points every nav entry at a route the router mounts", () => {
    for (const item of navItems) {
      expect(
        matchesSomeRoute(item.to, teacherRoutePaths),
        `${item.to} is not a mounted teacher route`,
      ).toBe(true)
    }
  })
})

describe("resolveTrail — D1.5's back affordance", () => {
  it("renders no trail on the portal root (one crumb, and the heading says it)", () => {
    expect(resolveTrail("/teacher")).toHaveLength(1)
  })

  it("takes flat-section labels from navItems so trail and sidebar cannot disagree", () => {
    for (const item of navItems) {
      if (item.to === "/teacher") continue
      const trail = resolveTrail(item.to)
      expect(trail[trail.length - 1].label, `trail tail for ${item.to}`).toBe(item.label)
    }
  })

  it.each([
    ["/teacher/review/abc-123", ["Overview", "Review", "This item"]],
    ["/teacher/classes/c1", ["Overview", "Classes", "This class"]],
    ["/teacher/classes/c1/analytics", ["Overview", "Classes", "This class", "Analytics"]],
    ["/teacher/students/s9", ["Overview", "This student"]],
    ["/teacher/quizzes/q1", ["Overview", "AI quizzes", "This quiz"]],
    [
      "/teacher/quizzes/q1/assignments/a1/results",
      ["Overview", "AI quizzes", "This quiz", "Results"],
    ],
  ])("builds the trail for %s", (path, labels) => {
    expect(resolveTrail(path).map((crumb) => crumb.label)).toEqual(labels)
  })

  /*
   * The honesty rule from the function's own docstring, enforced rather than
   * merely documented: no crumb may interpolate an id. A UUID in a breadcrumb
   * is noise, and a name would make navigation chrome depend on a request.
   */
  it("never leaks a route id into a crumb label", () => {
    const ids = ["abc-123", "c1", "s9", "q1", "a1"]
    const paths = [
      "/teacher/review/abc-123",
      "/teacher/classes/c1",
      "/teacher/classes/c1/analytics",
      "/teacher/students/s9",
      "/teacher/quizzes/q1",
      "/teacher/quizzes/q1/assignments/a1/results",
    ]
    for (const path of paths) {
      for (const crumb of resolveTrail(path)) {
        for (const id of ids) {
          expect(crumb.label, `${path} leaked ${id}`).not.toContain(id)
        }
      }
    }
  })

  /*
   * The rule that makes the trail trustworthy: an intermediate crumb that
   * renders as inert text looks like a way back and is not. Every crumb except
   * the last must carry a destination, and that destination must be a real
   * mounted route.
   */
  it("gives every crumb but the last a destination that the router mounts", () => {
    const paths = [
      "/teacher/grading",
      "/teacher/review",
      "/teacher/review/abc-123",
      "/teacher/classes/c1",
      "/teacher/classes/c1/analytics",
      "/teacher/students/s9",
      "/teacher/quizzes/q1",
      "/teacher/quizzes/q1/assignments/a1/results",
      "/teacher/announcements",
    ]
    for (const path of paths) {
      const trail = resolveTrail(path)
      trail.slice(0, -1).forEach((crumb) => {
        expect(crumb.to, `${path}: intermediate crumb "${crumb.label}" is inert`).toBeDefined()
        expect(
          matchesSomeRoute(crumb.to!, teacherRoutePaths),
          `${path}: crumb points at ${crumb.to}, which no route mounts`,
        ).toBe(true)
      })
      expect(trail[trail.length - 1].to, `${path}: the current page is a link`).toBeUndefined()
    }
  })

  it("tolerates a trailing slash rather than falling through every arm", () => {
    expect(resolveTrail("/teacher/classes/c1/")).toEqual(resolveTrail("/teacher/classes/c1"))
  })

  /*
   * An unknown path is a route this function has not been taught. It must
   * degrade to a single root crumb, which the layout renders as no trail at
   * all — no claim about where you are beats a confident wrong one.
   */
  it("degrades to no trail on a path it does not recognise", () => {
    expect(resolveTrail("/teacher/some/future/screen")).toHaveLength(1)
  })
})
