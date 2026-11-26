/*
 * L9 · the small decisions the study plan screen makes that are not about what
 * the plan holds (that is `planModel`): which query state to act on, which
 * message a refused move gets, which url a filter or session lives at, what
 * each mutation does when it settles, and where a tap on the day strip scrolls
 * to. Pure, so they run without a DOM and a test can fail them.
 */

import type { QueryStateQuery } from "@/components/ui/query-state"
import { ApiError } from "@/lib/api"
import { studentActionFailureMessage } from "@/lib/studentOutcome"
import { COPY, movedToast } from "./planCopy"
import type { SessionVM } from "./planModel"

/**
 * The week query as the screen should see it. react-query reports a failed
 * refetch as `status: "error"` while `data` still holds the last good week;
 * showing the error panel then would trade a working plan for a dead end
 * (a 409 on a move refetches the week, and a dropped connection fails that
 * refetch). The week stays on screen. Only a week that never loaded is an error.
 */
export function gateWeek<T>(query: QueryStateQuery<T>): QueryStateQuery<T> {
  if (query.status === "error" && query.data !== undefined) return { ...query, status: "success", error: null }
  return query
}

/**
 * What a refused move says. The server tags a 409 with `code`: a rebuilt plan
 * (`superseded`) and an already-finished session (`completed`) each get their
 * own line, because the list has just been refreshed under the student.
 */
export function moveFailureMessage(error: unknown): string {
  const detail = error instanceof ApiError ? error.detail : undefined
  const code = typeof detail === "object" && detail !== null ? (detail as { code?: unknown }).code : undefined
  if (code === "superseded") return COPY.moveSuperseded
  if (code === "completed") return COPY.moveCompleted
  return COPY.moveError
}

/** The id of the plan list, the one element the subject chips control. */
export const PLAN_LIST_ID = "plan-list"
/**
 * What the subject chips `aria-controls`. Only the plan state draws the list, so every other state
 * (first run, need a paper, nothing scheduled, week done) gives the chips nothing to point at.
 */
export const chipsControl = (kind: string): string | undefined => (kind === "plan" ? PLAN_LIST_ID : undefined)
/** The list for a filter: `null` is all subjects. */
export const planListUrl = (filter: string | null): string => (filter ? `/student/plan/${filter}` : "/student/plan")

/** The same list with one session open. The filter stays, so back and close land where the student was. */
export const planSessionUrl = (filter: string | null, sessionId: string): string =>
  filter ? `/student/plan/${filter}/session/${sessionId}` : `/student/plan/session/${sessionId}`

/**
 * Where a tap on a day of the week strip scrolls. A day that is all done lives in the done
 * fold (which must be opened); a day with something missed is in the missed group; any other
 * day, including one with nothing on it, has its own heading.
 */
export function dayScrollTarget(
  all: Pick<SessionVM, "date" | "status">[],
  date: string,
): { id: string; opensDone: boolean } {
  const day = all.filter((s) => s.date === date)
  if (day.length > 0 && day.every((s) => s.status === "done")) return { id: "plan-done", opensDone: true }
  if (day.some((s) => s.status === "missed")) return { id: "plan-missed", opensDone: false }
  return { id: `plan-day-${date}`, opensDone: false }
}

/** The toast the screen raises, so a test can stand in for it. */
export type PlanToast = (toast: { title: string; variant: "success" | "error" }) => void

/**
 * Where opening a session goes. The url is the one place an open session lives: a wide screen
 * rewrites it in place (the panel follows, and a push or inbox link can name a session too, K44),
 * a narrow screen pushes it so the back gesture closes the sheet.
 */
export function openSessionNav(
  wide: boolean,
  filter: string | null,
  sessionId: string,
): { to: string; options: { replace: true } | { state: { fromList: true } } } {
  return {
    to: planSessionUrl(filter, sessionId),
    options: wide ? { replace: true } : { state: { fromList: true } },
  }
}

/**
 * What the url asks for that the screen must correct. A session this week's plan does not hold
 * is dropped with a note (K24/K25); a subject the student does not study falls back to all
 * subjects (K18), keeping a session that does exist (a link with a stale subject still lands on
 * its sheet). `missingNote`: true shows the note, false clears it (a session is open), null
 * leaves it be.
 */
export function planRoute(p: {
  subjectCode?: string
  sessionId?: string
  filter: string | null
  sessionKnown: boolean
}): { redirectTo: string | null; missingNote: boolean | null } {
  if (p.sessionId && !p.sessionKnown) return { redirectTo: planListUrl(p.filter), missingNote: true }
  if (p.subjectCode && p.filter === null) {
    return p.sessionId
      ? { redirectTo: planSessionUrl(null, p.sessionId), missingNote: false }
      : { redirectTo: planListUrl(null), missingNote: null }
  }
  return { redirectTo: null, missingNote: p.sessionId ? false : null }
}

/**
 * Every move button waits while any move runs: a second `mutate` would replace the first
 * call's callbacks, and its error toast would be lost.
 */
export const moveBusy = (movePending: boolean, movingAll: boolean): boolean => movePending || movingAll

/**
 * What one move does when it settles: confirm with the day, close the sheet that was open, or
 * say what the server refused. `closeSheet` is null when there is no sheet (the desktop panel
 * stays where it is).
 */
export function moveCallbacks(p: {
  date: string
  today: string
  toast: PlanToast
  closeSheet: (() => void) | null
}): { onSuccess: () => void; onError: (error: unknown) => void } {
  return {
    onSuccess: () => {
      p.toast({ title: movedToast(p.date, p.today), variant: "success" })
      p.closeSheet?.()
    },
    onError: (error) => p.toast({ title: moveFailureMessage(error), variant: "error" }),
  }
}

/** Move the missed sessions one after another. Stops at the first refusal; the buttons are always freed. */
export async function runMoveAll(p: {
  ids: string[]
  moveOne: (id: string) => Promise<unknown>
  setBusy: (busy: boolean) => void
  toast: PlanToast
}): Promise<void> {
  p.setBusy(true)
  try {
    for (const id of p.ids) await p.moveOne(id)
    p.toast({ title: COPY.movedToday, variant: "success" })
  } catch (error) {
    p.toast({ title: moveFailureMessage(error), variant: "error" })
  } finally {
    p.setBusy(false)
  }
}

/** Planning next week succeeded: the button settles, and a toast says so. */
export function nextWeekCallbacks(p: { setReady: (ready: boolean) => void; toast: PlanToast }): { onSuccess: () => void } {
  return {
    onSuccess: () => {
      p.setReady(true)
      p.toast({ title: COPY.nextWeekReady, variant: "success" })
    },
  }
}

/**
 * The confirm button of the rebuild dialog. With subjects it holds, the rebuild runs and the dialog
 * stays open, showing its pending state, until the mutation settles (`run` calls `onSettled` then,
 * success or failure; a failure is shown above the plan). With none there is nothing to wait for.
 */
export function confirmRebuild(
  codes: string[] | null,
  p: { run: (codes: string[], onSettled: () => void) => void; close: () => void },
): void {
  if (codes) p.run(codes, p.close)
  else p.close()
}
/**
 * Whether a rebuild of this week's plan has run on this screen. Planning next week uses the same
 * mutation but leaves this week's sessions alone, so it does not count.
 */
export const rebuiltHere = (rebuild: {
  isSuccess: boolean
  variables?: { subjectCodes: string[]; week?: "current" | "next" }
}): boolean =>
  rebuild.isSuccess && rebuild.variables?.week !== "next"

/**
 * The sentence for a failed rebuild, or null. Planning next week uses the same mutation, so the
 * wording follows the variables it was called with: a student who tapped "plan next week" is not
 * told their plan could not be rebuilt.
 */
export function rebuildFailure(rebuild: {
  isError: boolean
  error: unknown
  variables?: { subjectCodes: string[]; week?: "current" | "next" }
}): string | null {
  if (!rebuild.isError) return null
  return studentActionFailureMessage(rebuild.error, rebuild.variables?.week === "next" ? "plan next week" : "rebuild your plan")
}

/**
 * A rebuild failure belongs to the list it happened on, so another list starts clean. Only a
 * failure is cleared: resetting a rebuild that is still running would drop its callbacks.
 */
export const shouldResetRebuild = (p: { previous: string | null; current: string | null; failed: boolean }): boolean =>
  p.previous !== p.current && p.failed

/**
 * The notices above the plan. First run draws its own failure inside its card. The not-in-week
 * note adds "Your plan was rebuilt." only when this screen rebuilt the plan, and only over a
 * plan: a link from last week, or one with first run or need-a-paper behind it, names a session
 * no rebuild here took away, so the sentence would be false (K24, #3).
 */
export function screenNotices(p: {
  kind: string
  missingNote: boolean
  rebuiltHere: boolean
  rebuilding: boolean
  rebuildError: string | null
}): {
  missing: boolean
  missingRebuilt: boolean
  rebuilding: boolean
  actionError: string | null
} {
  return {
    missing: p.missingNote,
    missingRebuilt: p.missingNote && p.rebuiltHere && p.kind !== "firstRun" && p.kind !== "needPaper",
    rebuilding: p.rebuilding && p.kind === "plan",
    actionError: p.kind === "firstRun" ? null : p.rebuildError,
  }
}

/** The retry on the load error: fetch the week again. */
export const retryWeek =
  (week: Pick<QueryStateQuery<unknown>, "refetch">) =>
  (): void => {
    void week.refetch()
  }
