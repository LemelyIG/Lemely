import { describe, expect, it } from "vitest"

import { navGroups, crumbs, resolveCrumb, resolveCrumbTrail } from "@/portals/student/data"
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
   * Onboarding is redirected into and `/student/landing` redirects out to the
   * public marketing page (P4.9), so removing either would break a real path.
   */
  it.each(["/student/onboard", "/student/landing"])(
    "keeps %s mounted as a deep-linkable route",
    (path) => {
      expect(studentRoutePaths).toContain(path)
    },
  )

  /*
   * `/student/directions` is the exception to the rule above, and the change
   * is deliberate rather than incidental — MISSION §9.7 requires a test that
   * changes with the IA to say so.
   *
   * D1.1 kept the route while removing its nav entry, which left an internal
   * design gallery of three result-header treatments reachable by any
   * signed-in student, rendering mock data. DECISION **D4.8** asked whether it
   * should ship and defaulted to option A on 2026-08-14 after its 30-minute
   * timeout: move it to `web/dev-previews/`, which is exactly what Phase 2 did
   * with the component kit for the identical reason.
   *
   * Asserted in both directions, like `marketing.test.ts`: it is not in the
   * nav (above) and it is no longer a route either. A gallery that is only
   * *invisible* is one forgotten guard away from being found.
   */
  it("no longer mounts /student/directions as a product route (D4.8)", () => {
    expect(studentRoutePaths).not.toContain("/student/directions")
  })

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

/*
 * P4.1 · the student header's breadcrumb became a real `<Breadcrumbs>` trail,
 * so the same facts the teacher's `resolveTrail` has been asserting since D1.5
 * now need asserting on the student side. Until this phase the student portal
 * rendered `resolveCrumb`'s flat string as inert text, which is why none of
 * this was checkable: an unlinked string cannot have a broken link in it.
 */
describe("resolveCrumbTrail — the student portal's back affordance", () => {
  it("renders a single crumb on the portal root, since the heading already says it", () => {
    expect(resolveCrumbTrail("/student")).toEqual([{ label: "Home" }])
  })

  it("never links the crumb for the page you are already on", () => {
    for (const item of navGroups.flatMap((group) => group.items)) {
      const trail = resolveCrumbTrail(item.to)
      expect(trail[trail.length - 1].to, `tail of the trail for ${item.to}`).toBeUndefined()
    }
  })

  /*
   * Only "Home" is linkable. The other leading labels this map produces are
   * grouping names with no route of their own — `/student/practice` and
   * `/student/flashcards` are not mounted paths, and `Marking` never was —
   * so linking them would manufacture the dead ends a back affordance exists
   * to remove.
   */
  it("links Home and nothing else", () => {
    const paths = [
      "/student",
      "/student/correct",
      "/student/board",
      "/student/subject/0625",
      "/student/practice/0625",
      "/student/flashcards/0625",
      "/student/plan/0625",
      "/student/plan/0625/session/abc-123",
      "/student/result/abc-123",
    ]
    for (const path of paths) {
      for (const crumb of resolveCrumbTrail(path)) {
        if (crumb.to !== undefined) {
          expect(crumb.to, `linked crumb "${crumb.label}" on ${path}`).toBe("/student")
          expect(crumb.label).toBe("Home")
        }
      }
    }
  })

  it("points every link it does emit at a route the router mounts", () => {
    const linked = [
      "/student",
      "/student/subject/0625",
      "/student/result/abc-123",
      "/student/plan/0625/session/abc-123",
    ].flatMap((path) => resolveCrumbTrail(path).flatMap((crumb) => (crumb.to ? [crumb.to] : [])))

    expect(linked.length).toBeGreaterThan(0)
    for (const to of linked) {
      expect(matchesSomeRoute(to, studentRoutePaths), `crumb link ${to}`).toBe(true)
    }
  })

  /*
   * The honesty rule the teacher trail already enforces, now enforced here
   * too. It was being broken: `/student/result/:paperId` rendered
   * "Home / Result <uuid>" on the product's flagship screen.
   */
  it("never leaks an opaque route id into a crumb label", () => {
    const cases: Array<[string, string]> = [
      ["/student/result/9f1c8b2e-0a44-4d33-8c21-77b0d5e6a1f2", "9f1c8b2e-0a44-4d33-8c21-77b0d5e6a1f2"],
      ["/student/plan/0625/session/abc-123", "abc-123"],
      ["/student/practice/set/abc-123", "abc-123"],
      ["/student/practice/result/abc-123", "abc-123"],
    ]
    for (const [path, id] of cases) {
      for (const crumb of resolveCrumbTrail(path)) {
        expect(crumb.label, `crumb on ${path}`).not.toContain(id)
      }
    }
  })

  /*
   * A syllabus code is deliberately NOT an opaque id: it is short, stable and
   * is what a student calls the subject. Pinned so a later "no parameters in
   * crumbs" sweep does not strip the one parameter that carries meaning.
   */
  it("keeps the syllabus code, which is a label rather than an id", () => {
    expect(resolveCrumbTrail("/student/subject/0625").map((c) => c.label)).toEqual([
      "Home",
      "0625",
    ])
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
