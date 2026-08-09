/*
 * Pure data + decision logic for S-24 (study plan, week view). No React, no
 * DOM — exercised directly by `web/tests/unit/studyPlan.test.ts`, the same
 * split as `practiceData.ts` and `flashcardData.ts` (D3.20: `vitest.config.ts`
 * runs unit-only, no jsdom).
 */

import type {
  ActivityType,
  CurrentStudyPlanDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
} from "@/lib/studyPlanTypes"

// ── The three wire states stay three states (D4.13) ─────────────────────

/**
 * S-24's render decision as one discriminated union, one arm per
 * `CurrentStudyPlanDTO` state.
 *
 * The whole substance of D4.13 was making these distinguishable at the wire
 * after they had all arrived as an empty `sessions` list. `"notGenerated"`
 * ("you have no plan for this week yet"), `"refused"` ("we looked and had
 * nothing to go on") and `"plan"` with zero sessions ("we looked, and there
 * was nothing to schedule") are three different facts about the student, and
 * flattening any two of them back together here would kill that work one layer
 * below where it was done. **None of them is an error and none is a 404.**
 */
export type StudyPlanView =
  | { kind: "notGenerated" }
  | { kind: "refused"; reason: string | null; plan: StudyPlanWeekDTO }
  | { kind: "plan"; plan: StudyPlanWeekDTO }

export function studyPlanView(current: CurrentStudyPlanDTO): StudyPlanView {
  if (!current.generated || !current.plan) return { kind: "notGenerated" }
  if (!current.plan.available) {
    return { kind: "refused", reason: current.plan.reason, plan: current.plan }
  }
  return { kind: "plan", plan: current.plan }
}

export interface PlanUnavailableMessage {
  heading: string
  body: string
}

/** One specific message per refusal `reason`. Today the scheduler's only
 * refusal is `no_signal` (no weakness rows, no placement, no confidence
 * ratings — `lemely.core.study.StudyPlanUnavailableReason`); the fallback
 * branch only fires for a reason string this frontend has never seen, and
 * still names it rather than hiding it behind "something went wrong".
 * Mirrors `practiceUnavailableMessage`/`flashcardUnavailableMessage`. */
export function planUnavailableMessage(reason: string | null): PlanUnavailableMessage {
  switch (reason) {
    case "no_signal":
      return {
        heading: "Not enough to plan from yet",
        body: "A plan is built from three things: topics you have lost marks on, your placement test, and the confidence ratings you gave during onboarding. None of those is recorded for this subject yet, so there is nothing to schedule around — take the placement test or correct a paper, then rebuild.",
      }
    default:
      return {
        heading: "No plan could be built this week",
        body: reason
          ? `The planner declined to build a plan (reason: ${reason}).`
          : "The planner declined to build a plan for this week.",
      }
  }
}

// ── Week progress: two totals, never conflated ──────────────────────────

export interface WeekProgress {
  /** Minutes the student said they had (`weeklyHours` × 60) — their own
   * questionnaire answer, not anything derived from the sessions. */
  statedMinutes: number
  /** Minutes actually scheduled. May be **below** `statedMinutes`: the
   * scheduler caps a single session at 90 minutes and splits the remainder
   * across days, and a week can simply run out of topics worth scheduling
   * (P4.7 chunk A). Reporting `statedMinutes` as "planned" would be a lie the
   * student cannot see through. */
  plannedMinutes: number
  completedMinutes: number
  sessionCount: number
  completedCount: number
  /** Completed as a share of *planned*, 0–100, rounded. `0` when nothing is
   * planned — never `NaN`, and never 100 for a vacuously empty week. */
  percentComplete: number
  /** True only when there is at least one session and every one is done. An
   * empty week is not a complete week. */
  fullyComplete: boolean
}

export function weekProgress(plan: StudyPlanWeekDTO): WeekProgress {
  const sessions = plan.sessions
  const plannedMinutes = sessions.reduce((total, s) => total + s.durationMinutes, 0)
  const completed = sessions.filter((s) => s.completedAt !== null)
  const completedMinutes = completed.reduce((total, s) => total + s.durationMinutes, 0)
  return {
    statedMinutes: Math.round(plan.weeklyHours * 60),
    plannedMinutes,
    completedMinutes,
    sessionCount: sessions.length,
    completedCount: completed.length,
    percentComplete: plannedMinutes === 0 ? 0 : Math.round((completedMinutes / plannedMinutes) * 100),
    fullyComplete: sessions.length > 0 && completed.length === sessions.length,
  }
}

// ── Day grouping (S-24: "the current week laid out by day") ─────────────

export interface StudyPlanDay {
  /** ISO `YYYY-MM-DD`, exactly as it arrived on the wire. */
  date: string
  sessions: StudyPlanSessionDTO[]
}

/**
 * Group sessions into days, ascending by date.
 *
 * Sorts by the raw ISO string rather than parsing to `Date`: `YYYY-MM-DD`
 * sorts lexicographically in calendar order, and parsing would drag the
 * browser's timezone into a value that has no time component — a UTC-negative
 * offset shifts a bare `YYYY-MM-DD` back onto the previous day and would
 * silently file Monday's session under Sunday.
 *
 * Days with no sessions are **not** synthesised. The plan is what the
 * scheduler produced; inventing empty Tuesday/Thursday rows to fill a 7-day
 * grid would present an absence as a decision.
 */
export function groupSessionsByDay(sessions: readonly StudyPlanSessionDTO[]): StudyPlanDay[] {
  const byDate = new Map<string, StudyPlanSessionDTO[]>()
  for (const session of sessions) {
    const bucket = byDate.get(session.date)
    if (bucket) bucket.push(session)
    else byDate.set(session.date, [session])
  }
  return [...byDate.keys()]
    .sort((a, b) => a.localeCompare(b))
    .map((date) => ({ date, sessions: byDate.get(date)! }))
}

// ── S-25: locating one session inside the week ──────────────────────────

/**
 * Where a session id resolves to, given the current week.
 *
 * **There is no `GET /sessions/{id}` route** — the router has exactly three
 * paths and none fetches a single session. S-25 therefore reads the week and
 * locates the session in it, which makes "not in this week" a state this
 * function has to name rather than something the network reports.
 *
 * `"notInCurrentWeek"` is **not an error and not a 404.** Regeneration
 * supersedes (P4.7 chunk B stamps `superseded_at` rather than mutating), so a
 * bookmarked link, an open tab from last week, or a link followed while a
 * rebuild was in flight all land here legitimately. Rendering it as "not
 * found" would tell the student their data is missing when in fact their plan
 * moved on.
 */
export type SessionLocation =
  | { kind: "found"; session: StudyPlanSessionDTO; plan: StudyPlanWeekDTO }
  /** A real plan exists for this week and this id is not one of its sessions. */
  | { kind: "notInCurrentWeek"; plan: StudyPlanWeekDTO }
  /** No usable plan this week at all — never generated, or generated and
   * refused. Kept separate from the arm above because the honest next step
   * differs: there is a plan to go back to in one case and not in the other. */
  | { kind: "noCurrentPlan"; view: StudyPlanView }

export function locateSession(current: CurrentStudyPlanDTO, sessionId: string): SessionLocation {
  const view = studyPlanView(current)
  if (view.kind !== "plan") return { kind: "noCurrentPlan", view }
  const session = view.plan.sessions.find((s) => s.id === sessionId)
  if (!session) return { kind: "notInCurrentWeek", plan: view.plan }
  return { kind: "found", session, plan: view.plan }
}

// ── S-25: the one provable "why this session" ───────────────────────────

/**
 * Why this session is in the plan — or an honest statement that this build
 * cannot say.
 *
 * **Nothing per-session records which signal produced it.** The planner reads
 * three (`_weaknesses` / `_placement_results` / `_confidence_ratings`,
 * `study_plan_repo.py`), weights them, and discards them; `focus` is
 * `f"{activity label}: {topic}"` — a restatement of two fields already on
 * screen, not a rationale. Rendering `focus` under a "why this session"
 * heading would launder a label into a reason.
 *
 * The one thing that *is* provable: `GET /student/practice/{code}/topics`
 * returns `weakTopics`, and its `_weak_topics_for` query is byte-identical to
 * the planner's `_weaknesses` query (same select, same join, same where). So
 * "this is one of your recorded weak topics for this subject" is a fact about
 * the same rows the planner read, not an inference about this session.
 *
 * Hence three arms, and the third is the one that is easy to get wrong:
 * when the weak-topics list has not arrived (pending) or failed to load,
 * the answer is `"unknown"` — asserting `"notWeakness"` there would report an
 * absence of evidence as evidence of absence.
 *
 * @param weakTopics the student's recorded weak topics, or `undefined` when
 *   that list is not (yet) known. Matching is exact: both sides come from the
 *   P4.2 `"<code> <name>"` taxonomy and share one vocabulary by construction
 *   (D4.4), so a fuzzy match here would only ever manufacture agreement.
 */
export type SessionRationale =
  | { kind: "recordedWeakness" }
  | { kind: "notRecordedWeakness" }
  | { kind: "unknown" }

export function sessionRationale(
  topic: string,
  weakTopics: readonly string[] | undefined,
): SessionRationale {
  if (weakTopics === undefined) return { kind: "unknown" }
  return weakTopics.includes(topic)
    ? { kind: "recordedWeakness" }
    : { kind: "notRecordedWeakness" }
}

export interface RationaleCopy {
  heading: string
  body: string
}

export function rationaleCopy(rationale: SessionRationale, topic: string): RationaleCopy {
  switch (rationale.kind) {
    case "recordedWeakness":
      return {
        heading: "Why this is in your plan",
        body: `${topic} is one of your recorded weak topics for this subject — you have lost marks on it in work that has been marked. That is one of the three signals the planner weighs.`,
      }
    case "notRecordedWeakness":
      return {
        heading: "Why this is in your plan",
        // Deliberately does not guess. Placement and confidence are real
        // inputs, and which one drove *this* session is not recorded.
        body: `${topic} is not one of your recorded weak topics, so this session came from one of the planner's other two signals — your placement result or the confidence rating you gave it during onboarding. Which of the two is not recorded, so this page will not guess.`,
      }
    case "unknown":
      return {
        heading: "Why this is in your plan",
        body: "Your recorded weak topics could not be loaded, so this page cannot say whether this session came from a weakness, your placement result, or a confidence rating.",
      }
  }
}

// ── S-25: the start action ──────────────────────────────────────────────

export interface SessionStartAction {
  label: string
  path: string
}

/**
 * Where "start this session" goes, or `null` when nothing in this product can
 * serve the activity.
 *
 * `review` returns `null`: there is **no revision surface** — no route renders
 * notes or a topic write-up — so a button would be dead. Shipping no control
 * is the same call chunk A made for reschedule, and for the same reason: a
 * control that cannot do what it says is worse than an absent one.
 */
export function sessionStartAction(
  activityType: string,
  subjectCode: string,
): SessionStartAction | null {
  switch (activityType) {
    case "practice":
      return { label: "Go to practice", path: `/student/practice/${subjectCode}` }
    case "flashcards":
      return { label: "Go to flashcards", path: `/student/flashcards/${subjectCode}` }
    case "past_paper":
      return { label: "Correct a past paper", path: "/student/correct" }
    default:
      return null
  }
}

// ── Labels ──────────────────────────────────────────────────────────────

const ACTIVITY_LABELS: Record<ActivityType, string> = {
  practice: "Practice set",
  flashcards: "Flashcards",
  past_paper: "Past paper",
  review: "Revision",
}

/** Human label for an activity type, in the UI spec's own vocabulary
 * ("practice set, flashcards, past paper, revision"). An unrecognised value
 * from a future backend renders verbatim rather than being silently mapped
 * onto one of the four this build knows. */
export function activityLabel(activityType: string): string {
  return ACTIVITY_LABELS[activityType as ActivityType] ?? activityType
}

/** `95` → `"1h 35m"`, `60` → `"1h"`, `45` → `"45m"`, `0` → `"0m"`. Whole
 * minutes only — the wire carries an integer and no fractional minute exists
 * to round. */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
}

/** Format a bare ISO `YYYY-MM-DD` as a weekday + date heading.
 *
 * Parsed with an explicit `T00:00:00` local-time suffix. `new Date("2026-08-10")`
 * is parsed by spec as **UTC midnight**, which renders as the 9th for every
 * user west of Greenwich — the same timezone trap `groupSessionsByDay` avoids
 * by not parsing at all. An unparseable value returns the raw string rather
 * than "Invalid Date". */
export function formatDayHeading(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return isoDate
  return parsed.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" })
}
