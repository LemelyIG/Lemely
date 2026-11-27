import { describe, expect, it } from "vitest"
import { patchCurrentSession, patchOverviewSession } from "@/lib/studyPlanCache"
import type {
  CurrentStudyPlanDTO,
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
} from "@/lib/studyPlanTypes"

const s = (id: string, date: string, extra: Partial<StudyPlanSessionDTO> = {}): StudyPlanSessionDTO => ({
  id,
  date,
  topic: "Vectors",
  activityType: "practice",
  durationMinutes: 10,
  focus: "",
  completedAt: null,
  anyDay: false,
  reason: null,
  ...extra,
})

const overview = (sessions: StudyPlanSessionDTO[]): StudyPlanOverviewDTO => ({
  today: "2026-08-06",
  weekStart: "2026-08-03",
  weekEnd: "2026-08-09",
  subjects: [
    {
      subjectCode: "0580",
      generated: true,
      paperCount: 4,
      weakTopics: [],
      plan: {
        id: "p1",
        subjectCode: "0580",
        weekStart: "2026-08-03",
        weeklyHours: 2,
        available: true,
        reason: null,
        generatedAt: "2026-08-03T09:00:00Z",
        sessions,
      },
    },
    { subjectCode: "0625", generated: false, plan: null, paperCount: 0, weakTopics: [] },
  ],
})

describe("patchOverviewSession", () => {
  it("replaces the matching session with the server's copy", () => {
    const before = overview([s("a", "2026-08-06", { reason: { kind: "marks_lost", count: 9 } })])
    const server = s("a", "2026-08-06", { completedAt: "2026-08-06T10:00:00Z" })
    const after = patchOverviewSession(before, server)!
    const patched = after.subjects[0].plan!.sessions[0]
    expect(patched.completedAt).toBe("2026-08-06T10:00:00Z")
    // The server sends reason null on complete/move; the computed one stays.
    expect(patched.reason).toEqual({ kind: "marks_lost", count: 9 })
  })

  it("re-sorts by date after a move", () => {
    const before = overview([s("a", "2026-08-06"), s("b", "2026-08-07")])
    const after = patchOverviewSession(before, s("a", "2026-08-09"))!
    expect(after.subjects[0].plan!.sessions.map((x) => x.id)).toEqual(["b", "a"])
  })

  it("returns the same object when the id is not in the week", () => {
    const before = overview([s("a", "2026-08-06")])
    expect(patchOverviewSession(before, s("zzz", "2026-08-06"))).toBe(before)
  })

  it("passes undefined through", () => {
    expect(patchOverviewSession(undefined, s("a", "2026-08-06"))).toBeUndefined()
  })
})

describe("patchCurrentSession", () => {
  it("patches a per-subject plan and leaves a missing plan alone", () => {
    const current: CurrentStudyPlanDTO = { generated: true, plan: overview([s("a", "2026-08-06")]).subjects[0].plan }
    const after = patchCurrentSession(current, s("a", "2026-08-06", { completedAt: "x" }))!
    expect(after.plan!.sessions[0].completedAt).toBe("x")
    const none: CurrentStudyPlanDTO = { generated: false, plan: null }
    expect(patchCurrentSession(none, s("a", "2026-08-06"))).toBe(none)
  })
})
