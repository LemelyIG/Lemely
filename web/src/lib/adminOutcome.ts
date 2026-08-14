import { ApiError } from "@/lib/api"

/*
 * P4.7 · What an administrator is told when something does not go through.
 *
 * ── Why an eighth module, when the standing note says the family is closed ──
 *
 * `BUILD/STATE.md` says plainly: seven modules, "do not write an eighth by
 * symmetry". This is not symmetry, and the note's own wording is the test —
 * the rule the family follows is *decide per endpoint, by reading the endpoint,
 * for the reader of the screen*. Two facts about these endpoints make every one
 * of the seven wrong here, and both were checked in the routers rather than
 * assumed:
 *
 * **1. The details are machine text, so detail-first is out.** That rules out
 * `teacherOutcome.ts` and `correctionOutcome.ts`, the two modules an admin
 * console would otherwise borrow, because both prefer the backend's own
 * sentence. Read in `lemely/web/routers/school.py` and its services:
 *
 *   "Caller does not administer school 3f2a…"        <- a UUID
 *   "Teacher still owns 2 class(es); supply
 *    reassignToTeacherId"                            <- a JSON field name
 *   "School 3f2a… has no free seats (5/5 used)"      <- a UUID
 *   "Unknown subscription: 9c1b…"                    <- a UUID
 *
 * **2. Two of the failures carry real meaning that no status sentence can
 * hold.** That rules out the status-first modules too, at least as-is. A 409 on
 * removing a teacher and a 409 on deciding an activation are not "something
 * went wrong": they are *"the thing you were looking at changed under you"*,
 * and the only useful next action is to reload and look again. Saying so is the
 * whole value, and it is why this module exports one helper per action rather
 * than one `mutationFailed` for all of them.
 *
 * ── The voice ──────────────────────────────────────────────────────────────
 *
 * Closest to `teacherOutcome.ts`: plain, no reassurance, states the data state.
 * An administrator's question after a failed write is always "did that take
 * effect?", and for every mutation reachable from these screens the answer is
 * no — each is a single request, so a failure means nothing was written. The
 * two race cases are the exception worth naming, because there the answer is
 * "not yours; someone else's did".
 *
 * ── The one thing this module must never do ────────────────────────────────
 *
 * Turn a failed *read* into an empty state. The platform console's whole job is
 * noticing trouble, and "zero open review items" is what calm looks like. Every
 * hook in `useAdminApi.ts` is therefore written without a `fallback`, and every
 * screen renders `adminLoadFailureMessage` rather than an empty table.
 */

/** No response at all, as opposed to a bad one. */
export const ADMIN_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again."

/** A fault on the server's side, which the administrator cannot fix. */
export const ADMIN_SERVICE_FAILURE = "Something went wrong on our side. Trying again is safe."

/** The caller's role or memberships do not cover what they asked for. */
export const ADMIN_NOT_PERMITTED = "You don't have access to that. Check which school you're in."

/**
 * `request()` wraps a `fetch` rejection as `ApiError(0, …)`, so status 0 is this
 * codebase's spelling of "no response at all" and must be checked before the
 * generic arms rather than after them.
 */
function statusOf(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null
}

/** The shared tail every helper below ends with, so the wording stays one text. */
function generalFailure(err: unknown): string {
  const status = statusOf(err)
  if (status === 0) return ADMIN_NETWORK_FAILURE
  if (status === 401 || status === 403) return ADMIN_NOT_PERMITTED
  return ADMIN_SERVICE_FAILURE
}

/**
 * A panel could not be read.
 *
 * Deliberately says nothing about what the numbers would have been. A console
 * that guesses at its own figures while failing to fetch them is worse than one
 * that admits it is blind.
 */
export function adminLoadFailureMessage(err: unknown): string {
  return generalFailure(err)
}

/**
 * A write did not go through, and nothing was saved.
 *
 * The default for any mutation with no more specific reading. Every mutation on
 * these screens is a single request, so "nothing was saved" is a fact, not
 * reassurance.
 */
export function adminMutationFailureMessage(err: unknown): string {
  const status = statusOf(err)
  if (status !== null && status >= 400 && status < 500 && status !== 401 && status !== 403) {
    return "We couldn't save that. Nothing has changed. Check the details and try again."
  }
  return generalFailure(err)
}

/**
 * Inviting a student onto a seat failed.
 *
 * The 409 is the school being at its quota — the one failure here an admin can
 * act on, and the one K-02's spec calls out ("Quota reached: explain and give a
 * route to request more"). The sentence explains; the screen supplies whatever
 * route exists.
 */
export function seatInviteFailureMessage(err: unknown): string {
  if (statusOf(err) === 409) {
    return "This school is using every seat it has, so the invite wasn't sent."
  }
  return adminMutationFailureMessage(err)
}

/**
 * Removing a teacher failed.
 *
 * The 409 covers both of the backend's refusals — classes that would be
 * orphaned, and a reassignment target who is no longer staff here — and one
 * sentence is right for both, because the screen already prevents the
 * deliberate versions of each. It requires a target before it will submit for a
 * teacher who owns classes, and it lists only current staff as targets. So a
 * 409 reaching this function means the staffing changed between the dialog
 * opening and the click, which is exactly what the sentence says.
 */
export function teacherRemovalFailureMessage(err: unknown): string {
  if (statusOf(err) === 409) {
    return "This teacher's classes changed while you were deciding. Reload and try again."
  }
  if (statusOf(err) === 404) {
    return "That teacher is no longer on this school's staff. Nothing has changed."
  }
  return adminMutationFailureMessage(err)
}

/**
 * Activating or rejecting a subscription failed.
 *
 * The 409 is another administrator having already decided this one. That is the
 * ordinary case on a shared queue, not an exotic one, and the useful thing to
 * say is that the decision stands and whose it was is visible on a reload —
 * never that "something went wrong", which would invite a retry that cannot
 * succeed.
 */
export function activationDecisionFailureMessage(err: unknown): string {
  if (statusOf(err) === 409) {
    return "Someone has already decided this one. Reload the queue to see the outcome."
  }
  if (statusOf(err) === 404) {
    return "That request is no longer in the queue. Nothing has changed."
  }
  return adminMutationFailureMessage(err)
}
