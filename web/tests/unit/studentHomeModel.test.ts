import { describe, expect, it } from "vitest"
import {
  binnyMood,
  deriveNextAction,
  localISODate,
  streakStrip,
  todayList,
  type HomeFacts,
} from "@/portals/student/home/model"

// 2026-11-05 10:00 local time. Every date below is local, so the tests do not
// depend on the machine's time zone.
const NOW = new Date(2026, 10, 5, 10, 0)
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString()

function facts(over: Partial<HomeFacts> = {}): HomeFacts {
  return {
    now: NOW,
    activeUpload: null,
    subjects: [
      { code: "0580", papers: 14, grade: "A", previousGrade: "B", nextExamOn: "2027-05-12" },
      { code: "0625", papers: 2, grade: "C", previousGrade: "D", nextExamOn: "2027-05-04" },
    ],
    upcomingSessions: [],
    weakTopics: [
      { topic: "Vectors", subjectCode: "0580", acc: 63 },
      { topic: "Waves", subjectCode: "0625", acc: 54 },
    ],
    latestResult: null,
    calendar: [],
    ...over,
  }
}

const session = (id: string, code: string, day: string) => ({
  sessionId: id,
  subjectCode: code,
  title: `Session ${id}`,
  minutes: 20,
  scheduledFor: day,
})

describe("localISODate", () => {
  it("formats the local calendar date with zero padding", () => {
    expect(localISODate(new Date(2026, 0, 3, 23, 59))).toBe("2026-01-03")
  })
})

describe("deriveNextAction", () => {
  it("1. marking in progress wins over everything", () => {
    const a = deriveNextAction(
      facts({ activeUpload: { paperLabel: "0580/42" }, upcomingSessions: [session("s1", "0580", "2026-11-05")] }),
    )
    expect(a).toEqual({ kind: "marking", paperLabel: "0580/42", to: "/student/correct" })
  })

  it("2. a session due today is next", () => {
    const a = deriveNextAction(facts({ upcomingSessions: [session("s1", "0606", "2026-11-05")] }))
    expect(a.kind).toBe("session")
    expect(a.to).toBe("/student/plan/0606/session/s1")
  })

  it("2. an overdue session counts as due", () => {
    expect(deriveNextAction(facts({ upcomingSessions: [session("s0", "0580", "2026-11-01")] })).kind).toBe("session")
  })

  it("2. a session scheduled for tomorrow is not due", () => {
    expect(deriveNextAction(facts({ upcomingSessions: [session("s2", "0580", "2026-11-06")] })).kind).toBe("practice")
  })

  it("3. no papers means the first-paper action", () => {
    const a = deriveNextAction(facts({ subjects: [], weakTopics: [] }))
    expect(a).toEqual({ kind: "first-paper", to: "/student/correct" })
  })

  it("3. subjects with zero papers also mean the first-paper action", () => {
    const subjects = [{ code: "0580", papers: 0, grade: "U", previousGrade: null, nextExamOn: null }]
    expect(deriveNextAction(facts({ subjects })).kind).toBe("first-paper")
  })

  it("4. otherwise the weakest topic is practised", () => {
    const a = deriveNextAction(facts())
    expect(a.kind).toBe("practice")
    if (a.kind === "practice") expect(a.topic.topic).toBe("Waves")
    expect(a.to).toBe("/student/practice/0625")
  })

  it("5. with no weak topics the fallback is correct another paper", () => {
    expect(deriveNextAction(facts({ weakTopics: [] }))).toEqual({ kind: "correct", to: "/student/correct" })
  })

  it("preferClosestExam picks the due session for the subject with the closest exam", () => {
    const f = facts({
      upcomingSessions: [session("s1", "0580", "2026-11-05"), session("s2", "0625", "2026-11-05")],
    })
    const closest = deriveNextAction(f, { preferClosestExam: true })
    const plain = deriveNextAction(f)
    expect(closest.kind === "session" ? closest.session.sessionId : null).toBe("s2")
    expect(plain.kind === "session" ? plain.session.sessionId : null).toBe("s1")
  })

  it("preferClosestExam picks practice in the subject with the closest exam", () => {
    const f = facts({
      weakTopics: [
        { topic: "Vectors", subjectCode: "0580", acc: 40 },
        { topic: "Waves", subjectCode: "0625", acc: 54 },
      ],
    })
    const a = deriveNextAction(f, { preferClosestExam: true })
    expect(a.kind === "practice" && a.topic.topic).toBe("Waves")
  })
})

describe("todayList", () => {
  it("starts with the same action deriveNextAction returns", () => {
    const cases: HomeFacts[] = [
      facts(),
      facts({ activeUpload: { paperLabel: "0580/42" } }),
      facts({ upcomingSessions: [session("s1", "0580", "2026-11-05")] }),
      facts({ subjects: [], weakTopics: [] }),
      facts({ weakTopics: [] }),
    ]
    for (const f of cases) expect(todayList(f)[0]).toEqual(deriveNextAction(f))
  })

  it("caps the list at three items", () => {
    const f = facts({
      activeUpload: { paperLabel: "0580/42" },
      upcomingSessions: [session("s1", "0580", "2026-11-05"), session("s2", "0625", "2026-11-04")],
    })
    expect(todayList(f).map((a) => a.kind)).toEqual(["marking", "session", "session"])
  })

  it("lists session, practice, correct for a typical day", () => {
    const f = facts({ upcomingSessions: [session("s1", "0580", "2026-11-05")] })
    expect(todayList(f).map((a) => a.kind)).toEqual(["session", "practice", "correct"])
  })

  it("a new student gets only the first-paper action", () => {
    expect(todayList(facts({ subjects: [], weakTopics: [] })).map((a) => a.kind)).toEqual(["first-paper"])
  })

  it("never offers a first paper while one is being marked", () => {
    const f = facts({ subjects: [], weakTopics: [], activeUpload: { paperLabel: "0580/42" } })
    expect(todayList(f).map((a) => a.kind)).toEqual(["marking"])
  })
})

describe("binnyMood", () => {
  it("marking in progress", () => {
    expect(binnyMood(facts({ activeUpload: { paperLabel: "0580/42" } }))).toBe("marking")
  })

  it("grade improved: result in the last 24 h above the previous grade", () => {
    const latestResult = { subjectCode: "0580", grade: "A", recordedAt: hoursAgo(16) }
    expect(binnyMood(facts({ latestResult }))).toBe("grade-improved")
  })

  it("paper marked: result in the last 24 h, same grade as before", () => {
    const subjects = [{ code: "0580", papers: 14, grade: "A", previousGrade: "A", nextExamOn: null }]
    const latestResult = { subjectCode: "0580", grade: "A", recordedAt: hoursAgo(2) }
    expect(binnyMood(facts({ subjects, latestResult }))).toBe("paper-marked")
  })

  it("paper marked: first paper in a subject has no previous grade", () => {
    const subjects = [{ code: "0580", papers: 1, grade: "B", previousGrade: null, nextExamOn: null }]
    const latestResult = { subjectCode: "0580", grade: "B", recordedAt: hoursAgo(2) }
    expect(binnyMood(facts({ subjects, latestResult }))).toBe("paper-marked")
  })

  it("a result older than 24 h no longer counts", () => {
    const latestResult = { subjectCode: "0580", grade: "A", recordedAt: hoursAgo(25) }
    expect(binnyMood(facts({ latestResult }))).toBe("idle")
  })

  it("streak kept: XP earned today", () => {
    expect(binnyMood(facts({ calendar: [{ day: "2026-11-05", xp: 30 }] }))).toBe("streak-kept")
  })

  it("zero XP today is not a kept streak", () => {
    expect(binnyMood(facts({ calendar: [{ day: "2026-11-05", xp: 0 }] }))).toBe("idle")
  })

  it("idle otherwise", () => {
    expect(binnyMood(facts({ calendar: [{ day: "2026-11-04", xp: 30 }] }))).toBe("idle")
  })
})

describe("streakStrip", () => {
  it("returns the last 7 local days, oldest first, with today last", () => {
    const strip = streakStrip([{ day: "2026-11-05", xp: 20 }, { day: "2026-11-01", xp: 5 }], NOW)
    expect(strip.map((d) => d.day)).toEqual([
      "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
    ])
    expect(strip.map((d) => d.earned)).toEqual([false, false, true, false, false, false, true])
    expect(strip[6].isToday).toBe(true)
    expect(strip.filter((d) => d.isToday)).toHaveLength(1)
  })

  it("days missing from the calendar have zero XP", () => {
    expect(streakStrip([], NOW).every((d) => d.xp === 0 && !d.earned)).toBe(true)
  })
})
