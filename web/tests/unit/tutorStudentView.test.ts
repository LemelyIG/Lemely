import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement as h, isValidElement, type ReactElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { MyStudents } from "@/portals/teacher/screens/tutoring/MyStudents"
import { TutorStudentDetail } from "@/portals/teacher/screens/tutoring/TutorStudentDetail"
import { StudentDetail as TeacherStudentDetail, StudentDetailView } from "@/portals/teacher/screens/StudentDetail"
import { TBody, TR } from "@/components/ui/table"
import {
  MY_STUDENTS_INTRO,
  NO_STUDENTS_LINE,
  NO_TUTOR_PROFILE_ACTION,
  NO_TUTOR_PROFILE_BODY,
  NO_TUTOR_PROFILE_HEADING,
  TUTOR_PROFILE_PATH,
  TUTOR_STUDENTS_PATH,
  TUTOR_STUDENT_CRUMB,
  TUTOR_STUDENT_TITLE,
  accessEndedHeading,
  dayLabel,
  isNoTutorProfile,
  isStudentNotFound,
  sharedLine,
  studentLoadFailureMessage,
  studentNameFromState,
  studentRowView,
  tutorStudentDates,
  tutorStudentDatesIn,
  tutorStudentPath,
} from "@/lib/tutoring/tutorStudentView"
import type { StudentDetail } from "@/lib/teacherTypes"
import type { TutorStudentDetail as TutorStudentDetailDTO, TutorStudentItem } from "@/lib/tutoringTypes"
import { stripComments } from "./support/jsxSource"

/*
 * T26 · the tutor's two student screens (T-19 My students, T-20 Student detail).
 *
 * The runner is `environment: "node"` with no jsdom, so the screens are rendered
 * to static markup with `react-dom/server`, the way `tutoringSessionScreens`
 * does. Only the data hooks and the lazy chart are replaced; the screens, the
 * shared T-05 composition (`StudentDetailView`) and every component under them
 * are the real ones.
 *
 * What is guarded, each proved by a mutation in the lane's export:
 *   1. The five things T-20 removes from T-05 are not in the tutor's markup, and
 *      the same assertions find them in the teacher's markup (non-vacuity).
 *   2. Every date the tutor sees is a calendar day: no clock time, no "3 hours
 *      ago", even if the API sent an instant.
 *   3. `access_ended` is one state: the same markup whatever the server said,
 *      no student data, no retry, no reason.
 *   4. The screen never clears or refetches the detail itself (the guard in
 *      `useTutoringApi` does the clearing; a second remover loops).
 * The expected sentences are parsed out of SPEC §d, not written out again.
 */

const harness = vi.hoisted(() => ({
  student: undefined as unknown,
  list: undefined as unknown,
  teacher: undefined as unknown,
  profile: undefined as unknown,
  studentCalls: [] as string[],
  listCalls: [] as unknown[],
}))

vi.mock("@/lib/hooks/useTutoringApi", () => ({
  useTutorStudent: (studentId: string) => {
    harness.studentCalls.push(studentId)
    return harness.student
  },
  useTutorStudents: (params: unknown) => {
    harness.listCalls.push(params)
    return harness.list
  },
  useOwnTutorProfile: () => harness.profile,
}))

vi.mock("@/lib/hooks/useTeacherApi", () => ({ useStudentDetail: () => harness.teacher }))
vi.mock("@/components/ui/lazy-chart", () => ({ LineChart: () => null }))

const WEB = join(import.meta.dirname, "..", "..")
const SPEC = readFileSync(join(WEB, "..", "docs", "tutoring", "SPEC.md"), "utf8")
const T19 = SPEC.slice(SPEC.indexOf("**T-19 · My students**"), SPEC.indexOf("**T-20 · Student detail (tutor view)**"))
const T20 = SPEC.slice(SPEC.indexOf("**T-20 · Student detail (tutor view)**"), SPEC.indexOf("**T-21 · Profile preview"))

/** The first quoted sentence after `anchor` in a SPEC screen block. */
function quoted(block: string, anchor: string): string {
  const at = block.indexOf(anchor)
  expect(at, `anchor not in SPEC: ${anchor}`).toBeGreaterThan(-1)
  const open = block.indexOf('"', at + anchor.length)
  return block.slice(open + 1, block.indexOf('"', open + 1))
}
const SPEC_INTRO = quoted(T19, "**Contains.**")
const SPEC_EMPTY = quoted(T19, "Empty:")
const SPEC_SHARED = quoted(T20, "with:")
const SPEC_ENDED = quoted(T20, "→ C-11:")

// ── Fixtures ────────────────────────────────────────────────────────────────

/** What the tutor projection sends: every instant already cut to its tutor-zone day. */
function tutorDetail(overrides: Partial<StudentDetail> = {}): StudentDetail {
  return {
    studentId: "s1",
    displayName: "Maya R.",
    subjects: [{ subjectCode: "0580", predictedGrade: "B", latestPercentage: 71.4, paperCount: 3 }],
    attempts: [
      {
        paperId: "0580/22",
        subjectCode: "0580",
        paperNumber: 2,
        paperVariant: 2,
        awardedMarks: 60,
        maximumMarks: 90,
        percentage: 66.7,
        grade: "B",
        recordedAt: "2026-10-20",
      },
      {
        paperId: "0580/22",
        subjectCode: "0580",
        paperNumber: 2,
        paperVariant: 2,
        awardedMarks: 64,
        maximumMarks: 90,
        percentage: 71.1,
        grade: "B",
        recordedAt: "2026-10-20",
      },
    ],
    weaknesses: [{ topic: "Algebra", lostMarks: 9, maximumMarks: 20, accuracy: 0.55, questionIds: [] }],
    trend: [
      { recordedAt: "2026-10-20", percentage: 66.7 },
      { recordedAt: "2026-10-20", percentage: 71.1 },
    ],
    isAtRisk: true,
    atRiskFlags: [
      {
        reason: "inactive",
        summary: "No papers submitted in 15 days (last active 2026-10-20).",
        evidence: { daysInactive: 15, lastActiveAt: "2026-10-20" },
        // The server never sends this to a tutor; the screen must not trust that.
        acknowledged: true,
      },
    ],
    engagement: { totalPapers: 3, lastActiveAt: "2026-10-20", daysSinceLastSubmission: 15 },
    ...overrides,
  } as StudentDetail
}

/** The teacher's version of the same student: real instants. */
function teacherDetail(): StudentDetail {
  const base = tutorDetail()
  return {
    ...base,
    attempts: base.attempts.map((a, i) => ({ ...a, recordedAt: `2026-10-20T0${i + 1}:40:00Z` })),
    trend: base.trend.map((p, i) => ({ ...p, recordedAt: `2026-10-20T0${i + 1}:40:00Z` })),
    engagement: { ...base.engagement, lastActiveAt: "2026-10-20T01:40:00Z" },
  }
}

/** T19 and T20 send the grant's day in the tutor's zone, never an instant (ID-9, F30-4). */
const GRANTED_AT = "2026-01-08"

function dto(detail: StudentDetail = tutorDetail()): TutorStudentDetailDTO {
  return { detail, grantId: "g1", grantedAt: GRANTED_AT, accessRecordedAt: "2026-10-27T09:00:00Z" }
}

function item(overrides: Partial<TutorStudentItem> = {}): TutorStudentItem {
  return {
    studentId: "s1",
    displayName: "Maya R.",
    grantId: "g1",
    grantedAt: GRANTED_AT,
    upcomingSessions: 2,
    ...overrides,
  }
}

function result(over: Record<string, unknown>) {
  return { refetch: vi.fn(), fetchStatus: "idle", isPending: false, isError: false, ...over }
}
const success = (data: unknown) => result({ status: "success", data, error: null })
const failure = (error: unknown) => result({ status: "error", data: undefined, error, isError: true })
const pending = () => result({ status: "pending", data: undefined, error: null, isPending: true, fetchStatus: "fetching" })

function accessEnded(message = "403 Forbidden", extra: Record<string, unknown> = {}) {
  return new ApiError(403, message, { code: "access_ended", ...extra })
}

function renderAt(element: ReactElement, path: string, route: string, state?: unknown): string {
  return renderToStaticMarkup(
    h(
      MemoryRouter,
      { initialEntries: [{ pathname: path, state }] },
      h(Routes, null, h(Route, { path: route, element })),
    ),
  )
}
const detailPage = (state?: unknown) =>
  renderAt(h(TutorStudentDetail), "/teacher/tutoring/students/s1", "/teacher/tutoring/students/:studentId", state)
const listPage = () => renderAt(h(MyStudents), "/teacher/tutoring/students", "/teacher/tutoring/students")
const teacherPage = () => renderAt(h(TeacherStudentDetail), "/teacher/students/s1", "/teacher/students/:studentId")

/** The text of a markup string, tags removed and entities decoded enough to read. */
function text(markup: string): string {
  return markup
    .replace(/<[^>]*>/g, " ")
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
}

const CLOCK_TIME = /\b\d{1,2}:\d{2}\b/
const RELATIVE_TIME = /\b(ago|just now|yesterday|today|minutes?|hours?)\b/i

beforeEach(() => {
  harness.student = success(dto())
  harness.list = success({ items: [item()], nextCursor: null })
  harness.teacher = success(teacherDetail())
  harness.profile = success({ zone: "Africa/Cairo", zoneLabel: "Cairo time" })
  harness.studentCalls.length = 0
  harness.listCalls.length = 0
})
afterEach(() => vi.restoreAllMocks())

// ── 1 · What T-20 removes ───────────────────────────────────────────────────

/** Things only the teacher's page may draw, each with the markup that proves it. */
const REMOVED: Array<[string, RegExp]> = [
  ["attempt drill-down and remark", /remark|View \//i],
  ["assign practice", /assign practice/i],
  ["at-risk acknowledge", /acknowledg/i],
  ["integrity signals", /integrity|plagiari|AI-content/i],
  ["a Coming soon placeholder for any of them", /coming soon/i],
  ["an Actions column", /<th[^>]*>\s*(<span[^>]*>)?\s*Actions/i],
  ["a disabled control", /\bdisabled\b/],
  ["any button", /<button\b/],
]

describe("T-20 removes five things from T-05", () => {
  it("draws none of them for the tutor, with a stale 'acknowledged' flag in the data", () => {
    const markup = detailPage()
    expect(markup).toContain("Maya R.")
    expect(markup).toContain("Attempt history")
    for (const [what, pattern] of REMOVED) {
      expect(markup, what).not.toMatch(pattern)
    }
  })

  it("finds every one of them in the teacher's page (the check can fail)", () => {
    const markup = teacherPage()
    const found = REMOVED.filter(([what, pattern]) => pattern.test(markup) && what !== "integrity signals")
    // Integrity signals have no teacher control either (T-05 renders none); the other seven exist.
    expect(found.map(([what]) => what)).toEqual([
      "attempt drill-down and remark",
      "assign practice",
      "at-risk acknowledge",
      "a Coming soon placeholder for any of them",
      "an Actions column",
      "a disabled control",
      "any button",
    ])
    expect(found.length).toBe(REMOVED.length - 1)
  })

  it("keeps the panels the tutor is allowed: subjects, trend, engagement, weaknesses, history", () => {
    const t = text(detailPage())
    for (const heading of ["Subjects", "Performance over time", "Engagement", "Weaknesses", "Attempt history"]) {
      expect(t, heading).toContain(heading)
    }
    expect(t).toContain("No papers submitted in 15 days (last active 2026-10-20).")
  })

  it("links nowhere but back to the list: no attempt, review or class route", () => {
    const hrefs = [...detailPage().matchAll(/href="([^"]*)"/g)].map((m) => m[1])
    expect(hrefs).toContain(TUTOR_STUDENTS_PATH)
    for (const href of hrefs) expect(href).toBe(TUTOR_STUDENTS_PATH)
  })

  it("gives two same-day attempts and two same-day trend points distinct React keys", () => {
    // `renderToStaticMarkup` never warns about a repeated key, so the keys are read
    // off the element tree itself: every row of every table the composition draws.
    const tables = rowKeysOfTables(
      StudentDetailView({ student: tutorDetail(), dates: tutorStudentDates, back: null }),
    )
    // Non-vacuity: the trend table and the attempt table, two rows each, all on one day.
    expect(tables.map((keys) => keys.length)).toEqual([2, 2])
    for (const keys of tables) {
      expect(keys.every((key) => typeof key === "string" && key.length > 0)).toBe(true)
      expect(new Set(keys).size, keys.join(" | ")).toBe(keys.length)
    }
  })
})

/** The row keys of each `TBody` under `node`, expanding the one inner component that holds a table. */
function rowKeysOfTables(node: ReactNode): Array<Array<string | null>> {
  const tables: Array<Array<string | null>> = []
  const rowsOf = (children: ReactNode): ReactElement[] => {
    if (Array.isArray(children)) return children.flatMap(rowsOf)
    return isValidElement(children) && children.type === TR ? [children] : []
  }
  const visit = (value: ReactNode): void => {
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (!isValidElement(value)) return
    const element = value as ReactElement<{ children?: ReactNode }>
    if (element.type === TBody) {
      tables.push(rowsOf(element.props.children).map((row) => row.key))
      return
    }
    if (typeof element.type === "function" && element.type.name === "StudentTrendPanel") {
      visit((element.type as (props: unknown) => ReactNode)(element.props))
      return
    }
    visit(element.props.children)
  }
  visit(node)
  return tables
}

describe("the teacher's T-05 page is the page it was before T-20 shared its composition", () => {
  const HEADERS = /<th\b[^>]*>(.*?)<\/th>/g
  const attemptTable = (markup: string) => {
    const from = markup.indexOf("Full attempt history, newest first")
    expect(from, "attempt table caption").toBeGreaterThan(-1)
    return markup.slice(from, markup.indexOf("</table>", from))
  }
  const headersOf = (table: string) => [...table.matchAll(HEADERS)].map((m) => text(m[1]).trim())

  it("keeps the seven teacher-only markers, counted", () => {
    const markup = teacherPage()
    const count = (pattern: RegExp) => markup.match(pattern)?.length ?? 0
    expect(count(/View \/ remark/g), "remark control per attempt").toBe(2)
    expect(count(/Coming soon/g), "two attempt tags and the practice tag").toBe(3)
    expect(count(/Assign practice/g), "assign practice").toBe(1)
    expect(count(/Acknowledged/g), "acknowledged tag on the flag").toBe(1)
    expect(count(/<th[^>]*>\s*<span class="sr-only">Actions<\/span>/g), "Actions column header").toBe(1)
    expect(count(/\bdisabled=""/g), "disabled controls: two remarks and practice").toBe(3)
    expect(count(/aria-disabled="true"/g), "aria-disabled on the same three").toBe(3)
    expect(markup).toContain('aria-label="Attempt history, scrollable horizontally"')
    expect(markup).toMatch(/<button[^>]*type="button"[^>]*>[^<]*(<svg[\s\S]*?<\/svg>)?\s*Back<\/button>/)
  })

  it("keeps the attempt table's column headers and their order", () => {
    expect(headersOf(attemptTable(teacherPage()))).toEqual(["Paper", "Marks", "Percentage", "Grade", "Recorded", "Actions"])
    // The tutor's table is the same table without the last column.
    expect(headersOf(attemptTable(detailPage()))).toEqual(["Paper", "Marks", "Percentage", "Grade", "Recorded"])
  })

  it("keeps the teacher's row cells in the same order as the headers", () => {
    const rows = attemptTable(teacherPage()).split("<tr").slice(2)
    expect(rows.length).toBe(2)
    for (const row of rows) {
      const cells = [...row.matchAll(/<td\b[^>]*>(.*?)<\/td>/g)].map((m) => text(m[1]).trim())
      expect(cells.length).toBe(6)
      expect(cells[0]).toBe("0580 \u00b7 Paper 2 Variant 2")
      expect(cells[1]).toMatch(/^\d+\/90$/)
      expect(cells[2]).toMatch(/^\d+%$/)
      expect(cells[4]).toMatch(RELATIVE_TIME)
      expect(cells[5]).toContain("View / remark")
    }
  })
})

// ── 2 · Dates only ──────────────────────────────────────────────────────────

describe("the tutor sees dates, never times", () => {
  it("draws the day the projection sent, as a calendar date", () => {
    const t = text(detailPage())
    expect(t).toContain("20 Oct 2026")
    expect(t).toContain("active 20 Oct 2026")
  })

  it("has no clock time and no relative time anywhere in the page", () => {
    const t = text(detailPage())
    expect(t).not.toMatch(CLOCK_TIME)
    expect(t).not.toMatch(RELATIVE_TIME)
  })

  it("the same page for the teacher does use relative time (the check can fail)", () => {
    expect(text(teacherPage())).toMatch(RELATIVE_TIME)
  })

  it("dayLabel keeps a day as it is, whatever zone the browser is in", () => {
    expect(dayLabel("2026-10-20")).toBe("20 Oct 2026")
    expect(dayLabel("2026-01-01")).toBe("1 Jan 2026")
    expect(dayLabel("2026-12-31")).toBe("31 Dec 2026")
    expect(dayLabel("2026-10-20", { year: false })).toBe("20 Oct")
  })

  it("dayLabel cuts an instant to its day in the tutor's zone, so a time never gets through", () => {
    // 23:30 UTC on 20 Oct is 02:30 on the 21st in Cairo (UTC+3 until 29 Oct 2026).
    expect(dayLabel("2026-10-20T23:30:00Z")).toBe("21 Oct 2026")
    expect(dayLabel("2026-10-20T08:00:00+03:00", { year: false })).toBe("20 Oct")
  })

  it("dayLabel shows nothing for what it cannot place", () => {
    for (const bad of ["", "soon", "2026-13-40", "2026-02-30", "20 Oct"]) expect(dayLabel(bad), bad).toBe("")
  })

  it("every date formatter yields a day for a day and no time for an instant", () => {
    const inputs = ["2026-10-20", "2026-10-20T23:59:59Z", "2026-03-01T00:00:00+02:00"]
    for (const value of inputs) {
      const out = [
        tutorStudentDates.chartLabel(value),
        tutorStudentDates.tableDate(value),
        tutorStudentDates.recorded(value),
        tutorStudentDates.lastActive(value),
        tutorStudentDates.activeSummary(value),
      ]
      for (const line of out) {
        expect(line, `${value} -> ${line}`).not.toMatch(CLOCK_TIME)
        expect(line, `${value} -> ${line}`).not.toMatch(RELATIVE_TIME)
        expect(line, value).toMatch(/\d{1,2} [A-Z][a-z]{2}/)
      }
    }
  })

  it("says plainly when there is no activity", () => {
    expect(tutorStudentDates.activeSummary(null)).toBe("never active")
    expect(tutorStudentDates.lastActive(null)).toBe("Never")
  })

  it("shows a dash, not 'Never', when the projection could not place the last activity", () => {
    // The projection sends "" for an instant it cannot put on a day; the student was active.
    for (const unplaced of ["", "soon", "2026-02-30"]) {
      expect(tutorStudentDates.lastActive(unplaced), unplaced).toBe("\u2014")
      expect(tutorStudentDates.activeSummary(unplaced), unplaced).not.toMatch(/never/i)
      expect(tutorStudentDates.activeSummary(unplaced), unplaced).toContain("\u2014")
    }
    harness.student = success(
      dto(tutorDetail({ engagement: { totalPapers: 3, lastActiveAt: "", daysSinceLastSubmission: null } })),
    )
    const t = text(detailPage())
    expect(t).not.toMatch(/never/i)
    expect(t).toMatch(/Last active \u2014/)
  })

  it("a day in a non-Cairo zone is cut in that zone, not Cairo's", () => {
    // 22:30 UTC on 8 Jan is 00:30 on the 9th in Cairo and 14:30 on the 8th in Los Angeles.
    const instant = "2026-01-08T22:30:00Z"
    expect(dayLabel(instant)).toBe("9 Jan 2026")
    expect(dayLabel(instant, { zone: "America/Los_Angeles" })).toBe("8 Jan 2026")
    expect(dayLabel(instant, { zone: "America/Los_Angeles", year: false })).toBe("8 Jan")
    expect(tutorStudentDatesIn("America/Los_Angeles").tableDate(instant)).toBe("8 Jan 2026")
    expect(tutorStudentDatesIn("America/Los_Angeles").lastActive(instant)).toBe("8 Jan 2026")
    expect(tutorStudentDates.tableDate(instant)).toBe("9 Jan 2026")
  })

  it("the page cuts every date it draws in the profile's zone", () => {
    // If an instant ever arrives it is cut where the tutor is: 23:30 UTC on the 20th is the 20th in Los Angeles.
    const base = tutorDetail()
    const instant = "2026-10-20T23:30:00Z"
    harness.student = success(
      dto(
        tutorDetail({
          attempts: base.attempts.map((a) => ({ ...a, recordedAt: instant })),
          trend: base.trend.map((p) => ({ ...p, recordedAt: instant })),
          engagement: { ...base.engagement, lastActiveAt: instant },
        }),
      ),
    )
    harness.profile = success({ zone: "America/Los_Angeles", zoneLabel: "Los Angeles time" })
    const inLosAngeles = text(detailPage())
    expect(inLosAngeles).toContain("active 20 Oct 2026")
    expect(inLosAngeles).not.toContain("21 Oct")
    harness.profile = success({ zone: "Africa/Cairo", zoneLabel: "Cairo time" })
    const inCairo = text(detailPage())
    expect(inCairo).toContain("active 21 Oct 2026")
    expect(inCairo).not.toContain("20 Oct")
  })

  it("the sharing line is cut in the tutor's zone like every other date on the page", () => {
    const instant = "2026-01-08T22:30:00Z"
    expect(sharedLine("Maya R.", instant, "America/Los_Angeles")).toContain("on 8 Jan 2026.")
    expect(sharedLine("Maya R.", instant)).toContain("on 9 Jan 2026.")
    harness.student = success({ ...dto(), grantedAt: instant })
    harness.profile = success({ zone: "America/Los_Angeles", zoneLabel: "Los Angeles time" })
    expect(text(detailPage())).toContain("on 8 Jan 2026.")
    // Until the tutor's profile is known (or if it never loads) the v1 zone is used: the page still reads.
    harness.profile = pending()
    expect(text(detailPage())).toContain("on 9 Jan 2026.")
    harness.profile = failure(new ApiError(500, "500"))
    expect(text(detailPage())).toContain("on 9 Jan 2026.")
  })

  it("the sharing date comes from the grant, as a date", () => {
    expect(sharedLine("Maya R.", GRANTED_AT)).toBe(
      SPEC_SHARED.replace("{Name}", "Maya R.").replace("{date}", "8 Jan 2026"),
    )
    expect(text(detailPage())).toContain(sharedLine("Maya R.", GRANTED_AT))
  })

  it("the list says 'since' with a date and no time", () => {
    const row = studentRowView(item())
    expect(row.sinceLine).toBe("Sharing since 8 Jan 2026")
    expect(text(listPage())).not.toMatch(CLOCK_TIME)
  })

  it("the grant's day as the API sends it is kept as it is, whatever the tutor's zone", () => {
    // The server already cut it in the tutor's zone; a second cut here would move it a day.
    for (const zone of ["Africa/Cairo", "America/Los_Angeles", "Pacific/Kiritimati", "Etc/GMT+12"]) {
      expect(sharedLine("Maya R.", "2026-01-08", zone), zone).toContain("on 8 Jan 2026.")
      expect(sharedLine("Maya R.", "2026-12-31", zone), zone).toContain("on 31 Dec 2026.")
    }
    expect(studentRowView(item({ grantedAt: "2026-12-31" })).sinceLine).toBe("Sharing since 31 Dec 2026")
    harness.student = success({ ...dto(), grantedAt: "2026-12-31" })
    harness.profile = success({ zone: "America/Los_Angeles", zoneLabel: "Los Angeles time" })
    const page = text(detailPage())
    expect(page).toContain("on 31 Dec 2026.")
    expect(page).not.toMatch(CLOCK_TIME)
  })
})

// ── 3 · One access_ended state ──────────────────────────────────────────────

describe("access_ended is one generic state", () => {
  const REASONS = /revok|expire|block|suspend|clos|stopped|ended|banned|removed|report/i

  it("draws the SPEC sentence with the name, and nothing of the student", () => {
    harness.student = failure(accessEnded())
    const t = text(detailPage({ studentName: "Maya R." }))
    expect(t).toContain(SPEC_ENDED.replace("{Name}", "Maya R."))
    expect(accessEndedHeading("Maya R.")).toBe(SPEC_ENDED.replace("{Name}", "Maya R."))
    for (const private_ of ["Algebra", "0580", "Attempt history", "20 Oct", "Performance over time"]) {
      expect(t, private_).not.toContain(private_)
    }
  })

  it("falls back to 'This student' when no name came with the link", () => {
    harness.student = failure(accessEnded())
    const t = text(detailPage())
    expect(t).toContain(SPEC_ENDED.replace("{Name}", "This student"))
    expect(accessEndedHeading(null)).toBe(SPEC_ENDED.replace("{Name}", "This student"))
  })

  it("is the same page whatever reason or message the server attached", () => {
    const variants = [
      accessEnded("403 Forbidden"),
      accessEnded("grant revoked", { reason: "revoked" }),
      accessEnded("grant expired", { reason: "expired" }),
      accessEnded("student blocked you", { reason: "blocked" }),
      accessEnded("tutor suspended", { reason: "suspended", message: "closed" }),
    ]
    const pages = variants.map((error) => {
      harness.student = failure(error)
      return detailPage({ studentName: "Maya R." })
    })
    expect(new Set(pages).size).toBe(1)
    expect(variants.length).toBe(5)
  })

  it("never names a reason", () => {
    harness.student = failure(accessEnded("blocked"))
    const t = text(detailPage({ studentName: "Maya R." }))
    // "no longer shared" is the one allowed phrase; take it out and look for any reason word.
    expect(t.replace(/no longer shared/g, "")).not.toMatch(REASONS)
    expect(accessEndedHeading(null).replace(/no longer shared/g, "")).not.toMatch(REASONS)
  })

  it("offers no retry and no refetch: asking again would be another audited read", () => {
    const query = failure(accessEnded())
    harness.student = query
    const markup = detailPage()
    expect(markup).not.toMatch(/<button\b/)
    expect(text(markup)).not.toMatch(/try again|retry|reload/i)
    expect(query.refetch).not.toHaveBeenCalled()
    expect(markup).toContain(`href="${TUTOR_STUDENTS_PATH}"`)
  })

  it("only a 403 with the access_ended code is this state", () => {
    harness.student = failure(new ApiError(409, "409", { code: "access_ended" }))
    expect(text(detailPage())).not.toContain("no longer shared")
    harness.student = failure(new ApiError(403, "403", { code: "email_unverified" }))
    expect(text(detailPage())).not.toContain("no longer shared")
  })

  it("a 404 is 'not found', a different page, not the ended one", () => {
    harness.student = failure(new ApiError(404, "404", { code: "not_found" }))
    const t = text(detailPage())
    expect(t).toContain("We couldn't find that student")
    expect(t).not.toContain("no longer shared")
    expect(t).not.toMatch(/try again/i)
  })

  it("only the API's not_found (or a malformed id) is 'not found'; any other 404 is a failure", () => {
    expect(isStudentNotFound(new ApiError(404, "404", { code: "not_found" }))).toBe(true)
    // FastAPI's validation list for an :studentId that is not a UUID.
    expect(isStudentNotFound(new ApiError(422, "422", [{ loc: ["path", "student_id"], msg: "bad uuid" }]))).toBe(true)
    expect(isStudentNotFound(new ApiError(404, "404", { code: "no_tutor_profile" }))).toBe(false)
    expect(isStudentNotFound(new ApiError(404, "404"))).toBe(false)
    expect(isStudentNotFound(new ApiError(403, "403", { code: "not_found" }))).toBe(false)
    expect(isStudentNotFound(new ApiError(500, "500"))).toBe(false)
    expect(isStudentNotFound(new Error("boom"))).toBe(false)

    // Not "not found": no tutor profile gets its own onboarding state (below), never "no such student".
    harness.student = failure(new ApiError(404, "404", { code: "no_tutor_profile" }))
    expect(text(detailPage())).not.toContain("We couldn't find that student")

    harness.student = failure(new ApiError(422, "422", [{ loc: ["path", "student_id"], msg: "bad uuid" }]))
    const badId = text(detailPage())
    expect(badId).toContain("We couldn't find that student")
    expect(badId).not.toMatch(/try again/i)
  })

  it("studentNameFromState reads only a plain, non-empty string", () => {
    expect(studentNameFromState({ studentName: "Maya R." })).toBe("Maya R.")
    for (const bad of [null, undefined, "Maya", {}, { studentName: "" }, { studentName: 4 }, { studentName: "x".repeat(200) }]) {
      expect(studentNameFromState(bad), String(bad)).toBeNull()
    }
  })
})

describe("T-20 has one title", () => {
  it("is 'Student progress' in the route title, the hidden h1 of every state and the crumb is 'This student'", () => {
    expect(TUTOR_STUDENT_TITLE).toBe("Student progress")
    expect(TUTOR_STUDENT_CRUMB).toBe("This student")
    const h1 = new RegExp(`<h1[^>]*class="sr-only"[^>]*>${TUTOR_STUDENT_TITLE}</h1>`)
    const states: Array<[string, unknown]> = [
      ["pending", pending()],
      ["access ended", failure(accessEnded())],
      ["not found", failure(new ApiError(404, "404", { code: "not_found" }))],
      ["server failure", failure(new ApiError(500, "500"))],
    ]
    for (const [name, query] of states) {
      harness.student = query
      const markup = detailPage()
      expect(markup, name).toMatch(h1)
      expect(markup, name).not.toContain("Student detail")
    }
  })
})

describe("the other T-20 states", () => {
  it("shows a skeleton while loading, with a heading for screen readers", () => {
    harness.student = pending()
    const markup = detailPage()
    expect(markup).toContain('aria-label="Loading"')
    expect(markup).toMatch(new RegExp(`<h1[^>]*>${TUTOR_STUDENT_TITLE}</h1>`))
    expect(text(markup)).not.toContain("Maya R.")
  })

  it("shows the C-11 error with a retry for a server failure", () => {
    harness.student = failure(new ApiError(500, "500"))
    const t = text(detailPage())
    expect(t).toContain("We couldn't load this student")
    expect(t).toContain("Try again")
    expect(t).not.toContain("no longer shared")
  })

  it("shows the offline state, not a failure, when the connection is down", () => {
    harness.student = failure(new ApiError(0, "Failed to fetch"))
    const t = text(detailPage())
    expect(t).toMatch(/offline|not connected|connection/i)
  })

  it("asks for the student in the address, once", () => {
    detailPage()
    expect(harness.studentCalls).toEqual(["s1"])
  })

  it("explains a student with no papers without inventing a line", () => {
    harness.student = success(
      dto(tutorDetail({ attempts: [], trend: [], weaknesses: [], subjects: [], atRiskFlags: [], isAtRisk: false,
        engagement: { totalPapers: 0, lastActiveAt: null, daysSinceLastSubmission: null } })),
    )
    const t = text(detailPage())
    expect(t).toContain("No papers recorded yet.")
    expect(t).toContain("never active")
    expect(t).toContain("Not currently flagged")
  })
})

// ── 4 · T-19 ────────────────────────────────────────────────────────────────

/*
 * A teacher with no tutor profile (the API's 404 `no_tutor_profile`) is not a
 * failure: they have not started tutoring. T-19 and T-20 say so in one honest
 * sentence and link to T-16. Only that code does this; every other error keeps
 * the C-11 failure state.
 */
describe("no tutor profile yet", () => {
  const noProfile = () => new ApiError(404, "404", { code: "no_tutor_profile" })
  const COPY_PAGES: Array<[string, () => string, string]> = [
    ["T-19", listPage, "list"],
    ["T-20", detailPage, "student"],
  ]

  it("isNoTutorProfile is only the 404 with that code", () => {
    expect(isNoTutorProfile(noProfile())).toBe(true)
    expect(isNoTutorProfile(new ApiError(404, "404", { code: "not_found" }))).toBe(false)
    expect(isNoTutorProfile(new ApiError(404, "404"))).toBe(false)
    expect(isNoTutorProfile(new ApiError(403, "403", { code: "no_tutor_profile" }))).toBe(false)
    expect(isNoTutorProfile(new ApiError(500, "500", { code: "no_tutor_profile" }))).toBe(false)
    expect(isNoTutorProfile(new Error("no_tutor_profile"))).toBe(false)
    expect(isNoTutorProfile(null)).toBe(false)
  })

  it("its copy is plain: no em dash, no exclamation mark, links to T-16", () => {
    expect(TUTOR_PROFILE_PATH).toBe("/teacher/tutoring/profile")
    for (const line of [NO_TUTOR_PROFILE_HEADING, NO_TUTOR_PROFILE_BODY, NO_TUTOR_PROFILE_ACTION]) {
      expect(line.length).toBeGreaterThan(5)
      expect(line).not.toMatch(/[\u2014\u2013!]/)
    }
  })

  for (const [screen, page, key] of COPY_PAGES) {
    it(`${screen} shows the onboarding state with a link to the profile, not the error`, () => {
      harness[key as "list" | "student"] = failure(noProfile())
      const markup = page()
      const t = text(markup)
      expect(t).toContain(NO_TUTOR_PROFILE_HEADING)
      expect(t).toContain(NO_TUTOR_PROFILE_BODY)
      expect(t).not.toContain("You don't have a tutor profile yet.")
      expect(t).not.toMatch(/We couldn't load|Try again|offline/i)
      expect(markup).toContain(`href="${TUTOR_PROFILE_PATH}"`)
      expect(t).toContain(NO_TUTOR_PROFILE_ACTION)
      expect(markup.match(/<h1\b/g)?.length).toBe(1)
    })

    it(`${screen} keeps the failure state for every other error`, () => {
      for (const error of [
        new ApiError(500, "500"),
        new ApiError(404, "404", { code: "not_found" }),
        new ApiError(403, "403", { code: "no_tutor_profile" }),
        new ApiError(0, "Failed to fetch"),
      ]) {
        harness[key as "list" | "student"] = failure(error)
        const markup = page()
        expect(text(markup), String(error.status)).not.toContain(NO_TUTOR_PROFILE_ACTION)
        // A 404 not_found is T-20's own "not found" page, which has no retry; the rest are failures.
        if (error.status !== 404) expect(text(markup), String(error.status)).toMatch(/Try again/)
        expect(markup, String(error.status)).not.toContain(`href="${TUTOR_PROFILE_PATH}"`)
      }
    })
  }
})

describe("T-19 My students", () => {
  it("uses the SPEC's sentences", () => {
    expect(MY_STUDENTS_INTRO).toBe(SPEC_INTRO)
    expect(NO_STUDENTS_LINE).toBe(SPEC_EMPTY)
  })

  it("lists each student with name, sharing since and upcoming sessions, linked to T-20", () => {
    harness.list = success({
      items: [item(), item({ studentId: "s2", grantId: "g2", displayName: "Omar K.", upcomingSessions: 0 }),
        item({ studentId: "s3", grantId: "g3", displayName: "Lina S.", upcomingSessions: 1 })],
      nextCursor: null,
    })
    const markup = listPage()
    const t = text(markup)
    expect(t).toContain(SPEC_INTRO)
    for (const name of ["Maya R.", "Omar K.", "Lina S."]) expect(t).toContain(name)
    expect(t).toContain("Sharing since 8 Jan 2026")
    expect(t).toContain("2 upcoming sessions")
    expect(t).toContain("1 upcoming session")
    expect(t).toContain("No upcoming sessions")
    expect(markup).toContain(`href="${tutorStudentPath("s2")}"`)
    expect(markup).toContain('<h1')
  })

  it("rows carry no analytics: no grade, no percentage, no flag", () => {
    const t = text(listPage())
    expect(t).not.toMatch(/\d+%|at risk|grade|predicted|weak/i)
  })

  it("builds each row's link from the id, encoded, and labels it with the name and both facts", () => {
    const row = studentRowView(item({ studentId: "a b/c" }))
    expect(row.href).toBe("/teacher/tutoring/students/a%20b%2Fc")
    expect(row.name).toBe("Maya R.")
    expect(row.ariaLabel).toContain("Maya R.")
    expect(row.ariaLabel).toContain("2 upcoming sessions")
  })

  it("shows the empty state with the SPEC line", () => {
    harness.list = success({ items: [], nextCursor: null })
    const t = text(listPage())
    expect(t).toContain(SPEC_EMPTY)
    expect(t).toContain(SPEC_INTRO)
  })

  it("shows a skeleton, an error with retry, and an offline state", () => {
    harness.list = pending()
    expect(listPage()).toContain('aria-label="Loading"')
    harness.list = failure(new ApiError(500, "500"))
    expect(text(listPage())).toContain("We couldn't load your students")
    expect(text(listPage())).toContain("Try again")
    harness.list = failure(new ApiError(0, "Failed to fetch"))
    expect(text(listPage())).toMatch(/offline|not connected|connection/i)
  })

  it("offers 'Show more students' only when there is a next page", () => {
    harness.list = success({ items: [item()], nextCursor: "abc" })
    expect(text(listPage())).toContain("Show more students")
    harness.list = success({ items: [item()], nextCursor: null })
    expect(text(listPage())).not.toContain("Show more students")
  })

  it("asks for the first page with no cursor", () => {
    listPage()
    expect(harness.listCalls[0]).toEqual({ cursor: null })
  })

  it("links back to Tutoring", () => {
    expect(listPage()).toContain('href="/teacher/tutoring"')
  })

  it("explains a failure with the API's own sentence when it sent one", () => {
    expect(studentLoadFailureMessage(new ApiError(429, "429", { code: "too_many_requests" }))).toBe(
      "That is happening too often. Try again in a little while.",
    )
    expect(studentLoadFailureMessage(new Error("boom"))).not.toContain("boom")
  })
})

// ── 5 · The source ──────────────────────────────────────────────────────────

const read = (path: string) => stripComments(readFileSync(join(WEB, path), "utf8"))
const LIB = "src/lib/tutoring/tutorStudentView.ts"
const DETAIL_SCREEN = "src/portals/teacher/screens/tutoring/TutorStudentDetail.tsx"
const LIST_SCREEN = "src/portals/teacher/screens/tutoring/MyStudents.tsx"

describe("the source of the tutor's screens", () => {
  const sources: Record<string, string> = {
    [LIB]: read(LIB),
    [DETAIL_SCREEN]: read(DETAIL_SCREEN),
    [LIST_SCREEN]: read(LIST_SCREEN),
  }

  it("scans the three files it names (non-vacuity)", () => {
    expect(Object.keys(sources).length).toBe(3)
    for (const [file, source] of Object.entries(sources)) expect(source.length, file).toBeGreaterThan(500)
  })

  it("never formats a time or a relative time", () => {
    for (const [file, source] of Object.entries(sources)) {
      expect(source, file).not.toMatch(/relativeTime|toLocaleTimeString|toLocaleString\(|getHours|getMinutes|hour12|timeStyle|hour:/)
    }
  })

  it("T-20 passes no attempt action and no footer to the shared composition, and hides the tag", () => {
    const screen = sources[DETAIL_SCREEN]
    expect(screen).toContain("<StudentDetailView")
    expect(screen).not.toMatch(/attemptAction|footer\s*=/)
    expect(screen).toMatch(/showAcknowledged=\{false\}/)
  })

  it("T-20 reads only the tutor route, never the teacher's", () => {
    const screen = sources[DETAIL_SCREEN]
    expect(screen).toContain("useTutorStudent(")
    expect(screen).not.toMatch(/useTeacherApi|useStudentDetail|useAtRisk|useAcknowledge/)
  })

  it("T-20 leaves clearing the cache to the access_ended guard", () => {
    // A second remover would rebuild the query on the next render and fetch it again: a loop of audited reads.
    const screen = sources[DETAIL_SCREEN]
    expect(screen).not.toMatch(/removeQueries|resetQueries|invalidateQueries|setQueryData|useQueryClient|refetch\(/)
    expect(screen).not.toMatch(/useEffect/)
  })

  it("both screens put a title in an h1 and use no raw colour", () => {
    for (const file of [DETAIL_SCREEN, LIST_SCREEN]) {
      expect(sources[file], file).toContain("<h1")
      expect(sources[file], file).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(/)
    }
  })
})
