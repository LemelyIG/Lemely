import { describe, expect, it } from "vitest"
import {
  alsoRows,
  bandVm,
  daysBetween,
  examInfo,
  firstName,
  floorVm,
  homeView,
  initials,
  isFirstRun,
  lastPaperVm,
  pickStage,
  questionLabel,
  relativeDay,
  shortGreeting,
  shortSubject,
  stageCandidates,
  streakPillVm,
  todayVm,
  weekVm,
  winVm,
} from "@/portals/student/home/model"
import type { HomeMoment } from "@/lib/studentHomeTypes"
import { makeHome } from "./studentHomeFixture"
import { bubbleText, wordsIn } from "./support/homeBubble"

const NONE: ReadonlySet<string> = new Set()
const result: HomeMoment = {
  kind: "result", paperId: "5", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4,
  awarded: 61, maximum: 80, grade: "B", previousGrade: "C", focusQuestion: "8", recordedAt: "2026-11-12T07:00:00+00:00",
}
const tough: HomeMoment = { ...result, kind: "tough", subjectCode: "0625", subjectName: "Physics", grade: "D", previousGrade: null, focusQuestion: "3" }
const marking: HomeMoment = { kind: "marking", paperId: "u1", filename: null, startedAt: null, stale: false, questionsDone: 8, questionsTotal: 14 }
const streak: HomeMoment = { kind: "streakAtRisk", streakDays: 9 }
const done: HomeMoment = { kind: "goalDone", streakDays: 10 }
const back: HomeMoment = { kind: "backAfterBreak", daysAway: 6 }
const reply: HomeMoment = { kind: "teacherReply", reply: makeHome().teacherReplies[0] }

describe("small helpers", () => {
  it("names and greetings", () => {
    expect(firstName("Mariam Adel")).toBe("Mariam")
    expect(firstName("m.adel@example.com")).toBe("m.adel")
    expect(firstName("  ")).toBe("there")
    expect(shortGreeting(9)).toBe("Morning")
    expect(shortGreeting(14)).toBe("Afternoon")
    expect(shortGreeting(23)).toBe("Evening")
    expect(shortGreeting(3)).toBe("Evening")
  })

  it("labels", () => {
    expect(questionLabel("8")).toBe("Q8")
    expect(questionLabel("Q4b")).toBe("Q4b")
    expect(shortSubject("Additional Mathematics")).toBe("Add Maths")
    expect(shortSubject("Mathematics")).toBe("Mathematics")
    expect(initials("Ms. Hanna")).toBe("MH")
    expect(initials("Hanna")).toBe("H")
  })

  it("days and relative days", () => {
    expect(daysBetween("2026-11-12", "2026-12-12")).toBe(30)
    expect(relativeDay("2026-11-12T08:00:00", "2026-11-12")).toBe("today")
    expect(relativeDay("2026-11-11T08:00:00", "2026-11-12")).toBe("yesterday")
    expect(relativeDay("2026-11-10T08:00:00", "2026-11-12")).toBe("2 days ago")
    expect(relativeDay("2026-11-03T08:00:00", "2026-11-12")).toBe("last week")
    expect(relativeDay("2026-10-20T08:00:00", "2026-11-12")).toBe("3 weeks ago")
  })

  it("exam info turns near inside 30 days", () => {
    expect(examInfo(makeHome({ nextExamOn: null }))).toBeNull()
    expect(examInfo(makeHome({ nextExamOn: "2026-12-12" }))).toEqual({ date: "2026-12-12", days: 30, near: true })
    expect(examInfo(makeHome({ nextExamOn: "2026-12-13" }))?.near).toBe(false)
  })
})

describe("stage", () => {
  it("follows the priority order", () => {
    const home = makeHome({ moments: [back, done, streak, reply, tough, marking] })
    expect(stageCandidates(home).map((s) => s.kind).slice(0, 6)).toEqual([
      "marking", "tough", "teacherReply", "streakAtRisk", "goalDone", "backAfterBreak",
    ])
  })

  it("result: a B is a pleased Binny (mood follows the grade), names the question to fix", () => {
    const s = pickStage(makeHome({ moments: [result] }), NONE)
    expect(s).toMatchObject({ kind: "result", mood: "wink", motion: "idle", dismissible: true })
    expect(s.line).toBe("From C to B")
    expect(s.action).toEqual({ label: "Fix Q8", to: "/student/result/5?q=lost" })
    const anA = pickStage(makeHome({ moments: [{ ...result, grade: "A", previousGrade: "E" } as HomeMoment] }), NONE)
    expect(anA.line).toBe("From E to A")
  })

  it("tough: a D is a concerned Binny, easiest question first", () => {
    const s = pickStage(makeHome({ moments: [tough] }), NONE)
    expect(s.mood).toBe("thinking")
    expect(s.line).toBe("Win back easy marks")
    expect(s.action.label).toBe("Start with Q3")
  })

  it("marking: thinking, never dismissible, shows progress when known", () => {
    const s = pickStage(makeHome({ moments: [marking] }), new Set(["marking:u1"]))
    expect(s).toMatchObject({ kind: "marking", mood: "thinking", dismissible: false })
    expect(s.line).toBe("8 of 14 marked")
    expect(s.action).toEqual({ label: "Watch it mark", to: "/student/correct" })
  })

  it("streak, goal done, back after a break", () => {
    expect(pickStage(makeHome({ moments: [streak] }), NONE)).toMatchObject({
      mood: "thinking",
      line: "Streak ends at midnight",
      action: { label: "Keep my streak", to: "/student/practice/0580?topic=Vectors" },
    })
    expect(pickStage(makeHome({ moments: [done] }), NONE)).toMatchObject({
      mood: "happy",
      line: "Three for three today",
      action: { label: "See tomorrow's plan", to: "/student/plan/0580" },
    })
    expect(pickStage(makeHome({ moments: [back] }), NONE)).toMatchObject({
      mood: "wink",
      line: "Ease back in",
      action: { label: "5-minute warm-up" },
    })
  })

  it("teacher reply: wink, links the result", () => {
    const s = pickStage(makeHome({ moments: [reply] }), NONE)
    expect(s.line).toBe("Your teacher checked Q7")
    expect(s.action).toEqual({ label: "See the answer", to: "/student/result/5" })
  })

  it("result with no grade change just names the grade", () => {
    const same = pickStage(makeHome({ moments: [{ ...result, previousGrade: null } as HomeMoment] }), NONE)
    expect(same.line).toBe("That's a B")
    const unchanged = pickStage(makeHome({ moments: [{ ...result, previousGrade: "B" } as HomeMoment] }), NONE)
    expect(unchanged.line).toBe("That's a B")
    const anA = pickStage(makeHome({ moments: [{ ...result, grade: "A*", previousGrade: null } as HomeMoment] }), NONE)
    expect(anA.line).toBe("That's an A*")
  })

  it("marking: no progress, no total, and a stale run each keep a short line", () => {
    const noProgress = pickStage(makeHome({ moments: [{ ...marking, questionsDone: null, questionsTotal: null }] }), NONE)
    expect(noProgress.line).toBe("Marking your paper")
    const noTotal = pickStage(makeHome({ moments: [{ ...marking, questionsDone: 0, questionsTotal: 0 }] }), NONE)
    expect(noTotal.line).toBe("Marking your paper")
    const zero = pickStage(makeHome({ moments: [{ ...marking, questionsDone: 0, questionsTotal: 1 }] }), NONE)
    expect(zero.line).toBe("0 of 1 marked")
    const stale = pickStage(makeHome({ moments: [{ ...marking, stale: true }] }), NONE)
    expect(stale.line).toBe("Still marking your paper")
  })

  it("falls back to today's session, then the top topic (morning), then scan", () => {
    const withSession = makeHome({
      todaySessions: [{ sessionId: "s1", subjectCode: "0625", topic: "Waves", minutes: 15, done: false }],
      nextExamOn: null,
    })
    expect(pickStage(withSession, NONE)).toMatchObject({
      kind: "session",
      line: "Today: Waves",
      action: { label: "Start", to: "/student/plan/0625/session/s1" },
    })
    const morning = pickStage(makeHome({ nextExamOn: null }), NONE)
    expect(morning).toMatchObject({
      kind: "morning",
      mood: "open",
      line: "Win marks back",
      action: { label: "Start 10 minutes", to: "/student/practice/0580?topic=Vectors" },
    })
    expect(pickStage(makeHome({ winBack: [], nextExamOn: null }), NONE)).toMatchObject({
      kind: "scanNext",
      dismissible: false,
      action: { label: "Scan a paper", to: "/student/correct" },
    })
  })

  it("keeps the exam countdown out of the bubble inside 30 days", () => {
    const s = pickStage(makeHome({ nextExamOn: "2026-11-24" }), NONE)
    expect(s.line).toBe("Win marks back")
    const scan = pickStage(makeHome({ nextExamOn: "2026-11-24", winBack: [] }), NONE)
    expect(scan.line).toBe("Scan your next paper")
    const session = pickStage(
      makeHome({ nextExamOn: "2026-11-24", todaySessions: [{ sessionId: "s1", subjectCode: "0625", topic: "Waves", minutes: 15, done: false }] }),
      NONE,
    )
    expect(session.line).toBe("Today: Waves")
    const first = pickStage(
      makeHome({ nextExamOn: "2026-11-24", floor: [], recentPapers: [], winBack: [], stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null } }),
      NONE,
    )
    expect(first.line).toBe("Mark your first paper")
  })

  it("a long session topic falls back to a short line instead of running past four words", () => {
    const long = makeHome({
      nextExamOn: null,
      todaySessions: [{ sessionId: "s2", subjectCode: "0625", topic: "Electromagnetic induction and transformers", minutes: 15, done: false }],
    })
    expect(pickStage(long, NONE).line).toBe("Today's plan is ready")
    const three = makeHome({
      nextExamOn: null,
      todaySessions: [{ sessionId: "s3", subjectCode: "0625", topic: "Forces and motion", minutes: 15, done: false }],
    })
    expect(pickStage(three, NONE).line).toBe("Today: Forces and motion")
  })

  it("everything rendered in Binny's bubble is two to four words with no bang or curly apostrophe", () => {
    const session = { sessionId: "s1", subjectCode: "0625", topic: "Waves", minutes: 15, done: false }
    const longSession = { ...session, topic: "Electromagnetic induction and transformers" }
    const firstRun = { floor: [], recentPapers: [], winBack: [], stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null } }
    const homes = [null, "2026-11-24"].flatMap((nextExamOn) => [
      makeHome({ nextExamOn, moments: [result, tough, marking, streak, done, back, reply] }),
      makeHome({ nextExamOn, moments: [{ ...result, previousGrade: null } as HomeMoment, { ...marking, stale: true }] }),
      makeHome({ nextExamOn, moments: [{ ...marking, questionsDone: null, questionsTotal: null }, { ...tough, focusQuestion: null } as HomeMoment] }),
      makeHome({ nextExamOn, moments: [], todaySessions: [session] }),
      makeHome({ nextExamOn, moments: [], todaySessions: [longSession] }),
      makeHome({ nextExamOn, moments: [], winBack: [] }),
      makeHome({ nextExamOn, moments: [], ...firstRun }),
    ])
    // The rendered bubble, not `s.line`: a greeting or any other text HomeStage adds to the paragraph counts too.
    const bubbles = homes.flatMap((h) => stageCandidates(h).map((s) => ({ line: s.line, said: bubbleText(s) })))
    expect(bubbles.length).toBeGreaterThan(20)
    for (const { line, said } of bubbles) {
      expect(said, `bubble for line "${line}"`).toBe(line)
      const words = wordsIn(said)
      expect(words, `"${said}"`).toBeGreaterThanOrEqual(2)
      expect(words, `"${said}"`).toBeLessThanOrEqual(4)
      expect(said, `"${said}"`).not.toMatch(/[!\u2018\u2019\u2014]/)
    }
  })

  it("skips dismissed moments and never dismisses the last fallback", () => {
    const home = makeHome({ moments: [result], nextExamOn: null })
    expect(pickStage(home, new Set(["result:5"])).kind).toBe("morning")
    expect(pickStage(home, new Set(["result:5", "morning:0580:Vectors"])).kind).toBe("scanNext")
  })

  it("first run", () => {
    const home = makeHome({ floor: [], recentPapers: [], winBack: [], nextExamOn: null, stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null } })
    expect(isFirstRun(home)).toBe(true)
    expect(pickStage(home, NONE)).toMatchObject({
      kind: "firstRun",
      mood: "open",
      line: "Mark your first paper",
      action: { label: "Scan a paper", to: "/student/correct" },
      dismissible: false,
    })
  })
})

describe("rows and blocks", () => {
  it("also rows: result row pairs with a paper stage, two rows at most", () => {
    const home = makeHome({ moments: [result] })
    const rows = alsoRows(home, pickStage(home, NONE), "phone")
    expect(rows.map((r) => r.kind)).toEqual(["result", "teacher"])
    expect(rows[0]).toMatchObject({ title: "See your full result", sub: "Mathematics · Paper 4", to: "/student/result/5", leading: { type: "grade", grade: "B" } })
  })

  it("also rows: morning shows teacher reply and homework on phone, neither on desktop", () => {
    const home = makeHome({ nextExamOn: null })
    const stage = pickStage(home, NONE)
    expect(alsoRows(home, stage, "phone").map((r) => r.kind)).toEqual(["teacher", "homework"])
    expect(alsoRows(home, stage, "desktop")).toEqual([])
    expect(alsoRows(home, stage, "phone")[1]).toMatchObject({
      title: "Trigonometry set from Ms. Hanna",
      sub: "Due tomorrow · 12 questions",
      to: "/student/practice/set/a1",
    })
  })

  it("also rows: a teacher reply stage keeps the teacher row on phone, since the line no longer names who or how many marks", () => {
    const home = makeHome({ moments: [reply], nextExamOn: null })
    const stage = pickStage(home, NONE)
    expect(stage.kind).toBe("teacherReply")
    const rows = alsoRows(home, stage, "phone")
    expect(rows[0]).toMatchObject({ kind: "teacher", title: "Ms. Hanna checked your answer", sub: "Q7 · +1 mark" })
  })

  it("also rows: join class, sparse nudge, scan nudge", () => {
    const base = makeHome({ teacherReplies: [], homework: [], classCount: 0, nextExamOn: null, lastPaperAt: "2026-11-01T10:00:00+00:00" })
    const kinds = alsoRows(base, pickStage(base, NONE), "phone").map((r) => r.kind)
    expect(kinds).toEqual(["joinClass", "scan"])
    const sparse = makeHome({ teacherReplies: [], homework: [], stats: { papersMarked: 1, marksWonBack: 0, bestGrade: null } })
    expect(alsoRows(sparse, pickStage(sparse, NONE), "phone")[0]).toMatchObject({
      kind: "sparse",
      title: "One more paper draws your trend",
      to: "/student/correct",
    })
  })

  it("today block", () => {
    const vm = todayVm(makeHome({ goals: { practice: true, flashcards: false, paperThisWeek: true } }))
    expect(vm.parts).toEqual([1, 0, 1])
    expect(vm.doneCount).toBe(2)
    expect(vm.label).toBe("2 of 3 today")
    expect(vm.chips.map((c) => [c.label, c.done, c.to])).toEqual([
      ["Practice", true, "/student/practice/0580?topic=Vectors"],
      ["Flashcards", false, "/student/flashcards/0580"],
      ["Paper this week", true, "/student/correct"],
    ])
  })

  it("week strip", () => {
    const days = weekVm(makeHome())
    expect(days.map((d) => d.letter).join("")).toBe("MTWTFSS")
    expect(days[3]).toMatchObject({ isToday: true, done: false, ariaLabel: "Thursday: Vectors" })
    expect(days[0].ariaLabel).toBe("Monday: Vectors, done")
  })

  it("grade floor", () => {
    const floor = floorVm(makeHome())
    expect(floor[2]).toEqual({ code: "0606", name: "Add Maths", grade: "B", sub: "9 marks to A", to: "/student/subject/0606" })
    const top = floorVm(makeHome({ floor: [{ ...makeHome().floor[0], grade: "A*", nextGrade: null, pointsToNext: null }] }))
    expect(top[0].sub).toBe("Top grade")
    const noGap = floorVm(makeHome({ floor: [{ ...makeHome().floor[0], grade: "B", nextGrade: "A", pointsToNext: null }] }))
    expect(noGap[0].sub).toBe("On the way to A")
  })

  it("last paper, win rows, streak pill", () => {
    expect(lastPaperVm(makeHome())).toEqual({
      grade: "B", title: "Last paper · Mathematics P4", sub: "61/80 · 2 days ago", to: "/student/result/5",
    })
    expect(lastPaperVm(makeHome({ recentPapers: [] }))).toBeNull()
    expect(winVm(makeHome(), "morning")).toHaveLength(3)
    expect(winVm(makeHome(), "backAfterBreak")).toHaveLength(1)
    expect(winVm(makeHome(), "morning")[0]).toEqual({ topic: "Vectors", sub: "Mathematics", marks: 9, to: "/student/practice/0580?topic=Vectors" })
    expect(streakPillVm(makeHome())).toEqual({ label: "9 days", lit: false, to: "/student/profile" })
    expect(streakPillVm(makeHome({ goals: { practice: true, flashcards: true, paperThisWeek: true } })).lit).toBe(true)
    expect(streakPillVm(makeHome({ streak: { current: 0, longest: 14, lastActiveOn: null, freezesAvailable: 0 } })).label).toBe("New streak")
    expect(streakPillVm(makeHome({ streak: { current: 0, longest: 0, lastActiveOn: null, freezesAvailable: 0 } })).label).toBe("Start a streak")
    expect(streakPillVm(makeHome({ streak: { current: 1, longest: 1, lastActiveOn: null, freezesAvailable: 0 } })).label).toBe("1 day")
  })

  it("desktop band", () => {
    const band = bandVm(makeHome())
    expect(band.weekNext).toEqual([{ when: "Today", what: "Vectors" }, { when: "Friday", what: "Paper 4" }])
    expect(band.recent).toHaveLength(3)
    expect(band.recent[1]).toMatchObject({ grade: "C", title: "Physics · Paper 6", sub: "27/40 · last week" })
    expect(band.classRows.map((r) => r.kind)).toEqual(["teacher", "homework"])
  })

  it("homeView puts it together", () => {
    const vm = homeView(makeHome({ nextExamOn: null }), NONE)
    expect(vm.firstRun).toBe(false)
    expect(vm.heading).toBe("Morning, Mariam")
    expect(vm.stage.kind).toBe("morning")
    expect(vm.exam).toBeNull()
  })
})
