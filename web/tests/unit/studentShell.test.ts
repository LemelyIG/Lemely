import { describe, expect, it } from "vitest"
import {
  STUDENT_INBOX_EMPTY,
  studentAccountLinks,
  studentDetailLine,
  studentInboxLinks,
  studentNavItems,
  studentPageTitle,
  studentShellTrail,
} from "@/portals/student/data"
import { studentRoute, STUDENT_BOTTOM_TABS } from "@/portals/student"
import { studentDestinationFor } from "@/lib/studentInbox"

const studentRoutePaths = (studentRoute.children ?? []).flatMap((child) => {
  const base = child.index ? "/student" : `/student/${(child as { path: string }).path}`
  const nested = (child.children ?? []).map((grand) =>
    grand.index ? base : `${base}/${(grand as { path: string }).path}`,
  )
  return [base, ...nested]
})
const mounted = (to: string) =>
  studentRoutePaths.some((p) => new RegExp(`^${p.replace(/:[^/]+/g, "[^/]+")}$`).test(to))

describe("student shell destinations (design A)", () => {
  it("leads the sidebar with design A's four rows, in order", () => {
    expect(studentNavItems.slice(0, 4).map((i) => i.label)).toEqual([
      "Overview",
      "Your classes",
      "Standings",
      "Friends",
    ])
  })

  it("puts Your profile, Your parents and Recently deleted in the account panel", () => {
    expect(studentAccountLinks.map((l) => [l.label, l.to])).toEqual([
      ["Your profile", "/student/profile"],
      ["Your parents", "/student/parents"],
      ["Recently deleted", "/student/recently-deleted"],
    ])
  })

  it("links the bell panel's footer to the inbox and announcements", () => {
    expect(studentInboxLinks.map((l) => l.to)).toEqual(["/student/notifications", "/student/announcements"])
  })

  it.each([...studentNavItems, ...studentAccountLinks, ...studentInboxLinks].map((i) => [i.label, i.to]))(
    "%s (%s) is a mounted student route",
    (_label, to) => {
      expect(mounted(to)).toBe(true)
    },
  )

  it("keeps today's four bottom tabs", () => {
    expect(STUDENT_BOTTOM_TABS.map((t) => t.label)).toEqual(["Overview", "Correct", "Classes", "Profile"])
  })

  it("uses design A's empty bell copy, with no em dash", () => {
    expect(STUDENT_INBOX_EMPTY).toBe("Nothing yet. Marked papers and messages from your teachers land here.")
    expect(STUDENT_INBOX_EMPTY).not.toMatch(/[—–]/)
  })
})

describe("studentShellTrail and studentPageTitle", () => {
  it("titles the portal root Overview with no trail", () => {
    expect(studentShellTrail("/student")).toEqual([])
    expect(studentPageTitle("/student")).toBe("Overview")
  })
  it("titles a section by its own name, one crumb, so no breadcrumbs", () => {
    expect(studentShellTrail("/student/friends")).toEqual([{ label: "Friends" }])
    expect(studentPageTitle("/student/friends")).toBe("Friends")
    expect(studentPageTitle("/student/correct")).toBe("Correct a paper")
  })
  it("titles a subject page by the subject's name when it is known", () => {
    const subjects = [{ code: "0606", name: "Add Maths" }]
    expect(studentPageTitle("/student/subject/0606", subjects)).toBe("Add Maths")
    expect(studentPageTitle("/student/subject/0606")).toBe("0606")
  })
  it("keeps a trail when drilled in, so breadcrumbs render", () => {
    expect(studentShellTrail("/student/practice/0580").map((c) => c.label)).toEqual(["Practice", "0580"])
  })
})

describe("studentDetailLine (design A: IGCSE · 3 subjects)", () => {
  it.each([
    ["IGCSE", 3, "IGCSE · 3 subjects"],
    ["IGCSE", 1, "IGCSE · 1 subject"],
    ["IGCSE", 0, "IGCSE · no subjects yet"],
    [null, 2, "2 subjects"],
  ] as const)("%s with %i subjects reads %s", (qualification, count, expected) => {
    expect(studentDetailLine(qualification, count)).toBe(expected)
  })
})

describe("studentDestinationFor", () => {
  it("matches the inbox screen's destinations", () => {
    expect(studentDestinationFor({ type: "announcement", payload: {} })).toBe("/student/announcements")
    expect(studentDestinationFor({ type: "streak_warning", payload: {} })).toBe("/student/profile")
    expect(
      studentDestinationFor({ type: "study_plan_reminder", payload: { subjectCode: "0580", sessionId: "s 1" } }),
    ).toBe("/student/plan/0580/session/s%201")
    expect(studentDestinationFor({ type: "grade_ready", payload: {} })).toBeNull()
  })
})
