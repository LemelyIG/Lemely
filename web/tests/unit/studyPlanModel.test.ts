import { describe, expect, it } from "vitest"
import type {
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
  SubjectWeekDTO,
} from "@/lib/studyPlanTypes"
import { planScreen, resolveFilter, ringParts, type PlanModelInput } from "@/portals/student/screens/studyplan/planModel"

const S = (id: string, date: string, extra: Partial<StudyPlanSessionDTO> = {}): StudyPlanSessionDTO => ({
  id, date, topic: id, activityType: "practice", durationMinutes: 10, focus: "", completedAt: null,
  anyDay: false, reason: null, ...extra,
})
const P = (code: string, sessions: StudyPlanSessionDTO[], extra: Partial<StudyPlanWeekDTO> = {}): StudyPlanWeekDTO => ({
  id: `plan-${code}`, subjectCode: code, weekStart: "2026-08-03", weeklyHours: 2, available: true, reason: null,
  generatedAt: "2026-08-03T09:00:00Z", sessions, ...extra,
})
const SUB = (code: string, plan: StudyPlanWeekDTO | null, extra: Partial<SubjectWeekDTO> = {}): SubjectWeekDTO => ({
  subjectCode: code, generated: plan !== null, plan, paperCount: 4, weakTopics: [], ...extra,
})
const O = (subjects: SubjectWeekDTO[], extra: Partial<StudyPlanOverviewDTO> = {}): StudyPlanOverviewDTO => ({
  today: "2026-08-06", weekStart: "2026-08-03", weekEnd: "2026-08-09", subjects, ...extra,
})
const DONE = "2026-08-04T10:00:00Z"
const NAMES: Record<string, string> = { "0580": "Mathematics", "0606": "Additional Maths", "0625": "Physics" }

function mockWeek(): StudyPlanOverviewDTO {
  return O([
    SUB("0580", P("0580", [
      S("Algebra", "2026-08-03", { completedAt: DONE, reason: { kind: "marks_lost", count: 7 } }),
      S("Vectors", "2026-08-06", { reason: { kind: "marks_lost", count: 9 } }),
      S("Trigonometry", "2026-08-07", { reason: { kind: "marks_lost", count: 5 } }),
    ]), { weakTopics: [{ topic: "Vectors", accuracyPct: 41 }, { topic: "Algebra", accuracyPct: 58 }, { topic: "Trigonometry", accuracyPct: 62 }] }),
    SUB("0606", P("0606", [
      S("Quadratic inequalities", "2026-08-05", { reason: { kind: "marks_lost", count: 6 } }),
      S("Functions", "2026-08-08", { activityType: "flashcards", durationMinutes: 5, reason: { kind: "cards_due", count: 9 } }),
    ])),
    SUB("0625", P("0625", [
      S("Forces", "2026-08-04", { activityType: "flashcards", durationMinutes: 5, completedAt: DONE }),
      S("Waves", "2026-08-06", { activityType: "flashcards", durationMinutes: 5, reason: { kind: "cards_due", count: 12 } }),
      S("0625/42", "2026-08-06", { activityType: "past_paper", durationMinutes: 45, anyDay: true, reason: { kind: "last_paper", count: 9 } }),
    ])),
  ])
}

function input(overview: StudyPlanOverviewDTO, extra: Partial<PlanModelInput> = {}): PlanModelInput {
  return {
    overview,
    filter: null,
    subjectName: (c) => NAMES[c] ?? c,
    targetGrade: (c) => (c === "0580" ? "A*" : null),
    nextExam: (c) => (c === "0580" ? { date: "2027-02-10", paperNumber: 4 } : c === "0625" ? { date: "2027-02-01", paperNumber: 4 } : null),
    now: new Date("2026-08-06T12:00:00"),
    xp: { weekXp: 260, streak: 7 },
    ...extra,
  }
}

function asPlan(screen: ReturnType<typeof planScreen>) {
  if (screen.kind !== "plan") throw new Error(`expected plan, got ${screen.kind}`)
  return screen
}

describe("state selection", () => {
  it("noSubjects when the student is enrolled in nothing", () => {
    expect(planScreen(input(O([]))).kind).toBe("noSubjects")
  })
  it("firstRun when no subject has a plan, building every subject", () => {
    const s = planScreen(input(O([SUB("0580", null), SUB("0625", null)])))
    expect(s.kind).toBe("firstRun")
    if (s.kind === "firstRun") {
      expect(s.codesToBuild).toEqual(["0580", "0625"])
      expect(s.header.sub).toBe("No plan yet")
    }
  })
  it("firstRun builds only the missing subjects when the rest were refused", () => {
    const s = planScreen(input(O([SUB("0580", null), SUB("0625", P("0625", [], { available: false, reason: "no_signal" }))])))
    expect(s.kind === "firstRun" && s.codesToBuild).toEqual(["0580"])
  })
  it("needPaper when every plan is a refusal", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [], { available: false, reason: "no_signal" }))])))
    expect(s.kind).toBe("needPaper")
    if (s.kind === "needPaper") {
      expect(s.placementCode).toBe("0625")
      expect(s.copy.heading).toBe("I need a paper first")
    }
  })
  it("an unknown refusal reason keeps its own copy", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [], { available: false, reason: "quota" }))])))
    expect(s.kind === "needPaper" && s.copy.heading).toBe("I couldn’t plan this week")
  })
  it("nothingScheduled for a real plan with zero sessions", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", []))])))
    expect(s.kind).toBe("nothingScheduled")
    expect(s.kind === "nothingScheduled" && s.practiceCode).toBe("0625")
  })
  it("weekDone when every session is done, with real XP and streak", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-04", { completedAt: DONE }), S("b", "2026-08-05", { completedAt: DONE, durationMinutes: 45 })]))])))
    expect(s.kind).toBe("weekDone")
    if (s.kind === "weekDone") {
      expect(s.body).toBe("All 2 sessions, 55 min.")
      expect(s.stats).toEqual([
        { value: "2", label: "sessions", tone: "ok" },
        { value: "+260", label: "XP", tone: "primary" },
        { value: "7", label: "days in a row", tone: "ok" },
      ])
      expect(s.header.sub).toBe("2 of 2 done · 55 min")
    }
  })
  it("weekDone without XP shows only what is known", () => {
    const s = planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-04", { completedAt: DONE })]))]), { xp: null }))
    expect(s.kind === "weekDone" && s.stats).toEqual([{ value: "1", label: "session", tone: "ok" }])
  })
})

describe("the all-subjects week (WA)", () => {
  const screen = asPlan(planScreen(input(mockWeek())))
  const b = screen.body

  it("sums the header and lists the filter chips", () => {
    expect(screen.header.title).toBe("This week")
    expect(screen.header.sub).toBe("2 of 8 done · 1 h 40 min")
    expect(screen.header.examDate).toBe("2027-02-01")
    expect(screen.header.filters.map((f) => [f.label, f.selected, f.dotIndex])).toEqual([
      ["All", true, null], ["Mathematics", false, 0], ["Additional Maths", false, 1], ["Physics", false, 2],
    ])
  })
  it("puts today first, with the open sessions and a ring", () => {
    expect(b.today.heading).toBe("Today · Thursday")
    expect(b.today.sub).toBe("2 sessions · 15 min")
    expect(b.today.sessions.map((s) => s.title)).toEqual(["Vectors", "Waves"])
    expect(b.ring).toEqual([0, 0, 0])
    expect(b.ringLabel).toBe("Today: 0 of 3 goals done")
  })
  it("writes each row's reason and start action", () => {
    const [vectors, waves] = b.today.sessions
    expect(vectors.why).toBe("Cost you 9 marks")
    expect(vectors.start).toEqual({ label: "Start · +9 marks", path: "/student/practice/0580" })
    expect(vectors.whyBody).toBe("Vectors has cost you 9 marks so far. Win them back on the way to your A*.")
    expect(waves.why).toBe("12 cards due")
    expect(waves.subjectName).toBe("Physics")
    expect(waves.dotIndex).toBe(2)
  })
  it("lists missed sessions with today as a move day", () => {
    expect(b.missed.map((s) => [s.title, s.dayShort])).toEqual([["Quadratic inequalities", "Wed"]])
    expect(b.missed[0].moveDays.map((d) => d.label)).toEqual(["Today", "Fri", "Sat", "Sun"])
  })
  it("offers a today session every later day, never its own", () => {
    expect(b.today.sessions[0].moveDays.map((d) => d.label)).toEqual(["Fri", "Sat", "Sun"])
    expect(b.today.sessions[0].canMove).toBe(true)
  })
  it("draws the Mon–Sun strip and the any-day list", () => {
    expect(b.week.show).toBe(true)
    expect(b.week.days.map((d) => [d.letter, d.count, d.isToday, d.allDone, d.hasMissed])).toEqual([
      ["M", 1, false, true, false], ["T", 1, false, true, false], ["W", 1, false, false, true],
      ["T", 3, true, false, false], ["F", 1, false, false, false], ["S", 1, false, false, false], ["S", 0, false, false, false],
    ])
    expect(b.week.anyDay.map((s) => s.title)).toEqual(["0625/42"])
    expect(b.week.anyDay[0].canMove).toBe(false)
    expect(b.week.anyDay[0].why).toBe("Your last paper was 9 days ago")
  })
  it("groups later days and folds done sessions", () => {
    expect(b.later.map((g) => [g.label, g.sessions.map((s) => s.title)])).toEqual([["Fri", ["Trigonometry"]], ["Sat", ["Functions"]]])
    expect(b.done.count).toBe(2)
    expect(b.done.title).toBe("2 done this week")
    expect(b.done.daysLabel).toBe("Mon · Tue")
    expect(b.done.openByDefault).toBe(false)
    expect(b.done.sessions.every((s) => !s.canMove)).toBe(true)
  })
  it("says what it is built from and picks the panel's first session", () => {
    expect(b.basedOn).toBe("Built from your 12 papers and weak topics")
    expect(b.firstOpenId).toBe("Vectors")
    expect(b.binnyLine).toBe("15 minutes today.")
    expect(b.subjectTop).toBeNull()
    expect(b.whyTopics).toEqual([])
    expect(screen.all).toHaveLength(8)
  })
})

describe("one subject (WM)", () => {
  const screen = asPlan(planScreen(input(mockWeek(), { filter: "0580" })))
  it("scopes the header, adds the target line and why-these-topics", () => {
    expect(screen.header.sub).toBe("Mathematics · 3 sessions · 30 min")
    expect(screen.header.examDate).toBe("2027-02-10")
    expect(screen.header.filters.find((f) => f.selected)?.label).toBe("Mathematics")
    expect(screen.body.subjectTop).toEqual({ targetGrade: "A*", exam: "Paper 4 in 188 days" })
    expect(screen.body.whyTopics).toEqual([
      { topic: "Vectors", pct: 41, tone: "w" }, { topic: "Algebra", pct: 58, tone: "w" }, { topic: "Trigonometry", pct: 62, tone: "m" },
    ])
    expect(screen.body.whyHint).toBe("Your weakest Mathematics topics from 4 papers.")
    expect(screen.body.today.sub).toBe("1 session · 10 min")
  })
  it("opens the done fold and hides the strip when nothing is any-day", () => {
    expect(screen.body.done.title).toBe("1 done")
    expect(screen.body.done.openByDefault).toBe(true)
    expect(screen.body.week.show).toBe(false)
  })
})

describe("edges", () => {
  it("labels a session the scheduler placed past Sunday", () => {
    const s = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06"), S("b", "2026-08-10")]))]))))
    expect(s.body.later.map((g) => g.label)).toEqual(["Next Mon"])
    expect(s.body.week.days.reduce((n, d) => n + d.count, 0)).toBe(1)
  })
  it("says done for today, or nothing today", () => {
    const doneToday = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06", { completedAt: DONE }), S("b", "2026-08-07")]))]))))
    expect(doneToday.body.today.sub).toBe("Done for today")
    expect(doneToday.body.binnyLine).toBe("Done for today.")
    const freeToday = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("b", "2026-08-07")]))]))))
    expect(freeToday.body.today.sub).toBe("Nothing planned today")
    expect(freeToday.body.firstOpenId).toBe("b")
  })
  it("counts only the goals planned today in the ring label", () => {
    const one = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06"), S("b", "2026-08-07")]))]))))
    expect(one.body.ringLabel).toBe("Today: 0 of 1 goal done")
    const met = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06", { completedAt: DONE }), S("b", "2026-08-07")]))]))))
    expect(met.body.ringLabel).toBe("Today: 1 of 1 goal done")
    const two = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06"), S("c", "2026-08-06", { activityType: "flashcards" }), S("b", "2026-08-07")]))]))))
    expect(two.body.ringLabel).toBe("Today: 0 of 2 goals done")
    const none = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("b", "2026-08-07")]))]))))
    expect(none.body.ringLabel).toBe("Today: nothing planned")
  })
  it("points Binny at missed sessions when nothing is due today", () => {
    const behind = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("m1", "2026-08-04"), S("m2", "2026-08-05"), S("b", "2026-08-07")]))]))))
    expect(behind.body.binnyLine).toBe("2 to catch up.")
    const caughtUp = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("b", "2026-08-07")]))]))))
    expect(caughtUp.body.binnyLine).toBe("Nothing due today.")
    const doneToday = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("m1", "2026-08-04"), S("a", "2026-08-06", { completedAt: DONE }), S("b", "2026-08-07")]))]))))
    expect(doneToday.body.binnyLine).toBe("Done for today.")
  })
  it("lists subjects without a usable plan as pending rows", () => {
    const s = asPlan(planScreen(input(O([SUB("0580", null), SUB("0625", P("0625", [S("a", "2026-08-06")])), SUB("0606", P("0606", [], { available: false, reason: "no_signal" }))]))))
    expect(s.body.pending).toEqual([
      { subjectCode: "0580", subjectName: "Mathematics", kind: "notGenerated" },
      { subjectCode: "0606", subjectName: "Additional Maths", kind: "refused" },
    ])
  })
  it("hides the filter chips for a single subject", () => {
    expect(asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06")]))])))).header.filters).toEqual([])
  })
  it("fills the ring per goal as sessions are done", () => {
    const vms = asPlan(planScreen(input(mockWeek()))).all.map((v) => (v.title === "Vectors" ? { ...v, status: "done" as const } : v))
    expect(ringParts(vms, "2026-08-06")).toEqual([1, 0, 0])
  })
  it("resolves an unknown subject filter to all", () => {
    expect(resolveFilter(mockWeek(), "0580")).toBe("0580")
    expect(resolveFilter(mockWeek(), "9999")).toBeNull()
    expect(resolveFilter(mockWeek(), undefined)).toBeNull()
  })
})

describe("totality and move rules", () => {
  it("a stale filter code falls back to all subjects instead of throwing", () => {
    const s = planScreen(input(mockWeek(), { filter: "9999" }))
    expect(s.kind).toBe("plan")
    expect(s.kind === "plan" && s.header.filters.find((f) => f.selected)?.label).toBe("All")
  })
  it("a stale filter on a week with no plans still returns a state", () => {
    const s = planScreen(input(O([SUB("0580", null), SUB("0625", null)]), { filter: "9999" }))
    expect(s.kind).toBe("firstRun")
    expect(s.kind === "firstRun" && s.codesToBuild).toEqual(["0580", "0625"])
  })
  it("a generated subject with no plan body counts as not built", () => {
    const o = O([SUB("0580", null, { generated: true }), SUB("0625", P("0625", [S("a", "2026-08-06")]))])
    const alone = planScreen(input(o, { filter: "0580" }))
    expect(alone.kind).toBe("firstRun")
    expect(alone.kind === "firstRun" && alone.codesToBuild).toEqual(["0580"])
    const mixed = asPlan(planScreen(input(o)))
    expect(mixed.body.pending).toEqual([{ subjectCode: "0580", subjectName: "Mathematics", kind: "notGenerated" }])
  })
  it("stops move days at the end of the week for a session placed past Sunday", () => {
    const s = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06"), S("b", "2026-08-10")]))]))))
    const b = s.all.find((v) => v.id === "b")
    expect(b?.moveDays.map((d) => d.label)).toEqual(["Today", "Fri", "Sat", "Sun"])
    expect(b?.moveDays.every((d) => d.date <= "2026-08-09")).toBe(true)
  })
  it("cannot move anything when today is the plan's last day", () => {
    const o = O([SUB("0625", P("0625", [S("a", "2026-08-09")]))], { today: "2026-08-09" })
    const s = asPlan(planScreen(input(o)))
    expect(s.body.today.sessions[0].moveDays).toEqual([])
    expect(s.body.today.sessions[0].canMove).toBe(false)
  })
  it("a missed any-day session is not movable", () => {
    const s = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-04", { anyDay: true }), S("b", "2026-08-07")]))]))))
    const a = s.all.find((v) => v.id === "a")
    expect(a?.status).toBe("anyDay")
    expect(a?.canMove).toBe(false)
    expect(a?.moveDays).toEqual([])
  })
  it("leaves a goal with nothing planned at zero", () => {
    const s = asPlan(planScreen(input(O([SUB("0625", P("0625", [S("a", "2026-08-06", { completedAt: DONE }), S("b", "2026-08-07")]))]))))
    expect(ringParts(s.all, "2026-08-06")).toEqual([1, 0, 0])
  })
})
