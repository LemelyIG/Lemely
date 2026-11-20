import { readFileSync } from "node:fs"
import { QueryClient, QueryObserver } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"
import type { PracticeRun, StudentQuizListItem } from "@/lib/practiceHubTypes"
import type { PracticeTopics } from "@/lib/practiceTypes"
import {
  dayLabel,
  dueLabel,
  hubState,
  hubTiles,
  pickHomework,
  practiceHubView,
  profileQueryState,
  recentRows,
  winBackRows,
  type HubInput,
} from "@/portals/student/screens/practice/hub/hubModel"

// Local-time constructors keep every assertion independent of the runner's TZ.
const NOW = new Date(2026, 10, 15, 12, 0) // Sun 15 Nov 2026
const iso = (y: number, m: number, d: number, h = 9) => new Date(y, m, d, h).toISOString()

const SUBJECTS = [
  { code: "0580", name: "Maths", papers: 3 },
  { code: "0625", name: "Physics", papers: 2 },
]

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

function homework(over: Partial<StudentQuizListItem>): StudentQuizListItem {
  return {
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
    ...over,
  }
}

function input(over: Partial<HubInput> = {}): HubInput {
  return {
    overviewStatus: "success",
    profileStatus: "success",
    subjects: SUBJECTS,
    topics: [
      { code: "0580", status: "success", data: topics("0580", [["Vectors", 9], ["Algebra", 0], ["2.1 Quadratic inequalities", 6]]) },
      { code: "0625", status: "success", data: topics("0625", [["3 Waves", 6]]) },
    ],
    runsStatus: "success",
    runs: [run({})],
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

describe("dayLabel / dueLabel", () => {
  it("names today, yesterday, this week by weekday, and older by date", () => {
    expect(dayLabel(iso(2026, 10, 15), NOW)).toBe("Today")
    expect(dayLabel(iso(2026, 10, 14), NOW)).toBe("Yesterday")
    expect(dayLabel(iso(2026, 10, 10), NOW)).toBe("Tue")
    expect(dayLabel(iso(2026, 10, 2), NOW)).toBe("2 Nov")
  })

  it("says overdue first, then today, tomorrow, weekday, date", () => {
    expect(dueLabel({ dueAt: iso(2026, 10, 10), isOverdue: true }, NOW)).toBe("overdue")
    expect(dueLabel({ dueAt: null, isOverdue: false }, NOW)).toBeNull()
    expect(dueLabel({ dueAt: iso(2026, 10, 15, 18), isOverdue: false }, NOW)).toBe("due today")
    expect(dueLabel({ dueAt: iso(2026, 10, 16), isOverdue: false }, NOW)).toBe("due tomorrow")
    expect(dueLabel({ dueAt: iso(2026, 10, 20), isOverdue: false }, NOW)).toBe("due Friday")
    expect(dueLabel({ dueAt: iso(2026, 11, 1), isOverdue: false }, NOW)).toBe("due 1 Dec")
  })
})

describe("hubState", () => {
  it.each([true, false])("retains the profile failure through a real retry (subjects known: %s)", async (known) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let resolveRetry!: (value: { enrolments: never[] }) => void
    let attempt = 0
    const observer = new QueryObserver(client, {
      queryKey: ["profile"],
      queryFn: () => ++attempt === 1
        ? Promise.reject(new Error("offline"))
        : new Promise<{ enrolments: never[] }>((resolve) => { resolveRetry = resolve }),
      enabled: false,
    })
    const unsubscribe = observer.subscribe(() => {})
    const model = () => practiceHubView(input({
      profileStatus: profileQueryState(observer.getCurrentResult()).profileStatus,
      ...(known ? {} : { subjects: [], topics: [], placement: [], runs: [] }),
    }))
    expect(model().state).toBe("loading")
    await observer.refetch()
    expect(profileQueryState(observer.getCurrentResult()).profileStatus).toBe("error")
    expect(model().notice ?? model().errorKind).toBe("subjects")
    const retry = observer.refetch()
    // TanStack drops an uncached query back to pending while retrying; the
    // hook's `refetching` (isFetching) is busy and the mapped status stays error.
    expect(observer.getCurrentResult().status).toBe("pending")
    expect(profileQueryState(observer.getCurrentResult()).refetching).toBe(true)
    expect(profileQueryState(observer.getCurrentResult()).profileStatus).toBe("error")
    expect(model().notice ?? model().errorKind).toBe("subjects")
    resolveRetry({ enrolments: [] })
    await retry
    expect(profileQueryState(observer.getCurrentResult()).refetching).toBe(false)
    expect(profileQueryState(observer.getCurrentResult()).profileStatus).toBe("success")
    expect(model().notice).toBeNull()
    expect(model().errorKind).toBeNull()
    unsubscribe()
    client.clear()
  })

  it("first load without any prior failure is still pending", () => {
    expect(profileQueryState({ data: undefined, status: "pending", errorUpdateCount: 0, isFetching: true }).profileStatus).toBe("pending")
  })

  it("usePracticeHubData uses the mapped profile status and busy state", () => {
    const hook = readFileSync(new URL("../../src/portals/student/screens/practice/hub/usePracticeHubData.ts", import.meta.url), "utf8")
    expect(hook).toMatch(/const profileState = profileQueryState\(profile\)/)
    expect(hook).toMatch(/profileStatus:\s*profileState\.profileStatus/)
    expect(hook).toMatch(/refetching:.*profileState\.refetching/)
  })

  it("keeps cached topics visible after a real failed refetch", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const cached = topics("0580", [["Vectors", 9]])
    let fail = false
    const observer = new QueryObserver(client, {
      queryKey: ["topics", "0580"],
      queryFn: async () => {
        if (fail) throw new Error("offline")
        return cached
      },
    })
    const unsubscribe = observer.subscribe(() => {})
    await observer.refetch()
    fail = true
    const result = await observer.refetch()
    expect(result.status).toBe("error")
    expect(result.data).toEqual(cached)
    const view = practiceHubView(input({ topics: [{ code: "0580", status: result.status, data: result.data }] }))
    expect(view.state).toBe("normal")
    expect(view.winBack.map((row) => row.label)).toEqual(["Vectors"])
    unsubscribe()
    client.clear()
  })

  it("waits for the profile before deciding anything", () => {
    expect(hubState(input({ profileStatus: "pending" }))).toBe("loading")
  })

  it("a failed profile does not block the hub while the overview already gave subjects", () => {
    const view = practiceHubView(input({ profileStatus: "error" }))
    expect(view.state).toBe("normal")
    expect(view.errorKind).toBeNull()
    expect(view.notice).toBe("subjects")
    expect(view.winBack.map((row) => row.label)).toEqual(["Vectors", "Quadratic inequalities", "Waves"])
    expect(view.recent).toHaveLength(1)
    expect(view.tiles[0].disabled).toBe(false)
  })

  it("a failed profile with no usable subject is its own error, never a false first run", () => {
    const view = practiceHubView(input({ profileStatus: "error", subjects: [], topics: [], placement: [], runs: [] }))
    expect(view.state).toBe("error")
    expect(view.errorKind).toBe("subjects")
    expect(view.notice).toBeNull()
    expect(view.binny).toBeNull()
    expect(view.showScanTip).toBe(false)
  })

  it("a failed profile with no subject still lists runs that already loaded", () => {
    const view = practiceHubView(input({ profileStatus: "error", subjects: [], topics: [], placement: [] }))
    expect(view.errorKind).toBe("subjects")
    expect(view.recent).toHaveLength(1)
  })

  it("a failed topics source is the topics error, even if the profile failed too", () => {
    expect(practiceHubView(input({ runsStatus: "error" })).errorKind).toBe("topics")
    expect(practiceHubView(input({ runsStatus: "error", profileStatus: "error" })).errorKind).toBe("topics")
  })

  it("no error kind or notice when everything loaded", () => {
    const view = practiceHubView(input())
    expect(view.errorKind).toBeNull()
    expect(view.notice).toBeNull()
  })

  it("is loading while any source is pending", () => {
    expect(hubState(input({ runsStatus: "pending" }))).toBe("loading")
    expect(hubState(input({ topics: [{ code: "0580", status: "pending" }] }))).toBe("loading")
  })

  it("prefers error over loading, so a failed source never spins forever", () => {
    expect(hubState(input({ overviewStatus: "error", runsStatus: "pending" }))).toBe("error")
    expect(hubState(input({ topics: [{ code: "0580", status: "error" }] }))).toBe("error")
  })

  it("is first time with no papers and no runs", () => {
    expect(hubState(input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], runs: [] }))).toBe("firstTime")
  })

  it("is not first time once a set has been run, even with no papers", () => {
    expect(hubState(input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }] }))).toBe("normal")
  })

  it("is sparse with exactly one paper", () => {
    expect(hubState(input({ subjects: [{ code: "0580", name: "Maths", papers: 1 }] }))).toBe("sparse")
  })

  it("is normal otherwise", () => {
    expect(hubState(input())).toBe("normal")
  })
})

describe("winBackRows", () => {
  it("keeps only topics that lost marks, most marks first, labels stripped", () => {
    const rows = winBackRows(input().subjects, input().topics)
    expect(rows.map((r) => [r.label, r.subjectName, r.marks])).toEqual([
      ["Vectors", "Maths", 9],
      ["Quadratic inequalities", "Maths", 6],
      ["Waves", "Physics", 6],
    ])
  })

  it("links each row to the builder for its subject with that topic preselected", () => {
    const [first] = winBackRows(input().subjects, input().topics)
    expect(first.to).toBe("/student/practice/0580?topic=Vectors")
    const quad = winBackRows(input().subjects, input().topics)[1]
    expect(quad.to).toBe("/student/practice/0580?topic=2.1%20Quadratic%20inequalities")
  })

  it("skips a subject whose topics have not loaded", () => {
    expect(winBackRows(SUBJECTS, [{ code: "0580", status: "error" }])).toEqual([])
  })
})

describe("recentRows", () => {
  it("puts unfinished runs first, then the rest by recency", () => {
    const rows = recentRows(
      [
        run({ assignmentId: "old-done", lastActivityAt: iso(2026, 10, 9) }),
        run({ assignmentId: "new-done", lastActivityAt: iso(2026, 10, 14) }),
        run({ assignmentId: "open", status: "in_progress", answeredCount: 3, questionCount: 8, awardedMarks: null, maximumMarks: null, topics: ["Trigonometry"], lastActivityAt: iso(2026, 10, 1) }),
      ],
      SUBJECTS,
      NOW,
    )
    expect(rows.map((r) => r.assignmentId)).toEqual(["open", "new-done", "old-done"])
  })

  it("resume row says which question is next and links to the set", () => {
    const [row] = recentRows(
      [run({ status: "in_progress", answeredCount: 3, questionCount: 8, awardedMarks: null, maximumMarks: null, topics: ["Trigonometry"] })],
      SUBJECTS,
      NOW,
    )
    expect(row).toMatchObject({ kind: "resume", title: "Trigonometry", sub: "Question 4 of 8 · saved", to: "/student/practice/set/a1" })
  })

  it("never points past the last question", () => {
    const [row] = recentRows([run({ status: "in_progress", answeredCount: 8, questionCount: 8, awardedMarks: null, maximumMarks: null })], SUBJECTS, NOW)
    expect(row.sub).toBe("Question 8 of 8 · saved")
  })

  it("done row shows marks won back and the day", () => {
    const [row] = recentRows([run({})], SUBJECTS, NOW)
    expect(row).toMatchObject({ kind: "done", sub: "7 of 9 back · Tue", to: "/student/practice/result/a1", subjectName: "Maths" })
  })

  it("submitted-but-unmarked never invents a score", () => {
    const [row] = recentRows([run({ status: "submitted", awardedMarks: null, maximumMarks: null })], SUBJECTS, NOW)
    expect(row.kind).toBe("marking")
    expect(row.sub).toBe("Marking · Tue")
    expect(row.sub).not.toMatch(/\d+ of \d+/)
  })

  it("falls back to the set title when no question has a topic", () => {
    const [row] = recentRows([run({ topics: [] })], SUBJECTS, NOW)
    expect(row.title).toBe("Mathematics Practice Set")
  })
})

describe("pickHomework", () => {
  it("is null with no open teacher homework", () => {
    expect(pickHomework([], NOW)).toBeNull()
    expect(pickHomework([homework({ teacherName: null })], NOW)).toBeNull()
    expect(pickHomework([homework({ submissionStatus: "submitted" })], NOW)).toBeNull()
    expect(pickHomework([homework({ isOpen: false })], NOW)).toBeNull()
  })

  it("shows the most urgent: overdue, then soonest due", () => {
    const hw = pickHomework(
      [
        homework({ assignmentId: "later", dueAt: iso(2026, 10, 25) }),
        homework({ assignmentId: "late", isOverdue: true, dueAt: iso(2026, 10, 12) }),
        homework({ assignmentId: "soon", dueAt: iso(2026, 10, 16) }),
      ],
      NOW,
    )
    expect(hw?.assignmentId).toBe("late")
    expect(hw?.sub).toBe("Ms Adel · 8 questions · overdue · +2 more")
  })

  it("matches the mock line for a single homework", () => {
    expect(pickHomework([homework({})], NOW)).toEqual({
      assignmentId: "h1",
      title: "Homework · Vectors set",
      sub: "Ms Adel · 8 questions · due Friday",
      to: "/student/practice/set/h1",
    })
  })
})

describe("hubTiles", () => {
  const base = { firstTime: false, primarySubject: "0580", dueTotal: 26, deckCount: 4, placement: input().placement }

  it("matches the mock statuses", () => {
    expect(hubTiles(base).map((t) => [t.key, t.title, t.status, t.tone])).toEqual([
      ["set", "Practice set", "Build your own", "tide"],
      ["cards", "Flashcards", "26 due today", "violet"],
      ["paper", "Past papers", "Print or do timed", "mint"],
      ["test", "Placement test", "Find your level\u00a0· 10\u00a0min", "sea"],
    ])
  })

  it("routes placement to the first subject that has a test", () => {
    expect(hubTiles(base).find((t) => t.key === "test")?.to).toBe("/student/placement/0625")
  })

  it("first time: pick any topic and make a first deck", () => {
    const tiles = hubTiles({ ...base, firstTime: true, dueTotal: 0, deckCount: 0 })
    expect(tiles[0].status).toBe("Pick any topic")
    expect(tiles[1].status).toBe("Make your first deck")
  })

  it("flashcards: caught up when nothing is due, neutral when unknown", () => {
    expect(hubTiles({ ...base, dueTotal: 0 })[1].status).toBe("All caught up")
    expect(hubTiles({ ...base, dueTotal: null, deckCount: null })[1].status).toBe("Review your cards")
  })

  it("flashcards: never claims caught up while the deck count is unknown", () => {
    expect(hubTiles({ ...base, dueTotal: 0, deckCount: null })[1].status).toBe("Review your cards")
  })

  it("placement: not ready and disabled when no subject has a test", () => {
    const test = hubTiles({ ...base, placement: [{ code: "0580", available: false, minutes: null }] })[3]
    expect(test).toMatchObject({ status: "Not ready yet", disabled: true, to: null })
  })

  it("no subject at all disables only the subject-bound tiles", () => {
    const tiles = hubTiles({ ...base, primarySubject: null, placement: [] })
    expect(tiles[0].disabled).toBe(true)
    expect(tiles[1].disabled).toBe(false)
    expect(tiles[2].disabled).toBe(false)
  })

  it("flashcards always opens the flashcards root (L10 makes it a route)", () => {
    expect(hubTiles(base)[1].to).toBe("/student/flashcards")
  })

  it("exposes the due count so the tile can set it in Mono, and none when nothing is due", () => {
    expect(hubTiles(base)[1].count).toBe(26)
    expect(hubTiles({ ...base, dueTotal: 0 })[1].count).toBeNull()
    expect(hubTiles(base)[0].count).toBeNull()
  })
})

describe("practiceHubView", () => {
  it("normal: subtitle counts every topic to win back, Binny names the top one", () => {
    const view = practiceHubView(input())
    expect(view.state).toBe("normal")
    expect(view.subtitle).toBe("3 topics to win back")
    expect(view.binny).toEqual({ mood: "happy", line: "Vectors first. +9 marks." })
    expect(view.primarySubject).toBe("0580")
    expect(view.winBackMore).toEqual([])
  })

  it("Binny's line never uses an exclamation mark (check:copy gate)", () => {
    for (const v of [practiceHubView(input()), practiceHubView(input({ subjects: [{ code: "0580", name: "Maths", papers: 1 }] }))]) {
      expect(v.binny?.line).not.toContain("!")
    }
  })

  it("keeps overflow rows from every subject for disclosure", () => {
    const view = practiceHubView(input({ topics: [
      { code: "0580", status: "success", data: topics("0580", [["A", 4], ["B", 3], ["C", 2]]) },
      { code: "0625", status: "success", data: topics("0625", [["D", 1]]) },
    ] }))
    expect(view.winBack).toHaveLength(3)
    expect(view.winBackMore.map((row) => row.subjectCode)).toEqual(["0625"])
    expect(view.subtitle).toBe("4 topics to win back")
  })

  it("sparse: one topic, the scan tip, an encouraging line", () => {
    const view = practiceHubView(
      input({ subjects: [{ code: "0580", name: "Maths", papers: 1 }], topics: [{ code: "0580", status: "success", data: topics("0580", [["Vectors", 9]]) }], runs: [] }),
    )
    expect(view.state).toBe("sparse")
    expect(view.subtitle).toBe("1 topic to win back")
    expect(view.binny?.line).toBe("Good start. Try one set.")
    expect(view.showScanTip).toBe(true)
  })

  it("first time: open Binny with the walkthrough line, no subtitle", () => {
    const view = practiceHubView(input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], topics: [], runs: [] }))
    expect(view.state).toBe("firstTime")
    expect(view.subtitle).toBeNull()
    expect(view.binny).toEqual({ mood: "open", line: "Scan a paper and I'll find your marks to win back." })
  })

  it("normal with nothing to win back: no subtitle, a calm line", () => {
    const view = practiceHubView(input({ topics: [{ code: "0580", status: "success", data: topics("0580", [["Vectors", 0]]) }] }))
    expect(view.subtitle).toBeNull()
    expect(view.binny?.line).toBe("All caught up. Try a set.")
    expect(view.showScanTip).toBe(false)
  })

  it("one mark to win back reads singular", () => {
    const view = practiceHubView(input({ topics: [{ code: "0580", status: "success", data: topics("0580", [["Vectors", 1]]) }] }))
    expect(view.binny?.line).toBe("Vectors first. +1 mark.")
  })

  it("sets done but no paper scanned: asks for a paper instead of claiming caught up", () => {
    const view = practiceHubView(
      input({ subjects: [{ code: "0580", name: "Maths", papers: 0 }], topics: [{ code: "0580", status: "success", data: topics("0580", []) }] }),
    )
    expect(view.state).toBe("normal")
    expect(view.binny).toEqual({ mood: "happy", line: "Scan a paper next." })
    expect(view.showScanTip).toBe(true)
  })

  it("error: tiles still present, no Binny line, no subtitle", () => {
    const view = practiceHubView(input({ runsStatus: "error" }))
    expect(view.state).toBe("error")
    expect(view.tiles).toHaveLength(4)
    expect(view.binny).toBeNull()
    expect(view.subtitle).toBeNull()
  })

  it("splits recent into the first four and the rest", () => {
    const runs = Array.from({ length: 6 }, (_, i) => run({ assignmentId: `r${i}`, lastActivityAt: iso(2026, 10, 14 - i) }))
    const view = practiceHubView(input({ runs }))
    expect(view.recent).toHaveLength(4)
    expect(view.recentMore).toHaveLength(2)
  })

  it("shows homework only when set, and never while loading", () => {
    expect(practiceHubView(input()).homework).toBeNull()
    expect(practiceHubView(input({ homework: [homework({})] })).homework?.title).toBe("Homework · Vectors set")
    expect(practiceHubView(input({ homework: [homework({})], runsStatus: "pending" })).homework).toBeNull()
  })
})
