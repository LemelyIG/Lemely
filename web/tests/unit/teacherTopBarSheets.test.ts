import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { backgroundState, underlyingPathname } from "@/lib/nav/backgroundLocation"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { resolveTrail } from "@/portals/teacher/data"

import { teacherRoute } from "@/portals/teacher"
import {
  CREATE_ACTIONS,
  HELP_HREF,
  PROFILE_EDIT_TO,
  SETTINGS_TO,
  roleLabel,
} from "@/portals/teacher/components/topBarActions"

/*
 * The teacher top bar's Create and profile sheets are lists of links. A link
 * to a route that no longer exists renders happily and fails only when a
 * teacher clicks it, so every destination is checked against the routes
 * `teacherRoute` actually mounts.
 */

const teacherRoutePaths = (teacherRoute.children ?? []).flatMap((child) => {
  const base = child.index ? "/teacher" : `/teacher/${(child as { path: string }).path}`
  const nested = (child.children ?? []).map((grand) =>
    grand.index ? base : `${base}/${(grand as { path: string }).path}`,
  )
  return [base, ...nested]
})

function mountedRoute(to: string): string | undefined {
  const pathname = to.split("?")[0]
  return teacherRoutePaths.find((pattern) =>
    new RegExp(`^${pattern.replace(/:[^/]+/g, "[^/]+")}$`).test(pathname),
  )
}

describe("teacher Create sheet", () => {
  it("offers the four starting points in order", () => {
    expect(CREATE_ACTIONS.map((a) => a.title)).toEqual([
      "Add a mark scheme",
      "AI quiz",
      "Announcement",
      "Class",
    ])
  })

  it.each(CREATE_ACTIONS.map((a) => [a.title, a.to] as const))(
    "%s links to a mounted route (%s)",
    (_title, to) => {
      expect(mountedRoute(to)).toBeDefined()
      expect(mountedRoute(to)).not.toBe("/teacher/*")
    },
  )

  it("sends the class action to the invite-code screen", () => {
    expect(CREATE_ACTIONS.find((a) => a.id === "class")?.to).toBe("/teacher/first-class")
  })

  it("opens the quiz form only through a query the Quizzes screen reads", () => {
    const quiz = CREATE_ACTIONS.find((a) => a.id === "quiz")!
    const query = new URLSearchParams(quiz.to.split("?")[1] ?? "")
    expect(query.get("new")).toBe("1")
    const source = readFileSync(
      resolve(__dirname, "../../src/portals/teacher/screens/Quizzes.tsx"),
      "utf8",
    )
    expect(source).toContain('searchParams.get("new") === "1"')
  })

  it("keeps every description to one line of plain copy", () => {
    for (const action of CREATE_ACTIONS) {
      expect(action.description).not.toMatch(/[—–]/)
      expect(action.description.length).toBeLessThanOrEqual(40)
    }
  })
})

describe("teacher profile sheet", () => {
  it.each([PROFILE_EDIT_TO, SETTINGS_TO])("%s is a mounted settings route", (to) => {
    expect(mountedRoute(to)).toBe("/teacher/settings")
  })

  it("points help and feedback at a real contact address", () => {
    expect(HELP_HREF).toMatch(/^mailto:[^@\s]+@[^@\s]+\.[a-z]+$/)
  })

  it.each([
    ["teacher", "Teacher"],
    ["school_admin", "School Admin"],
    ["platform_admin", "Platform Admin"],
  ])("labels role %s as %s", (role, label) => {
    expect(roleLabel(role)).toBe(label)
  })
})

describe("settings opens over the current page", () => {
  it("Edit profile and Settings both open the default (Profile) tab", () => {
    expect(PROFILE_EDIT_TO).toBe("/teacher/settings")
    expect(SETTINGS_TO).toBe("/teacher/settings")
  })

  it("useOverlayState carries the current page as the background location", () => {
    let seen: unknown = null
    function Probe() {
      seen = useOverlayState()
      return null
    }
    renderToStaticMarkup(
      createElement(MemoryRouter, { initialEntries: ["/teacher/classes?x=1#top"] }, createElement(Probe)),
    )
    expect(seen).toEqual({
      backgroundLocation: { pathname: "/teacher/classes", search: "?x=1", hash: "#top" },
    })
  })

  it("the top-bar title follows the page under the dialog, not Settings", () => {
    const state = backgroundState({ pathname: "/teacher", search: "", hash: "" })
    const under = underlyingPathname({ pathname: SETTINGS_TO, state, overlayBase: "/teacher/settings" })
    expect(under).toBe("/teacher")
    expect(resolveTrail(under)).toEqual([{ label: "Overview" }])
    // A direct load has no background: the trail falls back to Settings itself.
    expect(
      underlyingPathname({ pathname: SETTINGS_TO, state: null, overlayBase: "/teacher/settings" }),
    ).toBe(SETTINGS_TO)
    // Outside the overlay the pathname is untouched, state or not.
    expect(
      underlyingPathname({ pathname: "/teacher/classes", state, overlayBase: "/teacher/settings" }),
    ).toBe("/teacher/classes")
  })
})
