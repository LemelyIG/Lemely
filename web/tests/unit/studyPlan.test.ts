import { describe, expect, it } from "vitest"
import type {
  CurrentStudyPlanDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
} from "@/lib/studyPlanTypes"
import {
  activityLabel,
  formatDayHeading,
  formatDuration,
  groupSessionsByDay,
  planUnavailableMessage,
  studyPlanView,
  weekProgress,
} from "@/portals/student/screens/studyplan/studyPlanData"

/*
 * Unit tests for S-24's pure decision logic (`studyPlanData.ts`). Every
 * assertion here carries its inverse — a test that only proves the happy
 * branch cannot tell "the code does the right thing" from "the code does one
 * thing unconditionally", which is exactly how D4.13's three-state contract
 * could die silently at the screen.
 */

function session(overrides: Partial<StudyPlanSessionDTO> = {}): StudyPlanSessionDTO {
  return {
    id: "s1",
    date: "2026-08-10",
    topic: "1.2 Motion",
    activityType: "practice",
    durationMinutes: 45,
    focus: "Practice questions: 1.2 Motion",
    completedAt: null,
    ...overrides,
  }
}

function week(overrides: Partial<StudyPlanWeekDTO> = {}): StudyPlanWeekDTO {
  return {
    id: "p1",
    subjectCode: "0625",
    weekStart: "2026-08-10",
    weeklyHours: 5,
    available: true,
    reason: null,
    generatedAt: "2026-08-10T06:00:00Z",
    sessions: [],
    ...overrides,
  }
}

describe("studyPlanView — the three wire states stay three states", () => {
  it("reports notGenerated when no plan exists for this week", () => {
    const current: CurrentStudyPlanDTO = { generated: false, plan: null }
    expect(studyPlanView(current).kind).toBe("notGenerated")
  })

  it("reports refused — not notGenerated — for a generated no_signal plan", () => {
    const plan = week({ available: false, reason: "no_signal" })
    const view = studyPlanView({ generated: true, plan })
    // The inverse of the test above: a refusal was *generated*, so collapsing
    // it into "you have no plan yet" would tell the student to build a plan
    // that the planner has already declined to build.
    expect(view.kind).toBe("refused")
    expect(view.kind === "refused" && view.reason).toBe("no_signal")
  })

  it("reports plan — not refused — for an available plan with zero sessions", () => {
    const view = studyPlanView({ generated: true, plan: week({ available: true, sessions: [] }) })
    // The state D4.13 exists to preserve: there *was* something to evaluate
    // and nothing to schedule. Indistinguishable from a refusal if the view
    // keyed off `sessions.length`.
    expect(view.kind).toBe("plan")
  })

  it("reports plan for a populated available plan", () => {
    const view = studyPlanView({ generated: true, plan: week({ sessions: [session()] }) })
    expect(view.kind).toBe("plan")
  })

  it("treats generated:true with a null plan as notGenerated rather than throwing", () => {
    expect(studyPlanView({ generated: true, plan: null }).kind).toBe("notGenerated")
  })
})

describe("planUnavailableMessage", () => {
  it("names the three signals for no_signal", () => {
    const message = planUnavailableMessage("no_signal")
    expect(message.heading).toBe("Not enough to plan from yet")
    expect(message.body).toContain("placement")
  })

  it("names an unrecognised reason rather than hiding it", () => {
    const message = planUnavailableMessage("some_future_reason")
    expect(message.body).toContain("some_future_reason")
  })

  it("does not print the word null when there is no reason", () => {
    expect(planUnavailableMessage(null).body).not.toContain("null")
  })
})

describe("weekProgress — planned and stated are two different facts", () => {
  it("keeps planned minutes below stated minutes rather than reporting the stated figure", () => {
    // 5 stated hours = 300 minutes; the scheduler placed 90 of them. Reporting
    // 300 as planned would claim time was scheduled that never was (P4.7
    // chunk A's 270-of-600 defect, one layer up).
    const progress = weekProgress(
      week({ weeklyHours: 5, sessions: [session({ durationMinutes: 45 }), session({ id: "s2", durationMinutes: 45 })] }),
    )
    expect(progress.statedMinutes).toBe(300)
    expect(progress.plannedMinutes).toBe(90)
  })

  it("counts completion in minutes, not in sessions", () => {
    const progress = weekProgress(
      week({
        sessions: [
          session({ id: "a", durationMinutes: 90, completedAt: "2026-08-10T10:00:00Z" }),
          session({ id: "b", durationMinutes: 30, completedAt: null }),
        ],
      }),
    )
    expect(progress.completedMinutes).toBe(90)
    expect(progress.completedCount).toBe(1)
    expect(progress.percentComplete).toBe(75) // 90/120, not 50% by session count
  })

  it("returns 0 percent and not NaN for an empty week", () => {
    const progress = weekProgress(week({ sessions: [] }))
    expect(progress.percentComplete).toBe(0)
    expect(Number.isNaN(progress.percentComplete)).toBe(false)
  })

  it("does not call an empty week fully complete", () => {
    // The inverse of the test below. `completed.length === sessions.length` is
    // vacuously true at zero, which would congratulate a student on a week
    // that never had anything in it.
    expect(weekProgress(week({ sessions: [] })).fullyComplete).toBe(false)
  })

  it("calls a week fully complete only when every session is done", () => {
    const done = session({ completedAt: "2026-08-10T10:00:00Z" })
    expect(weekProgress(week({ sessions: [done] })).fullyComplete).toBe(true)
    expect(
      weekProgress(week({ sessions: [done, session({ id: "s2", completedAt: null })] })).fullyComplete,
    ).toBe(false)
  })
})

describe("groupSessionsByDay", () => {
  it("orders days ascending and keeps each day's sessions together", () => {
    const days = groupSessionsByDay([
      session({ id: "c", date: "2026-08-12" }),
      session({ id: "a", date: "2026-08-10" }),
      session({ id: "b", date: "2026-08-10" }),
    ])
    expect(days.map((d) => d.date)).toEqual(["2026-08-10", "2026-08-12"])
    expect(days[0].sessions.map((s) => s.id)).toEqual(["a", "b"])
  })

  it("sorts across a month boundary, where lexicographic and numeric order agree", () => {
    const days = groupSessionsByDay([
      session({ id: "sep", date: "2026-09-01" }),
      session({ id: "aug", date: "2026-08-31" }),
    ])
    expect(days.map((d) => d.date)).toEqual(["2026-08-31", "2026-09-01"])
  })

  it("synthesises no empty days", () => {
    // A 7-day grid would need Tue/Wed/Thu rows invented here. The plan is what
    // the scheduler produced; an absence is not a decision to display.
    const days = groupSessionsByDay([
      session({ id: "mon", date: "2026-08-10" }),
      session({ id: "fri", date: "2026-08-14" }),
    ])
    expect(days).toHaveLength(2)
  })

  it("returns an empty list for no sessions", () => {
    expect(groupSessionsByDay([])).toEqual([])
  })
})

describe("labels and formatting", () => {
  it("maps the four activity types to the spec's vocabulary", () => {
    expect(activityLabel("practice")).toBe("Practice set")
    expect(activityLabel("flashcards")).toBe("Flashcards")
    expect(activityLabel("past_paper")).toBe("Past paper")
    expect(activityLabel("review")).toBe("Revision")
  })

  it("renders an unknown activity verbatim rather than mapping it onto a known one", () => {
    expect(activityLabel("some_future_activity")).toBe("some_future_activity")
  })

  it("formats durations without a bare 0m hour remainder", () => {
    expect(formatDuration(45)).toBe("45m")
    expect(formatDuration(60)).toBe("1h")
    expect(formatDuration(95)).toBe("1h 35m")
    expect(formatDuration(0)).toBe("0m")
  })

  it("formats a bare ISO date on the day it says, not the day before", () => {
    // `new Date("2026-08-10")` is UTC midnight and renders as the 9th west of
    // Greenwich. The heading must name the 10th in every timezone.
    expect(formatDayHeading("2026-08-10")).toContain("10")
  })

  it("returns the raw string for an unparseable date rather than Invalid Date", () => {
    expect(formatDayHeading("not-a-date")).toBe("not-a-date")
  })
})
