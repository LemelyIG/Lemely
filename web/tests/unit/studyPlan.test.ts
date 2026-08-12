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
  locateSession,
  planUnavailableMessage,
  rationaleCopy,
  sessionRationale,
  sessionStartAction,
  studyPlanView,
  weekProgress,
} from "@/portals/student/screens/studyplan/studyPlanData"
import { resolveCrumb } from "@/portals/student/data"

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

// ── S-25 · locating a session with no route that fetches one ─────────────

describe("locateSession", () => {
  const target = session({ id: "sess-42", topic: "4.3 Electric circuits" })

  it("finds a session that is in the current week", () => {
    const current: CurrentStudyPlanDTO = {
      generated: true,
      plan: week({ sessions: [session({ id: "other" }), target] }),
    }
    const located = locateSession(current, "sess-42")
    expect(located.kind).toBe("found")
    expect(located.kind === "found" && located.session.topic).toBe("4.3 Electric circuits")
  })

  it("reports notInCurrentWeek — not an error — for an id the week does not hold", () => {
    // A rebuild supersedes rather than mutates, so a bookmarked link lands
    // here legitimately. The inverse of the test above: same plan, different
    // id, and the difference must show up in the arm.
    const current: CurrentStudyPlanDTO = { generated: true, plan: week({ sessions: [target] }) }
    expect(locateSession(current, "sess-99").kind).toBe("notInCurrentWeek")
  })

  it("reports noCurrentPlan when the week was never generated", () => {
    expect(locateSession({ generated: false, plan: null }, "sess-42").kind).toBe("noCurrentPlan")
  })

  it("reports noCurrentPlan — carrying the refusal — for a refused week", () => {
    // Kept distinct from notInCurrentWeek so the screen can render the
    // planner's own reason instead of "your plan moved on", which would be
    // false here: it never moved, it was refused.
    const located = locateSession(
      { generated: true, plan: week({ available: false, reason: "no_signal" }) },
      "sess-42",
    )
    expect(located.kind).toBe("noCurrentPlan")
    expect(located.kind === "noCurrentPlan" && located.view.kind).toBe("refused")
  })

  it("does not find a session in a refused plan even if the id matches", () => {
    // A refused plan carries no sessions today, but keying the search off the
    // sessions array alone would silently resurrect one if it ever did.
    const located = locateSession(
      { generated: true, plan: week({ available: false, reason: "no_signal", sessions: [target] }) },
      "sess-42",
    )
    expect(located.kind).not.toBe("found")
  })
})

// ── S-25 · the "why", and the absence-of-evidence trap ───────────────────

describe("sessionRationale", () => {
  it("calls a topic a recorded weakness when it is in the weak-topic list", () => {
    expect(sessionRationale("1.2 Motion", ["1.2 Motion", "4.3 Electric circuits"]).kind).toBe(
      "recordedWeakness",
    )
  })

  it("says not-a-recorded-weakness when the list is known and excludes the topic", () => {
    expect(sessionRationale("1.2 Motion", ["4.3 Electric circuits"]).kind).toBe(
      "notRecordedWeakness",
    )
  })

  it("says not-a-recorded-weakness for a known-but-empty list", () => {
    // An empty list is an answer ("you have no recorded weak topics"), not a
    // missing one. Folding it into `unknown` would refuse to say something
    // true.
    expect(sessionRationale("1.2 Motion", []).kind).toBe("notRecordedWeakness")
  })

  it("says unknown — never not-a-weakness — when the list has not arrived", () => {
    // The load-bearing one. `undefined` is pending-or-failed; answering
    // "not a recorded weakness" there reports an absence of evidence as
    // evidence of absence, about a student who may well have that weakness.
    expect(sessionRationale("1.2 Motion", undefined).kind).toBe("unknown")
    expect(sessionRationale("1.2 Motion", undefined).kind).not.toBe("notRecordedWeakness")
  })

  it("matches the taxonomy label exactly rather than loosely", () => {
    // Both sides come from the P4.2 `"<code> <name>"` vocabulary (D4.4), so a
    // fuzzy match could only ever manufacture agreement — e.g. claiming a
    // session on "1.2 Motion" is covered by a weakness on "1 Motion, forces…".
    expect(sessionRationale("1.2 Motion", ["1 Motion, forces and energy"]).kind).toBe(
      "notRecordedWeakness",
    )
  })
})

describe("rationaleCopy", () => {
  it("never renders the session's focus string as a reason", () => {
    // `focus` is `"<activity label>: <topic>"` server-side — a restatement of
    // two fields already on screen. Putting it under a "why this session"
    // heading would launder a label into a rationale.
    const focus = session().focus
    for (const kind of ["recordedWeakness", "notRecordedWeakness", "unknown"] as const) {
      const copy = rationaleCopy({ kind }, "1.2 Motion")
      expect(copy.body).not.toContain(focus)
    }
  })

  it("does not name a driving signal when the topic is not a recorded weakness", () => {
    // The planner weighs placement and confidence too and does not record
    // which one produced a session. The copy must say that, not pick one.
    const body = rationaleCopy({ kind: "notRecordedWeakness" }, "1.2 Motion").body
    expect(body).toContain("not recorded")
  })

  it("gives the unknown arm its own copy rather than reusing either answer", () => {
    const unknown = rationaleCopy({ kind: "unknown" }, "1.2 Motion").body
    expect(unknown).not.toBe(rationaleCopy({ kind: "notRecordedWeakness" }, "1.2 Motion").body)
    expect(unknown).not.toBe(rationaleCopy({ kind: "recordedWeakness" }, "1.2 Motion").body)
  })
})

// ── S-25 · the start action, including the one that must not exist ───────

describe("sessionStartAction", () => {
  it("routes practice and flashcards to their subject-scoped screens", () => {
    expect(sessionStartAction("practice", "0625")?.path).toBe("/student/practice/0625")
    expect(sessionStartAction("flashcards", "0625")?.path).toBe("/student/flashcards/0625")
  })

  it("routes past_paper to the correction screen, which is not subject-scoped", () => {
    expect(sessionStartAction("past_paper", "0625")?.path).toBe("/student/correct")
  })

  it("returns null for review — this product has no revision surface", () => {
    // The inverse of the three above. A button here would navigate nowhere;
    // shipping none is the same call chunk A made for reschedule.
    expect(sessionStartAction("review", "0625")).toBeNull()
  })

  it("returns null for an activity type this build does not know", () => {
    expect(sessionStartAction("meditation", "0625")).toBeNull()
  })
})

// ── The breadcrumb arm for the subject-scoped plan route ─────────────────
//
// `resolveCrumb` was moved out of `portals/student/index.tsx` into the pure
// `data.ts` in P4.10 chunk A specifically so these can exist. While it sat in
// the React module it was unreachable from this suite, and that is exactly how
// the new `/student/plan/:subjectCode` route came to fall through every arm and
// render a bare "Home": the crumb map still held the pre-P4.10 `/student/plan`
// key, which no pathname can hit any more. A wrong-but-valid breadcrumb trips
// no typecheck, no axe rule and no threshold, so only a test catches it.

describe("resolveCrumb", () => {
  it("names the study plan for the subject-scoped route", () => {
    expect(resolveCrumb("/student/plan/0625")).toBe("Home / Study plan / 0625")
  })

  it("does not fall through to the bare Home default for the plan route", () => {
    // The inverse of the arm above, stated separately: the defect was not a
    // wrong label, it was silently landing on the catch-all.
    expect(resolveCrumb("/student/plan/0580")).not.toBe("Home")
  })

  it("no longer resolves the pre-P4.10 subjectless plan path to a plan crumb", () => {
    // `/student/plan` is not a route any more. It must not keep answering with
    // a plan breadcrumb, or a dead link would look live.
    expect(resolveCrumb("/student/plan")).toBe("Home")
  })

  it("still resolves the exact-match routes and the other dynamic arms", () => {
    expect(resolveCrumb("/student")).toBe("Home")
    expect(resolveCrumb("/student/correct")).toBe("Marking / Correct a paper")
    expect(resolveCrumb("/student/practice/0625")).toBe("Home / Practice / 0625")
    expect(resolveCrumb("/student/flashcards/0625")).toBe("Home / Flashcards / 0625")
  })

  it("names the S-25 session route instead of falling through", () => {
    // `planMatch` is anchored, so the session route would have repeated the
    // chunk-A defect exactly: a wrong-but-valid breadcrumb that no gate sees.
    expect(resolveCrumb("/student/plan/0625/session/abc-123")).toBe(
      "Home / Study plan / 0625 / Session",
    )
  })

  it("does not land the session route on the bare Home default", () => {
    expect(resolveCrumb("/student/plan/0625/session/abc-123")).not.toBe("Home")
  })

  it("keeps the week route and the session route on different crumbs", () => {
    // Both are real screens. A shared crumb would tell the student they had
    // not moved.
    expect(resolveCrumb("/student/plan/0625/session/abc-123")).not.toBe(
      resolveCrumb("/student/plan/0625"),
    )
  })

  it("returns Home for an unknown path rather than throwing", () => {
    expect(resolveCrumb("/student/nothing/here/at/all")).toBe("Home")
  })
})
