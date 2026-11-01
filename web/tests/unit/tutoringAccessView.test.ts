import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  ASK_SCHOOL_LINE,
  COUNTING_EXPLAINER,
  COUNTING_LABEL,
  EMPTY_BLOCKS_LINE,
  EMPTY_GRANTS_LINE,
  EMPTY_LOG_LINE,
  GRANT_STATUS_VIEW,
  SHARING_EXPLAINER,
  SHARING_PARENTS_LINE,
  UNBLOCK_NOTE,
  accessLogView,
  blockRowView,
  classAccessView,
  countingChecked,
  countingUpdate,
  grantRowView,
  leaveClassCopy,
  splitGrants,
  stopSharingCopy,
  unblockSheetCopy,
} from "@/lib/tutoring/accessView"
import type { AccessLogEntry, ClassAccessItem, Grant, GrantStatus } from "@/lib/tutoringTypes"
import { stripComments } from "./support/jsxSource"

/*
 * T23 · S-38 logic (SPEC §d). Every fixed sentence is parsed out of the SPEC's
 * S-38 block; the masking rules (a student never learns a tutor blocked them,
 * SPEC §i.8) are checked over every GrantStatus value the SPEC declares.
 */

const WEB = join(import.meta.dirname, "..", "..")
const REPO = join(WEB, "..")
const SPEC = readFileSync(join(REPO, "docs", "tutoring", "SPEC.md"), "utf8")

const S38_START = SPEC.indexOf("**S-38 · Tutors & your data**")
const S38 = SPEC.slice(S38_START, SPEC.indexOf("### Teacher (T)", S38_START))

function quotedAfter(anchor: string, from = S38): string {
  const at = from.indexOf(anchor)
  expect(at, `anchor not in SPEC S-38: ${anchor}`).toBeGreaterThan(-1)
  const open = from.indexOf('"', at + anchor.length)
  const close = from.indexOf('"', open + 1)
  return from.slice(open + 1, close)
}

function grant(overrides: Partial<Grant> = {}): Grant {
  return {
    grantId: "g1",
    tutor: {
      tutorId: "t1",
      publicName: "Nour A.",
      headline: "IGCSE Maths",
      subjects: [{ code: "0580", name: "Mathematics" }],
      modes: ["virtual"],
      area: { code: "maadi", name: "Maadi" },
      rating: { state: "new", average: null, count: 0 },
    },
    createdAt: "2026-01-08T15:00:00Z",
    revokedAt: null,
    status: "active",
    scope: "all_subjects_derived",
    alsoTeachesClasses: [],
    ...overrides,
  }
}

const SPEC_STATUSES: GrantStatus[] = (() => {
  const at = SPEC.indexOf("GrantStatusLit = Literal[")
  const end = SPEC.indexOf("class GrantDTO", at)
  return [...SPEC.slice(at, end).matchAll(/"([a-z_]+)"/g)].map((m) => m[1] as GrantStatus)
})()

// ── Stop sharing ──────────────────────────────────────────────────────────

describe("stopSharingCopy", () => {
  const base = quotedAfter("confirm sheet:")
  const classTemplate = quotedAfter("when `alsoTeachesClasses` is non-empty,")
  const always = quotedAfter("and always")

  it("reads the three SPEC sentences from the SPEC", () => {
    expect(base).toBe("They can't see your progress through Lemely's tutoring pages from now on.")
    expect(classTemplate).toContain("{name}")
    expect(always).toContain("still counted in their results")
  })

  it("without a class it is the two always-lines and nothing about classes", () => {
    const copy = stopSharingCopy(grant({ alsoTeachesClasses: [] }))
    expect(copy.lines).toEqual([base, always])
    expect(copy.lines.join(" ")).not.toMatch(/class/i)
  })

  it("adds the class line, between the two, when the tutor also teaches a class", () => {
    const copy = stopSharingCopy(grant({ alsoTeachesClasses: ["Maths 10A"] }))
    expect(copy.lines).toEqual([base, classTemplate.replace("{name}", "Maths 10A"), always])
  })

  it("names several classes in one sentence", () => {
    const copy = stopSharingCopy(grant({ alsoTeachesClasses: ["Maths 10A", "Physics 11B", "Extra"] }))
    expect(copy.lines).toHaveLength(3)
    expect(copy.lines[1]).toBe(
      "This tutor also teaches your classes Maths 10A, Physics 11B and Extra, so they still see your class progress there.",
    )
    expect(stopSharingCopy(grant({ alsoTeachesClasses: ["A", "B"] })).lines[1]).toContain("your classes A and B,")
  })

  it("keeps a class name as plain text", () => {
    const hostile = "<b>Maths</b> & <script>x</script>"
    const copy = stopSharingCopy(grant({ alsoTeachesClasses: [hostile] }))
    expect(copy.lines[1]).toContain(hostile)
  })

  it("title and buttons name the act and the tutor", () => {
    const copy = stopSharingCopy(grant())
    expect(copy.title).toBe("Stop sharing with Nour A.?")
    expect(copy.confirmLabel).toBe("Stop sharing")
    expect(copy.cancelLabel).toBe("Keep sharing")
  })
})

// ── Grants ────────────────────────────────────────────────────────────────

describe("grant status view", () => {
  it("covers every status the SPEC declares, seven of them", () => {
    expect(SPEC_STATUSES).toHaveLength(7)
    expect(Object.keys(GRANT_STATUS_VIEW).sort()).toEqual([...SPEC_STATUSES].sort())
  })

  it("a tutor-side ending reads the same for every cause (SPEC i.8)", () => {
    const unavailable = GRANT_STATUS_VIEW.tutor_unavailable
    expect(GRANT_STATUS_VIEW.tutor_suspended).toEqual(unavailable)
    expect(GRANT_STATUS_VIEW.tutor_closed).toEqual(unavailable)
  })

  it("no ended status names a suspension, a closure or a block by the tutor", () => {
    for (const status of SPEC_STATUSES) {
      const view = GRANT_STATUS_VIEW[status]
      const text = `${view.label} ${view.detail}`
      if (status !== "blocked") expect(text, status).not.toMatch(/block/i)
      expect(text, status).not.toMatch(/suspend|clos(?:e|ed|ing)|banned|removed|safety|report/i)
    }
  })

  it("`blocked` is the student's own block and says so", () => {
    expect(GRANT_STATUS_VIEW.blocked.label).toBe("You blocked this tutor")
  })

  it("only an active grant can be stopped; ended ones carry a label and an icon of their own", () => {
    expect(GRANT_STATUS_VIEW.active.live).toBe(true)
    for (const status of SPEC_STATUSES.filter((s) => s !== "active")) {
      expect(GRANT_STATUS_VIEW[status].live, status).toBe(false)
    }
    const icons = new Set(Object.values(GRANT_STATUS_VIEW).map((v) => v.icon))
    expect(icons.size).toBeGreaterThanOrEqual(4)
  })
})

describe("grantRowView and splitGrants", () => {
  it("shows the tutor, the since date in the tutor's zone, and Stop sharing only when live", () => {
    const live = grantRowView(grant())
    expect(live).toMatchObject({
      tutorName: "Nour A.",
      sinceLine: "Since 8 Jan 2026",
      canStop: true,
      stopLabel: "Stop sharing with Nour A.",
    })
    const ended = grantRowView(grant({ status: "revoked", revokedAt: "2026-02-01T10:00:00Z" }))
    expect(ended.canStop).toBe(false)
    expect(ended.sinceLine).toBe("Since 8 Jan 2026, ended 1 Feb 2026")
  })

  it("an ended grant without an end date says only when it began", () => {
    expect(grantRowView(grant({ status: "tutor_unavailable", revokedAt: null })).sinceLine).toBe("Since 8 Jan 2026")
  })

  it("splits live from ended, keeping the API's order inside each", () => {
    const items = [
      grant({ grantId: "a", status: "active" }),
      grant({ grantId: "b", status: "revoked" }),
      grant({ grantId: "c", status: "active" }),
      grant({ grantId: "d", status: "tutor_unavailable" }),
    ]
    const { live, ended } = splitGrants(items)
    expect(live.map((g) => g.grantId)).toEqual(["a", "c"])
    expect(ended.map((g) => g.grantId)).toEqual(["b", "d"])
  })

  it("the empty lines are the SPEC's", () => {
    expect(EMPTY_GRANTS_LINE).toBe(quotedAfter("No grants:"))
    expect(EMPTY_LOG_LINE).toBe(quotedAfter("Empty log:"))
  })
})

// ── The explainer ─────────────────────────────────────────────────────────

describe("sharing explainer (F29)", () => {
  it("is the SPEC's two sentences", () => {
    expect(SHARING_EXPLAINER).toBe(quotedAfter("Explainer (F29):"))
    const parents = quotedAfter('Never your answer sheets, and never the time of day you used Lemely." ')
    expect(SHARING_PARENTS_LINE).toBe(parents)
  })
})

// ── Who looked ────────────────────────────────────────────────────────────

describe("accessLogView", () => {
  const entry = (overrides: Partial<AccessLogEntry> = {}): AccessLogEntry => ({
    tutorId: "t1",
    tutorName: "Nour A.",
    action: "detail",
    accessedAt: "2026-01-08T15:05:00Z",
    ...overrides,
  })

  it("uses the SPEC's two verbs", () => {
    expect(accessLogView(entry({ action: "detail" })).action).toBe("viewed your progress")
    expect(accessLogView(entry({ action: "list" })).action).toBe("saw you in their student list")
    expect(S38).toContain('"viewed your progress" / "saw you in their student list"')
  })

  it("gives the time in the tutor's zone and links a tutor who still has a profile id", () => {
    const view = accessLogView(entry())
    expect(view.timeLabel).toBe("Thu 8 Jan · 17:05 Cairo time")
    expect(view.tutorHref).toBe("/student/tutors/t1")
    expect(accessLogView(entry({ tutorId: null })).tutorHref).toBeNull()
  })

  it("a parent's view names the child", () => {
    expect(accessLogView(entry({ action: "detail" }), "Maya").action).toBe("viewed Maya's progress")
    expect(accessLogView(entry({ action: "list" }), "Maya").action).toBe("saw Maya in their student list")
  })

  it("encodes a tutor id in the link", () => {
    expect(accessLogView(entry({ tutorId: "a/b?c" })).tutorHref).toBe("/student/tutors/a%2Fb%3Fc")
  })
})

// ── Classes ───────────────────────────────────────────────────────────────

describe("classAccessView", () => {
  const item = (overrides: Partial<ClassAccessItem> = {}): ClassAccessItem => ({
    classId: "c1",
    className: "Maths 10A",
    teacherName: "Ms Hala",
    schoolName: null,
    leavable: true,
    teacherIsYourTutor: false,
    ...overrides,
  })

  it("a school-less class is called independent and can be left", () => {
    const view = classAccessView(item())
    expect(view.whereLine).toBe("Independent class")
    expect(view.canLeave).toBe(true)
    expect(view.askSchool).toBe(false)
  })

  it("a school class names the school and is not leavable here (ask your school)", () => {
    const view = classAccessView(item({ schoolName: "Helwan Science Centre", leavable: false }))
    expect(view.whereLine).toBe("Helwan Science Centre")
    expect(view.canLeave).toBe(false)
    expect(view.askSchool).toBe(true)
    expect(ASK_SCHOOL_LINE.length).toBeGreaterThan(10)
    expect(S38).toContain('"Ask your school" note')
  })

  it("flags a teacher who is also the student's tutor", () => {
    expect(classAccessView(item({ teacherIsYourTutor: true })).alsoTutor).toBe(true)
    expect(classAccessView(item()).alsoTutor).toBe(false)
  })

  it("the leave sheet is the SPEC's sentence with the class name filled in", () => {
    const template = quotedAfter("S17, confirm sheet:")
    const copy = leaveClassCopy(item())
    expect(copy.title).toBe("Leave Maths 10A?")
    expect(copy.body).toBe(template.replace("{class}", "Maths 10A"))
    expect(copy.confirmLabel).toBe("Leave class")
  })
})

// ── Counting and blocks ───────────────────────────────────────────────────

describe("results counting", () => {
  it("the label and the explanation are the SPEC's", () => {
    expect(COUNTING_LABEL).toBe(quotedAfter("C-14"))
    expect(COUNTING_EXPLAINER).toBe(quotedAfter("(default on) with:"))
  })

  it("the box is ticked when the student has not opted out, and saving flips it", () => {
    expect(countingChecked({ outcomeStatsOptOut: false })).toBe(true)
    expect(countingChecked({ outcomeStatsOptOut: true })).toBe(false)
    expect(countingUpdate(true)).toEqual({ outcomeStatsOptOut: false })
    expect(countingUpdate(false)).toEqual({ outcomeStatsOptOut: true })
  })
})

describe("blocked tutors", () => {
  it("a row offers Unblock by name and says what unblocking does not undo", () => {
    const row = blockRowView({ counterpartId: "t9", displayName: "Omar K.", createdAt: "2026-01-09T09:00:00Z" })
    expect(row).toMatchObject({ name: "Omar K.", unblockLabel: "Unblock Omar K.", sinceLine: "Blocked 9 Jan 2026" })
    expect(EMPTY_BLOCKS_LINE).toBe("You haven't blocked any tutors.")
  })

  it("Unblock asks first, and the sheet carries what unblocking does not undo", () => {
    const copy = unblockSheetCopy({ displayName: "Omar K." })
    expect(copy.title).toBe("Unblock Omar K.?")
    expect(copy.consequence).toBe(UNBLOCK_NOTE)
    expect(UNBLOCK_NOTE).toBe("Unblocking doesn't bring back sharing or cancelled sessions.")
    expect(copy.confirmLabel).toBe("Unblock")
    expect(copy.cancelLabel).toBe("Keep blocked")
  })

  it("a block's name is returned as given", () => {
    expect(unblockSheetCopy({ displayName: "<b>Omar</b>" }).title).toBe("Unblock <b>Omar</b>?")
  })

  it("the screen never calls the unblock mutation straight from the button", () => {
    const screen = stripComments(readFileSync(join(WEB, "src/portals/student/screens/tutoring/TutorAccess.tsx"), "utf8"))
    const at = screen.indexOf("function BlocksSection")
    expect(at).toBeGreaterThan(-1)
    const section = screen.slice(at, screen.indexOf("export function TutorAccess", at))
    // The row button opens the sheet; only the sheet's confirm removes the block.
    const calls = [...section.matchAll(/remove\.mutateAsync\(/g)]
    expect(calls).toHaveLength(1)
    const mutate = calls[0].index ?? 0
    const buttonAt = section.indexOf("Unblock\n")
    expect(buttonAt).toBeGreaterThan(-1)
    expect(section.slice(section.lastIndexOf("<Button", buttonAt), buttonAt)).not.toContain("unblock(")
    expect(section).toContain("ConfirmModal")
    expect(section.indexOf("ConfirmModal")).toBeGreaterThan(-1)
    expect(mutate).toBeLessThan(section.indexOf("<ConfirmModal"))
  })
})

// ── Source rules ──────────────────────────────────────────────────────────

describe("what the S-38 files must not say", () => {
  const FILES = [
    "src/lib/tutoring/accessView.ts",
    "src/components/tutoring/stop-sharing-sheet.tsx",
    "src/portals/student/screens/tutoring/TutorAccess.tsx",
  ]

  it("scans three files", () => {
    for (const file of FILES) {
      expect(stripComments(readFileSync(join(WEB, file), "utf8")).length, file).toBeGreaterThan(200)
    }
  })

  it("never claims a tutor blocked, suspended or closed anything in student-facing words", () => {
    for (const file of FILES) {
      const code = stripComments(readFileSync(join(WEB, file), "utf8"))
      const strings = [...code.matchAll(/"([^"\n]{12,})"|`([^`\n]{12,})`/g)].map((m) => m[1] ?? m[2])
      for (const text of strings) {
        expect(text, `${file}: ${text}`).not.toMatch(/blocked you|tutor blocked|suspended|was closed|has been closed/i)
      }
    }
  })

  it("no client branch reads tutor_suspended or tutor_closed apart from the shared status table", () => {
    const screen = stripComments(readFileSync(join(WEB, "src/portals/student/screens/tutoring/TutorAccess.tsx"), "utf8"))
    expect(screen).not.toMatch(/tutor_suspended|tutor_closed/)
    const sheet = stripComments(readFileSync(join(WEB, "src/components/tutoring/stop-sharing-sheet.tsx"), "utf8"))
    expect(sheet).not.toMatch(/tutor_suspended|tutor_closed/)
  })
})
