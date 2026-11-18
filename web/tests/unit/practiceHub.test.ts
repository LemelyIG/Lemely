import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { PracticeRun, StudentQuizListItem } from "@/lib/practiceHubTypes"
import type { PracticeTopics } from "@/lib/practiceTypes"
import type { HubInput } from "@/portals/student/screens/practice/hub/hubModel"

// The screen is thin: it renders practiceHubView(input). These tests drive it
// through the data hook (mocked) and the breakpoint hook, one frame per state.
const hub = vi.hoisted(() => ({
  input: null as unknown as HubInput,
  refetching: false,
  wide: false,
}))

vi.mock("@/portals/student/screens/practice/hub/usePracticeHubData", () => ({
  usePracticeHubData: () => ({
    input: hub.input,
    builderSubjects: hub.input.subjects.map(({ code, name }) => ({ code, name })),
    refetchAll: () => {},
    refetching: hub.refetching,
  }),
}))
vi.mock("@/portals/student/screens/practice/hub/useWide", () => ({ useWide: () => hub.wide }))

const { PracticeHub } = await import("@/portals/student/screens/practice/PracticeHub")

const NOW = new Date(2026, 10, 15, 12, 0)
const iso = (y: number, m: number, d: number) => new Date(y, m, d, 9).toISOString()

function topics(code: string, rows: [string, number][]): PracticeTopics {
  return {
    subjectCode: code,
    topics: rows.map(([topic, marksLost]) => ({ topic, availableCount: 10, syllabusGroup: topic, marksLost })),
    weakTopics: rows.filter(([, lost]) => lost > 0).map(([t]) => t),
    untopicedCount: 0,
  }
}

function run(over: Partial<PracticeRun>): PracticeRun {
  return {
    assignmentId: "a1",
    subjectCode: "0580",
    title: "Mathematics Practice Set",
    topics: ["Vectors"],
    status: "marked",
    questionCount: 9,
    answeredCount: 9,
    awardedMarks: 7,
    maximumMarks: 9,
    timeLimitMinutes: null,
    lastActivityAt: iso(2026, 10, 10),
    ...over,
  }
}

const HOMEWORK: StudentQuizListItem = {
  assignmentId: "h1",
  quizTitle: "Vectors set",
  subjectCode: "0580",
  className: "10B",
  teacherName: "Ms Adel",
  assignedAt: iso(2026, 10, 12),
  dueAt: iso(2026, 10, 20),
  closesAt: null,
  questionCount: 8,
  timeLimitMinutes: null,
  submissionStatus: "not_started",
  isOpen: true,
  isOverdue: false,
}

function input(over: Partial<HubInput> = {}): HubInput {
  return {
    overviewStatus: "success",
    subjects: [
      { code: "0580", name: "Maths", papers: 3 },
      { code: "0625", name: "Physics", papers: 2 },
    ],
    topics: [
      { code: "0580", status: "success", data: topics("0580", [["Vectors", 9], ["2.1 Quadratic inequalities", 6]]) },
      { code: "0625", status: "success", data: topics("0625", [["3 Waves", 1]]) },
    ],
    runsStatus: "success",
    runs: [run({}), run({ assignmentId: "a2", status: "in_progress", answeredCount: 3, lastActivityAt: iso(2026, 10, 14) })],
    homework: [],
    dueTotal: 26,
    deckCount: 4,
    placement: [
      { code: "0580", available: false, minutes: null },
      { code: "0625", available: true, minutes: 10 },
    ],
    now: NOW,
    ...over,
  }
}

const render = () => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(PracticeHub)))
const count = (haystack: string, needle: string) => haystack.split(needle).length - 1

beforeEach(() => {
  hub.input = input()
  hub.refetching = false
  hub.wide = false
})

describe("PracticeHub", () => {
  it("one page heading, always", () => {
    const out = render()
    expect(count(out, "<h1")).toBe(1)
    expect(out).toMatch(/<h1[^>]*>Practice<\/h1>/)
  })

  it("loading (CL): a busy skeleton and nothing that depends on data", () => {
    hub.input = input({ runsStatus: "pending" })
    const out = render()
    expect(out).toContain('aria-busy="true"')
    expect(out).not.toContain("Ways to practise")
    expect(out).not.toContain("rd-say")
  })

  it("normal (CN): subtitle, four tiles, Binny once after the tiles on a phone, both lists", () => {
    const out = render()
    expect(out).toContain("3 topics to win back")
    expect(count(out, 'class="rd-tile"')).toBe(4)
    expect(count(out, "rd-say")).toBe(1)
    expect(out.indexOf("rd-say")).toBeGreaterThan(out.indexOf("Ways to practise"))
    expect(out).toContain("Vectors first. +9 marks.")
    expect(out).toContain("Win marks back")
    expect(out).toContain('aria-label="Recent"')
  })

  it("desktop (CDK): Binny moves above the tiles and still mounts once", () => {
    hub.wide = true
    const out = render()
    expect(count(out, "rd-say")).toBe(1)
    expect(out.indexOf("rd-say")).toBeLessThan(out.indexOf("Ways to practise"))
  })

  it("pages are links; the builder (a sheet) opens from buttons", () => {
    const out = render()
    expect(out).toMatch(/<a class="rd-tile" data-tone="violet"[^>]*href="\/student\/flashcards"/)
    expect(out).toMatch(/<a class="rd-tile" data-tone="mint"[^>]*href="\/student\/practice\/papers"/)
    expect(out).toMatch(/<button type="button" class="rd-tile" data-tone="tide"/)
    expect(out).toContain('href="/student/practice/set/a2"')
  })

  it("the due count is set in Mono", () => {
    expect(render()).toMatch(/<b class="font-mono[^"]*">26<\/b> due today/)
  })

  it("a single mark reads singular in the win-back row", () => {
    const out = render()
    expect(out).toMatch(/\+1<small[^>]*>mark<\/small>/)
    expect(out).toMatch(/\+9<small[^>]*>marks<\/small>/)
  })

  it("homework sits on top as the one tinted row, when set", () => {
    hub.input = input({ homework: [HOMEWORK] })
    const out = render()
    expect(out).toContain("Homework · Vectors set")
    expect(out.indexOf("Homework · Vectors set")).toBeLessThan(out.indexOf("Ways to practise"))
  })

  it("recent: See all is a disclosure when there are more than four", () => {
    hub.input = input({ runs: Array.from({ length: 6 }, (_, i) => run({ assignmentId: `r${i}`, lastActivityAt: iso(2026, 10, 14 - i) })) })
    const out = render()
    expect(out).toMatch(/<button type="button" class="rd-lnk" aria-expanded="false"[^>]*>See all<\/button>/)
  })

  it("error (CE): the tiles still work, an alert explains and offers a retry", () => {
    hub.input = input({ runsStatus: "error" })
    const out = render()
    expect(count(out, 'class="rd-tile"')).toBe(4)
    expect(out).toContain('role="alert"')
    expect(out).toContain("We couldn’t load your topics")
    expect(out).toMatch(/<button[^>]*>.*Try again.*<\/button>/s)
    expect(out).not.toContain("Win marks back")
  })

  it("error retrying: the button shows it is working", () => {
    hub.input = input({ runsStatus: "error" })
    hub.refetching = true
    expect(render()).toMatch(/<button[^>]*disabled=""[^>]*>[\s\S]*Try again/)
  })

  it("first run (CZ): walkthrough, Binny open once, a scan call to action, no lists", () => {
    hub.input = input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], topics: [], runs: [] })
    const out = render()
    expect(count(out, "rd-say")).toBe(1)
    expect(out).toContain("Scan a paper and I&#x27;ll find your marks to win back.")
    expect(out).toContain('class="rd-walk"')
    expect(out).toContain("Scan a marked paper")
    expect(out).toMatch(/<a [^>]*href="\/student\/correct"[^>]*>Scan a paper<\/a>/)
    expect(out).not.toContain("Win marks back")
    expect(out).not.toContain('aria-label="Recent"')
  })

  it("sparse (CS): one paper, no All topics link, the scan tip", () => {
    hub.input = input({
      subjects: [{ code: "0580", name: "Maths", papers: 1 }],
      topics: [{ code: "0580", status: "success", data: topics("0580", [["Vectors", 9]]) }],
      runs: [],
    })
    const out = render()
    expect(out).toContain("Good start. Try one set.")
    expect(out).toContain("More papers, sharper picks")
    expect(out).toMatch(/<a [^>]*href="\/student\/correct"[^>]*>Scan<\/a>/)
    expect(out).not.toContain("All topics")
  })

  it("sets done, no paper yet: the scan tip without an empty win-back heading", () => {
    hub.input = input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], topics: [{ code: "0580", status: "success", data: topics("0580", []) }] })
    const out = render()
    expect(out).toContain("Scan a paper next.")
    expect(out).toContain("More papers, sharper picks")
    expect(out).not.toContain("Win marks back")
  })
})
