import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

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
