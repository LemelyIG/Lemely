import { ApiError } from "@/lib/api"

/*
 * P4.5 · What a teacher is told when something does not go through.
 *
 * The third member of the family, after `correctionOutcome.ts` (P4.2) and
 * `friendOutcome.ts` (P4.4), and by some distance the widest: **every one of
 * the teacher portal's fifteen screens rendered a raw `error.message`**, at 44
 * separate call sites. A dropped connection put the browser's
 * `TypeError: Failed to fetch` on screen; a 500 put whatever the server
 * happened to say. Neither tells a teacher what state their data is in, which
 * is the only question they have at that moment.
 *
 * Two things differ from the student modules, and both are deliberate.
 *
 * **The voice.** A teacher is not a fifteen-year-old and does not need to be
 * reassured; they need to know whether to retry, whether anything was written,
 * and whether the problem is theirs to fix. So these sentences are plainer and
 * they state the data state explicitly.
 *
 * **The detail-first branch matters more here.** Several teacher endpoints
 * return a 4xx whose `detail` is the only place the real reason exists — the
 * at-risk acknowledge route's 422 ("that reason is not currently firing for
 * this student", a genuine race when the evidence moved between the list
 * loading and the click) has no other spelling. Discarding it for a generic
 * sentence would lose the one fact worth knowing. This is the same call
 * `friendOutcome.ts` made for the send-request path, and the same reason.
 *
 * `mutationFailed` exists separately from `loadFailed` because the two answer
 * different questions. A failed *read* leaves the screen empty and the fix is
 * to retry. A failed *write* raises "did it save?", and the honest answer for
 * every mutation in this portal is no: they are all single requests, so a
 * failure means nothing was written. Saying so is the point.
 */

/** No response at all, as opposed to a bad one. */
export const TEACHER_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again."

/** A fault on the server's side, which the teacher can do nothing about. */
export const TEACHER_SERVICE_FAILURE = "Something went wrong on our side. Trying again is safe."

/**
 * The shared classifier both exported helpers run on.
 *
 * `request()` wraps a `fetch` rejection as `ApiError(0, String(err))`, so
 * status 0 is this codebase's spelling of "no response at all" and has to be
 * checked before the generic 4xx arm rather than after it.
 */
function classify(err: unknown): { kind: "detail" | "network" | "service" | "unknown"; text: string } {
  if (err instanceof ApiError) {
    if (typeof err.detail === "string" && err.detail.trim() !== "") {
      return { kind: "detail", text: err.detail.trim() }
    }
    if (err.status === 0) return { kind: "network", text: TEACHER_NETWORK_FAILURE }
    if (err.status >= 500) return { kind: "service", text: TEACHER_SERVICE_FAILURE }
    return { kind: "unknown", text: "" }
  }
  if (err instanceof TypeError) return { kind: "network", text: TEACHER_NETWORK_FAILURE }
  return { kind: "unknown", text: "" }
}

/**
 * Turn a failed *read* into a sentence. Use for the body of an `ErrorState`
 * standing in for a screen that could not load.
 *
 * The endpoint's own `detail` wins where there is one: a 403 on a class that
 * is not this teacher's says so far better than any sentence written here.
 */
export function teacherLoadFailureMessage(err: unknown): string {
  const c = classify(err)
  if (c.kind !== "unknown") return c.text
  return "We couldn't load this just now. Trying again usually sorts it."
}

/**
 * Turn a failed *write* into a sentence, for an inline error beside the
 * control that produced it.
 *
 * Every branch other than the endpoint's own wording ends by saying nothing
 * was saved, because for every mutation in this portal that is true and it is
 * the thing a teacher actually needs to know before they press the button a
 * second time.
 */
export function teacherMutationFailureMessage(err: unknown): string {
  const c = classify(err)
  if (c.kind === "detail") return c.text
  if (c.kind === "network") return `${TEACHER_NETWORK_FAILURE} Nothing was saved.`
  if (c.kind === "service") return `${TEACHER_SERVICE_FAILURE} Nothing was saved.`
  return "That didn't go through, and we couldn't tell why. Nothing was saved."
}
