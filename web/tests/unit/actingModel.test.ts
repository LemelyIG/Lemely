import { describe, expect, it } from "vitest"
import {
  leadLabel,
  lackedPermissions,
  lackedSummary,
  membershipEndedNotice,
  MEMBERSHIP_UNCONFIRMED_NOTICE,
  ownAccountNote,
  SCREEN_PERMISSIONS,
  SELF_OPTION_ID,
  switcherOptions,
} from "@/lib/actingModel"
import { PRESET_PERMISSIONS } from "@/lib/assistantRoles"

/* The words of the "working as" UI, and the arithmetic behind "what your role can't do". */

describe("switcherOptions", () => {
  it("puts Me first, then each team with its role, keyed by the lead's user id", () => {
    const options = switcherOptions([
      { teacherId: "t1", teacherName: "Mr Hassan", role: "marker" },
      { teacherId: "t2", teacherName: "Ms Ahmed", role: "co_teacher" },
    ])
    expect(options).toEqual([
      { id: SELF_OPTION_ID, label: "Me" },
      { id: "t1", label: "Mr Hassan (Marker)" },
      { id: "t2", label: "Ms Ahmed (Co-teacher)" },
    ])
  })

  it("is just Me for a teacher who assists nobody", () => {
    expect(switcherOptions([])).toEqual([{ id: SELF_OPTION_ID, label: "Me" }])
  })

  it("labels the viewer role plainly", () => {
    expect(leadLabel({ teacherName: "Mrs Ali", role: "viewer" })).toBe("Mrs Ali (Viewer)")
  })
})

describe("what a role can't do", () => {
  it("is nothing for a co-teacher", () => {
    expect(lackedPermissions(PRESET_PERMISSIONS.co_teacher)).toEqual([])
    expect(lackedSummary(PRESET_PERMISSIONS.co_teacher)).toBeNull()
  })

  it("does not count See usage, which no teacher screen is behind", () => {
    expect(SCREEN_PERMISSIONS).not.toContain("view_usage")
    expect(lackedSummary(["mark", "regrade", "generate_quiz", "manage_classes", "view_results", "manage_students"])).toBeNull()
  })

  it("lists, in catalogue order, what the marker preset lacks", () => {
    expect(lackedSummary(PRESET_PERMISSIONS.marker)).toBe(
      "Your role can't generate quizzes, manage classes or manage students.",
    )
  })

  it("lists what the viewer preset lacks", () => {
    expect(lackedSummary(PRESET_PERMISSIONS.viewer)).toBe(
      "Your role can't mark papers, regrade papers, generate quizzes, manage classes or manage students.",
    )
  })

  it("reads a single missing permission without a list", () => {
    expect(lackedSummary(["mark", "regrade", "generate_quiz", "view_results", "manage_students"])).toBe("Your role can't manage classes.")
  })

  it("follows the permissions as toggled, not the preset", () => {
    // A marker the lead also let manage classes.
    expect(lackedSummary([...PRESET_PERMISSIONS.marker, "manage_classes"])).toBe("Your role can't generate quizzes or manage students.")
  })
})

describe("notices", () => {
  it("names the lead whose team ended", () => {
    expect(membershipEndedNotice("Mr Hassan")).toBe("Your access to Mr Hassan's team has ended, so you're working as yourself again.")
    expect(membershipEndedNotice(null)).toBe("Your access to that team has ended, so you're working as yourself again.")
  })

  it("says plainly that a choice could not be confirmed, and what to do", () => {
    expect(MEMBERSHIP_UNCONFIRMED_NOTICE).toMatch(/working as yourself/)
    expect(MEMBERSHIP_UNCONFIRMED_NOTICE).toMatch(/Pick the team again/)
  })

  it("tells an own-account page's reader it is theirs, not the lead's", () => {
    expect(ownAccountNote("Mr Hassan")).toBe("This page is about your own account, not Mr Hassan's. Working as Mr Hassan doesn't change it.")
  })

  it("uses no em dash anywhere (check:copy bans it in product copy)", () => {
    const all = [membershipEndedNotice("X"), membershipEndedNotice(null), MEMBERSHIP_UNCONFIRMED_NOTICE, ownAccountNote("X"), lackedSummary([]) ?? "", lackedSummary(["mark"]) ?? ""]
    for (const line of all) expect(line.includes("—")).toBe(false)
  })
})
