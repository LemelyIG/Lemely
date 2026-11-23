/*
 * L9 · the small decisions the study plan screen makes that are not about what
 * the plan holds (that is `planModel`): which query state to act on, which
 * message a refused move gets, which url a filter or session lives at, and
 * where a tap on the day strip scrolls to. Pure, so they run without a DOM.
 */

import type { QueryStateQuery } from "@/components/ui/query-state"
import { ApiError } from "@/lib/api"
import { COPY } from "./planCopy"
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
