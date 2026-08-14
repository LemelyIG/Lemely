import { ApiError } from "@/lib/api"

/*
 * P4.10 · What a student is told when one of their own screens fails.
 *
 * The seventh and last member of the family, after `correctionOutcome.ts`
 * (P4.2), `friendOutcome.ts` (P4.4), `teacherOutcome.ts` (P4.5),
 * `parentOutcome.ts` (P4.6), `authOutcome.ts` (P4.7) and `settingsOutcome.ts`
 * (P4.10). It covers the student screens surface 10's sweep found still in the
 * build-era language: onboarding, the placement flow, the subject screen,
 * announcements and the parent-linking screen.
 *
 * ── Why not simply widen `correctionOutcome.ts` ────────────────────────────
 *
 * Same audience, so this looks like the obvious merge. It is the wrong one,
 * and the reason is the single most important line in that module: it is
 * **detail-first on purpose**. `routers/student.py`'s marking path writes its
 * 4xx `detail` for a user — "No mark scheme available for this paper" is a
 * sentence a fifteen-year-old can act on, and discarding it would lose the
 * only useful fact in the response. Widening that policy across these routers
 * would put their details in front of the same reader, and their details are:
 *
 *   me.py         113  f"{field} cannot be null."          <- a JSON field name
 *                 207  "Malformed user id."
 *                 254  f"Unknown session month: {value!r}" <- a Python repr
 *                 326  detail=str(exc)                     <- StudentProfile-
 *                 364  detail=str(exc)                        ValidationError,
 *                 387  detail=str(exc)                        stringified
 *   placement.py   52  detail=str(exc)                     <- "Unknown
 *                 118  detail=str(exc)                        assignment:
 *                 140  detail=str(exc)                        6f2c…" — a raw
 *                 160  detail=str(exc)                        UUID
 *   student_announcements.py
 *                 139  detail=str(exc)
 *                 141  detail=str(exc)
 *
 * So the two modules disagree about the one question that matters, for
 * evidenced reasons on both sides, and merging them would mean picking a
 * policy that is wrong for one half of the student's screens. They stay
 * separate. `correctionOutcome.ts` owns the marking stream; this owns the rest.
 *
 * ── Why not `settingsOutcome.ts` ───────────────────────────────────────────
 *
 * That module is status-first too, and for the same evidence. But its whole
 * premise is that its reader is *any of five roles at once*, so it cannot pick
 * a register: no reassurance a teacher would find patronising, no plain-speech
 * concession a student needs. This module has exactly one reader and is written
 * for them — shorter sentences, and the thing a student actually worries about
 * ("did I lose what I typed") answered first.
 *
 * ── The placement 409 is deliberately not handled here ─────────────────────
 *
 * `placement.py:137` answers 409 with a **structured** detail: a full
 * `PlacementAvailabilityDTO`, not a string, which `ApiError.detail` preserves
 * for exactly this purpose. `PlacementInvite` reads that object and renders the
 * same honest unavailable-reason panel S-03 shows on load. Flattening it to a
 * sentence here would throw away the only response in this whole set that
 * carries machine-readable information worth having, so `studentLoad-
 * FailureMessage` leaves 409 to the generic arm and the caller checks
 * `err.detail` first. That check is the caller's job, and the two placement
 * screens do it.
 */

/** No response at all, as opposed to a bad one. */
export const STUDENT_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again."

/** A fault on our side, which the student can do nothing about. */
export const STUDENT_SERVICE_FAILURE =
  "Something went wrong on our side. Trying again is safe."

/** The thing being asked for is not there. */
export const STUDENT_NOT_FOUND =
  "We couldn't find that. It may have been removed, or the link you followed may be out of date."

/** Somebody else's. */
export const STUDENT_NOT_YOURS = "That isn't yours to open."

/** The session ended underneath the screen. */
export const STUDENT_SIGNED_OUT = "You've been signed out. Sign in again to pick up where you left off."

/**
 * A save the server refused.
 *
 * The first sentence answers the question a student actually has, which is not
 * "what status code was that" but "have I lost what I typed". They have not:
 * every screen in this set keeps its local state on a failed save.
 */
export const STUDENT_SAVE_REJECTED =
  "We couldn't save that. Nothing you typed has been lost, so you can try again."

/**
 * Turn a failed read into a sentence, for the body of an `ErrorState`.
 *
 * `request()` wraps a `fetch` rejection as `ApiError(0, String(err))`, so
 * status 0 is this codebase's spelling of "no response at all" and is checked
 * before the generic arms rather than after them.
 */
export function studentLoadFailureMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return STUDENT_SERVICE_FAILURE
  if (err.status === 0) return STUDENT_NETWORK_FAILURE
  if (err.status === 401) return STUDENT_SIGNED_OUT
  if (err.status === 403) return STUDENT_NOT_YOURS
  if (err.status === 404) return STUDENT_NOT_FOUND
  return STUDENT_SERVICE_FAILURE
}

/**
 * Turn a failed write into a sentence.
 *
 * Separate from the read helper because the student's question is different: a
 * failed read asks "can I see this", a failed write asks "did I lose it". None
 * of these sentences claims a change was saved, and none of them blames the
 * student for a 422 they had no way to cause — every field in this set is
 * either a choice from a fixed list or validated in the browser first.
 */
export function studentSaveFailureMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return STUDENT_SERVICE_FAILURE
  if (err.status === 0) return STUDENT_NETWORK_FAILURE
  if (err.status === 401) return STUDENT_SIGNED_OUT
  if (err.status === 403) return STUDENT_NOT_YOURS
  if (err.status === 422) return STUDENT_SAVE_REJECTED
  return STUDENT_SERVICE_FAILURE
}

/**
 * Turn a failed *action* into a sentence that still says which action (P6.2).
 *
 * A third helper rather than a call site of the second, because the second
 * answers the wrong question for this case. `STUDENT_SAVE_REJECTED` leads with
 * "Nothing you typed has been lost", which is the right reassurance for a form
 * and a confusing one after a button press where nothing was typed at all.
 *
 * `action` completes "We couldn't ___", so it is a bare verb phrase in the
 * infinitive: `"mark that session as done"`, not `"Marking failed"`. Keeping it
 * is the point of the helper: two different actions can fail on one screen, and
 * a reader who is told only that something went wrong has to guess which.
 *
 * The status arms are deliberately the same judgements as the other two
 * helpers, minus the typing reassurance. A 422 here is not a validation
 * message a student could act on — these routes take an id from the screen's
 * own data, so a rejection means the plan changed underneath them.
 */
export function studentActionFailureMessage(err: unknown, action: string): string {
  const lead = `We couldn't ${action}.`
  if (!(err instanceof ApiError)) return `${lead} Something went wrong on our side.`
  if (err.status === 0) {
    return `${lead} Check your connection and try again.`
  }
  if (err.status === 401) return STUDENT_SIGNED_OUT
  if (err.status === 403) return STUDENT_NOT_YOURS
  if (err.status === 404 || err.status === 409 || err.status === 422) {
    return `${lead} Your plan may have changed since this page loaded. Reload and try again.`
  }
  return `${lead} Something went wrong on our side, so trying again is safe.`
}
