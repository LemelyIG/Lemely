/*
 * TS interfaces mirroring `lemely/web/schemas_study_plan.py` (the *persisted*
 * adaptive study-plan routes, P4.7 chunk C / D4.13). Field names are camelCase
 * to match the wire, following `practiceTypes.ts`/`placementTypes.ts`.
 *
 * **These are the only study-plan types.** The legacy
 * `StudyPlan`/`StudyPlanRequest` in `studentTypes.ts` mirrored
 * `GET`/`POST /api/student/plan`, which rebuilt an unpersisted plan on every
 * request and exposed neither a date nor an activity type. P4.10 chunk A
 * migrated the screen onto this surface and chunk D deleted that pair on both
 * sides of the wire (D4.22).
 */

/** The four activity types the scheduler can emit (`lemely.core.study.
 * ActivityType`). A session's activity is *earned* against the live bank and
 * the student's own decks (P4.7 chunk B) — it is a fact about what material
 * exists, not a label the screen may reinterpret. */
export type ActivityType = "practice" | "flashcards" | "past_paper" | "review"

/**
 * One scheduled session, as persisted.
 *
 * `focus` is `f"{activity label}: {topic}"` server-side — a restatement of
 * `activityType` and `topic`, **not** a rationale. Nothing on this type records
 * which of the planner's three signals (weakness / placement / confidence)
 * produced the session; see `sessionRationale` in `studyPlanData.ts` for the
 * one provable statement available, and do not render `focus` as a "why".
 *
 * `completedAt` is the P5 XP seam and nothing more — there is no points or
 * streak field here, and inventing one on the completion affordance is exactly
 * the fabricated precision UI spec §1.4 forbids (D4.17's precedent for S-23).
 */
export interface StudyPlanSessionDTO {
  id: string
  /** ISO `YYYY-MM-DD`, not a datetime — the scheduler places sessions on days. */
  date: string
  topic: string
  activityType: ActivityType
  durationMinutes: number
  focus: string
  completedAt: string | null
}

/**
 * One persisted weekly plan and its sessions.
 *
 * `available: true` with an empty `sessions` list is a **real and distinct**
 * state ("there was something to evaluate and nothing to schedule"), not the
 * same thing as `available: false` (`reason: "no_signal"` — nothing to evaluate
 * at all). Collapsing the two is the exact gap D4.13 closed at the wire, and it
 * would die here if this type were flattened.
 */
export interface StudyPlanWeekDTO {
  id: string
  subjectCode: string
  /** ISO `YYYY-MM-DD` — the Monday of the plan's ISO week. */
  weekStart: string
  /** The student's own stated weekly study time (`StudentProfile.
   * weekly_study_hours`), not a figure derived from the sessions. Progress is
   * measured against this; the sessions' own total is summed from
   * `durationMinutes`. */
  weeklyHours: number
  available: boolean
  reason: string | null
  generatedAt: string
  sessions: StudyPlanSessionDTO[]
}

/**
 * `GET /api/student/study-plan/{subjectCode}` — three distinguishable states,
 * **none of which is a 404**:
 *
 * 1. `{generated: false, plan: null}` — no plan generated for this ISO week.
 * 2. `{generated: true, plan: {available: false, reason: "no_signal", …}}` —
 *    generated, and honestly refused.
 * 3. `{generated: true, plan: {available: true, …}}` — a real plan, whose
 *    `sessions` may still legitimately be empty.
 */
export interface CurrentStudyPlanDTO {
  generated: boolean
  plan: StudyPlanWeekDTO | null
}

/** Request body for `POST /api/student/study-plan` (201). The caller is always
 * the authenticated student server-side — no student id is sent. */
export interface CreateStudyPlanRequest {
  subjectCode: string
}
