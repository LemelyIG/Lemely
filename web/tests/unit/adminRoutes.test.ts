import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes } from "@/routes"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { platformAdminRoute, schoolAdminRoute } from "@/portals/admin"

/*
 * P4.7 · the two admin lanes, and the role split that made them necessary.
 *
 * This file exists for one class of fact, and it is the class `marketing.test.ts`
 * was written for: **which role can reach which subtree**. A guard around the
 * wrong subtree passes typecheck, passes lint, passes the design hook, and
 * renders perfectly for whoever it happens to admit. Nothing else in this suite
 * can see it.
 *
 * The specific thing being pinned here is a role *removal*, which is rarer and
 * more fragile than an addition. `platform_admin` was in `TEACHER_ROLES` for the
 * whole build. It looked harmless: the API admits the role on every
 * `/api/teacher/*` route, so the guard was not wrong about permissions. It was
 * wrong about data. Every service behind those routes returns **empty** for a
 * platform admin on purpose ("no super-role bypass", D1.6/D1.10, stated in
 * `class_repo.py`, `review.py`, `teacher.py` and `at_risk_repo.py`), so the
 * console they landed in could only ever have been blank — and a permanently
 * blank console is indistinguishable on screen from a broken one.
 *
 * Putting them back would therefore not fail anything. It would just quietly
 * restore a dead end. Hence the assertion below that names the role and the
 * list, in both directions.
 */

/** Walk a route element tree looking for a component by display name.
 *
 * Same helper as `marketing.test.ts` and `notFoundFallback.test.ts`, and for
 * the same reason: guards are React elements, so this is the only honest way to
 * ask what gates a route without rendering it. */
function containsComponent(node: unknown, name: string): boolean {
  if (!node || typeof node !== "object") return false
  if (Array.isArray(node)) return node.some((n) => containsComponent(n, name))
  const el = node as { type?: unknown; props?: { children?: unknown } }
  const type = el.type as { name?: string; displayName?: string } | undefined
  if (type && (type.name === name || type.displayName === name)) return true
  return containsComponent(el.props?.children, name)
}

/** The `allowedRoles` a route's `RequireAuth` carries, or null if it has none. */
function allowedRolesOf(node: unknown): readonly string[] | null {
  if (!node || typeof node !== "object") return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = allowedRolesOf(child)
      if (found) return found
    }
    return null
  }
  const el = node as {
    type?: { name?: string; displayName?: string }
    props?: { allowedRoles?: readonly string[]; children?: unknown }
  }
  if (el.type?.name === "RequireAuth" || el.type?.displayName === "RequireAuth") {
    return el.props?.allowedRoles ?? null
  }
  return allowedRolesOf(el.props?.children)
}

const routesSource = fs.readFileSync(path.resolve(__dirname, "../../src/routes.tsx"), "utf8")

describe("the admin lanes are mounted and guarded — P4.7", () => {
  it.each([
    ["school", ["school_admin"]],
    ["platform", ["platform_admin"]],
  ])("gates /%s to exactly %j", (portal, expected) => {
    const route = appRoutes.find((r) => r.path === portal)
    expect(route, `/${portal} is not mounted`).toBeDefined()
    expect(containsComponent(route!.element, "RequireAuth")).toBe(true)
    expect(allowedRolesOf(route!.element)).toEqual(expected)
  })

  /*
   * The inverse of the above, and the assertion that would fail if someone
   * "simplified" the two lanes back into one guard admitting both roles. They
   * read different APIs gated to different roles; a shared guard would put each
   * role in front of screens whose every request 403s.
   */
  it("does not let either admin role into the other's lane", () => {
    const school = allowedRolesOf(appRoutes.find((r) => r.path === "school")!.element)
    const platform = allowedRolesOf(appRoutes.find((r) => r.path === "platform")!.element)
    expect(school).not.toContain("platform_admin")
    expect(platform).not.toContain("school_admin")
  })

  it("mounts both lanes at the top level, not inside another portal", () => {
    expect(appRoutes.map((r) => r.path)).toEqual(expect.arrayContaining(["school", "platform"]))
    expect(schoolAdminRoute.path).toBe("school")
    expect(platformAdminRoute.path).toBe("platform")
  })
})

describe("the teacher portal's role list — P4.7", () => {
  /*
   * Read off the mounted route rather than the source text, so a change to the
   * constant cannot pass by the array literal being renamed.
   */
  const teacherRoles = allowedRolesOf(appRoutes.find((r) => r.path === "teacher")!.element)

  it("keeps school_admin, whose data the teacher API really does return", () => {
    expect(teacherRoles).toContain("school_admin")
  })

  it("no longer admits platform_admin, for whom every panel there is empty", () => {
    expect(teacherRoles).not.toContain("platform_admin")
  })

  it("still admits the teacher", () => {
    expect(teacherRoles).toContain("teacher")
  })
})

describe("every role has somewhere to land — P4.7", () => {
  it.each([
    ["student", "/student"],
    ["parent", "/parent"],
    ["teacher", "/teacher"],
    ["school_admin", "/school"],
    ["platform_admin", "/platform"],
  ])("sends %s to %s", (role, expected) => {
    expect(portalPathForRole(role)).toBe(expected)
  })

  /*
   * The property that actually matters, stated as itself rather than left
   * implied by the table above: the portal a role is sent to must be one the
   * guard on that portal admits. A mismatch is an infinite redirect — the
   * guard bounces them to the path that bounces them back — and it is exactly
   * what P3.9 found when a parent was being sent to `/teacher`.
   */
  it.each(["student", "parent", "teacher", "school_admin", "platform_admin"])(
    "sends %s to a portal whose own guard admits them",
    (role) => {
      const home = portalPathForRole(role).replace(/^\//, "")
      const route = appRoutes.find((r) => r.path === home)
      expect(route, `${home} is not mounted`).toBeDefined()
      expect(allowedRolesOf(route!.element)).toContain(role)
    },
  )
})

describe("the settings lane still reaches every role — P4.7", () => {
  /*
   * `ALL_ROLES` is now assembled from four constants rather than three, and the
   * one it gained is the role most easily dropped: `platform_admin` no longer
   * appears in `TEACHER_ROLES`, so an `ALL_ROLES` still spread from the old
   * three would silently lock platform admins out of their own device list.
   * That would be invisible — the routes render, just not for them.
   */
  it.each(["/settings/devices", "/settings/notifications"])("admits all five roles on %s", (p) => {
    const route = appRoutes.find((r) => r.path === p)
    expect(route).toBeDefined()
    const roles = allowedRolesOf(route!.element)
    expect(roles).toEqual(
      expect.arrayContaining([
        "student",
        "parent",
        "teacher",
        "school_admin",
        "platform_admin",
      ]),
    )
  })
})

describe("the admin screens never render a raw error message — P4.7", () => {
  /*
   * The defect every surface of this phase has found at least once. Asserted in
   * the source because the alternative is rendering seven screens in seven
   * failure states, and the failure is a *string* reaching the DOM rather than
   * anything visual.
   */
  const SCREENS = [
    "src/portals/admin/screens/SchoolDashboard.tsx",
    "src/portals/admin/screens/Seats.tsx",
    "src/portals/admin/screens/Teachers.tsx",
    "src/portals/admin/screens/Classes.tsx",
    "src/portals/admin/screens/PlatformConsole.tsx",
    "src/portals/admin/screens/Activations.tsx",
    "src/portals/admin/screens/PipelineHealth.tsx",
  ]

  it.each(SCREENS)("%s renders no `error.message`", (relative) => {
    const source = fs.readFileSync(path.resolve(__dirname, "../..", relative), "utf8")
    expect(source).not.toMatch(/\berror\.message\b/)
    expect(source).not.toMatch(/\berr\.message\b/)
  })

  /*
   * And the positive half: a screen that renders no error at all would also
   * pass the assertion above. Every one of these reads a query, so every one
   * must have a failure path that goes through the outcome module.
   */
  it.each(SCREENS)("%s routes its failures through adminOutcome", (relative) => {
    const source = fs.readFileSync(path.resolve(__dirname, "../..", relative), "utf8")
    expect(source).toMatch(/from "@\/lib\/adminOutcome"/)
  })
})

describe("routes.tsx records why platform_admin left the teacher list — P4.7", () => {
  /*
   * A source assertion, which this suite normally avoids. It is here because
   * the removal is the kind of change a later reader would reverse as tidying:
   * the role holds the API's permissions, so re-adding it looks obviously
   * correct and breaks nothing a test could see. The comment is the only thing
   * that says why not, and a test is how a comment stops being optional.
   */
  it("keeps the no-super-role reasoning next to the constant", () => {
    expect(routesSource).toMatch(/no super-role/i)
    expect(routesSource).toMatch(/D1\.6\/D1\.10/)
  })
})
