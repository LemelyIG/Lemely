import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes } from "@/routes"
import { studentRoute } from "@/portals/student"
import { teacherRoute } from "@/portals/teacher"
import { parentRoute } from "@/portals/parent"

/*
 * P4.10 · where an unmatched path lands, pinned.
 *
 * The defect this file exists for has the property that makes a gate worth
 * writing: **it cannot fail loudly.**
 *
 * A portal route enumerates its children. Ask for `/student/nonsense` and none
 * of them match, so react-router keeps walking outward and the top-level
 * `path: "*"` answers instead. The reader gets a real 404 screen, correctly
 * worded, with a working way onward — and no sidebar, no header, no breadcrumb
 * trail, having been silently ejected from the app they were inside. Nothing
 * throws. Typecheck passes. `navigation.test.ts` passes, because every
 * destination it knows about *does* resolve; the paths that break this are by
 * definition the ones no nav entry names. The only way to see it is to render
 * a wrong URL and look, or to assert the fallback's existence in the route
 * table, which is what this does.
 *
 * `routes.tsx` and `portals/misc/NotFound.tsx` both carried the gap as a
 * written note from P3.1 onward, deferred to "once each portal layout is its
 * final shape". A note is not a gate: the marketing page had one of those too,
 * naming its own defect, for the whole build (see `marketing.test.ts`).
 *
 * The second half of the file pins the settings lane, for a related reason.
 * `/settings/devices` and `/settings/notifications` are the product's only
 * top-level *authenticated* routes, so they are the only two places where the
 * `ALL_ROLES` guard could be dropped without any portal noticing.
 */

/** The three portal subtrees, by the name their route uses. */
const PORTALS = [
  { name: "student", route: studentRoute },
  { name: "teacher", route: teacherRoute },
  { name: "parent", route: parentRoute },
] as const

/**
 * Walk a route element tree looking for a component by display name.
 *
 * Same helper as `marketing.test.ts`, and for the same reason: guards and
 * screens are React elements, so this is the only honest way to ask what a
 * route renders without rendering it. Matching by name rather than by type
 * identity keeps it working when the element is wrapped in a `Suspense` or a
 * frame, which is exactly how routing defects hide.
 */
function containsComponent(node: unknown, name: string): boolean {
  if (!node || typeof node !== "object") return false
  if (Array.isArray(node)) return node.some((n) => containsComponent(n, name))
  const el = node as { type?: unknown; props?: { children?: unknown } }
  const type = el.type as { name?: string; displayName?: string } | undefined
  if (type && (type.name === name || type.displayName === name)) return true
  return containsComponent(el.props?.children, name)
}

function sourceOf(relative: string): string {
  return fs.readFileSync(path.join(process.cwd(), relative), "utf8")
}

describe("every portal answers its own unmatched paths — P4.10", () => {
  it.each(PORTALS)("$name has a catch-all child", ({ route }) => {
    const paths = (route.children ?? []).map((child) => child.path)
    expect(paths).toContain("*")
  })

  /*
   * Order is load-bearing, not cosmetic. React-router ranks its matches, so a
   * `*` is outranked by any literal sibling regardless of position — but the
   * file reads top to bottom, and a `*` sitting in the middle of the list is
   * how the next person adding a route puts theirs after it and spends an hour
   * wondering why their screen renders a 404.
   */
  it.each(PORTALS)("$name puts the catch-all last", ({ route }) => {
    const children = route.children ?? []
    expect(children[children.length - 1]?.path).toBe("*")
  })

  /*
   * The distinction the whole change rests on. `PortalNotFound` renders the
   * body only; `NotFound` renders a full-screen frame with its own `SkipLink`
   * and its own `<main id={MAIN_CONTENT_ID}>`. Mounting the latter inside a
   * portal layout would put two `<main>` landmarks and two identical ids on
   * one page, so the skip link would jump to whichever the browser found
   * first. That looks perfectly fine in a screenshot, which is why it is
   * asserted here rather than left to the visual round.
   */
  it.each(PORTALS)("$name's catch-all renders PortalNotFound, not NotFound", ({ route }) => {
    const fallback = (route.children ?? []).find((child) => child.path === "*")
    expect(containsComponent(fallback?.element, "PortalNotFound")).toBe(true)
    expect(containsComponent(fallback?.element, "NotFound")).toBe(false)
  })

  it("still keeps the top-level catch-all, for paths outside every portal", () => {
    const catchAll = appRoutes.find((route) => route.path === "*")
    expect(catchAll).toBeDefined()
    expect(containsComponent(catchAll?.element, "NotFound")).toBe(true)
  })

  /*
   * The top-level catch-all must stay ungated. A mistyped URL from a
   * signed-out reader is a 404, not a login prompt: bouncing them to `/login`
   * to land somewhere that still is not the page they asked for is two wrong
   * answers instead of one. `routes.tsx` says so in a comment; this is the
   * version of that sentence which fails when someone changes it.
   */
  it("leaves the top-level catch-all ungated", () => {
    const catchAll = appRoutes.find((route) => route.path === "*")
    expect(containsComponent(catchAll?.element, "RequireAuth")).toBe(false)
  })

  /*
   * Two `<main>` elements on one page is the failure this split prevents, so
   * the source is checked as well as the route table: `PortalNotFound` must
   * not grow a frame later. Read as text because the landmark only exists once
   * the component renders, and rendering it needs a router and a jsdom this
   * suite deliberately does not have.
   */
  it("PortalNotFound renders no frame of its own", () => {
    const source = sourceOf("src/portals/misc/NotFound.tsx")
    const start = source.indexOf("export function PortalNotFound")
    const end = source.indexOf("function NotFoundBody")
    expect(start).toBeGreaterThan(-1)
    expect(end).toBeGreaterThan(start)
    const body = source.slice(start, end)
    expect(body).not.toContain("<main")
    expect(body).not.toContain("SkipLink")
    expect(body).not.toContain("MAIN_CONTENT_ID")
  })
})

describe("the settings lane stays reachable by every role — P4.10", () => {
  const settingsRoutes = appRoutes.filter((route) => route.path?.startsWith("/settings/"))

  it("mounts both screens at the top level", () => {
    expect(settingsRoutes.map((route) => route.path).sort()).toEqual([
      "/settings/devices",
      "/settings/notifications",
    ])
  })

  /*
   * Guarded, but never role-narrowed. The device limit is enforced per account
   * regardless of role and the at-risk-alert preference belongs to teachers and
   * parents, so narrowing either guard to one role would put a screen out of
   * reach of the roles it applies to — the exact defect P3.9 found when
   * `parent` was wrongly inside `TEACHER_ROLES`, and the mirror image of P4.9's
   * marketing page, which was guarded when it should have been public.
   */
  it.each(["/settings/devices", "/settings/notifications"])("guards %s", (routePath) => {
    const route = appRoutes.find((r) => r.path === routePath)
    expect(containsComponent(route?.element, "RequireAuth")).toBe(true)
  })

  it("admits all five roles to both settings screens", () => {
    const source = sourceOf("src/routes.tsx")
    // Both `/settings/*` routes must name ALL_ROLES, which is the union of the
    // three role lists — asserted here rather than trusting the name, because
    // a narrowed ALL_ROLES would satisfy a name check and fail every reader.
    const allRoles = source.match(/const ALL_ROLES = \[([^\]]*)\]/)?.[1] ?? ""
    expect(allRoles).toContain("STUDENT_ROLES")
    expect(allRoles).toContain("PARENT_ROLES")
    expect(allRoles).toContain("TEACHER_ROLES")

    // Anchored on the route declaration, not the bare path: `/settings/` also
    // appears in this file's prose, and counting comments as routes is how a
    // gate ends up asserting something other than what it claims to.
    const settingsBlocks = source.split('path: "/settings/').slice(1)
    expect(settingsBlocks).toHaveLength(2)
    for (const block of settingsBlocks) {
      expect(block.slice(0, 400)).toContain("ALL_ROLES")
    }
  })

  /*
   * Neither settings screen may render a raw `error.message` again. Every
   * `detail` `routers/me.py` produces is written for a client author — a JSON
   * field name, a camelCase key, a stringified Python exception — and this
   * lane's reader is any of the five roles, including a fifteen-year-old. See
   * `lib/settingsOutcome.ts` for the endpoint-by-endpoint evidence.
   */
  it.each([
    "src/portals/settings/DeviceSettings.tsx",
    "src/portals/settings/NotificationSettings.tsx",
  ])("%s renders no raw error message", (relative) => {
    const source = sourceOf(relative)
    const offences = source
      .split("\n")
      .map((line, index) => ({ line, number: index + 1 }))
      .filter(({ line }) => /\.error\.message|err\.message|error\.message/.test(line))
      .filter(({ line }) => !line.trimStart().startsWith("*"))
      .map(({ number }) => `${relative}:${number}`)
    expect(offences).toEqual([])
  })

  /*
   * The frame is what makes the lane a lane. Without it these two screens sit
   * outside every portal's chrome — which is how they shipped: no mark, no
   * navigation, no breadcrumb, no skip link, reached from four different
   * entry points across three portals.
   */
  it.each([
    "src/portals/settings/DeviceSettings.tsx",
    "src/portals/settings/NotificationSettings.tsx",
  ])("%s renders inside SettingsFrame", (relative) => {
    expect(sourceOf(relative)).toContain("<SettingsFrame")
  })
})
