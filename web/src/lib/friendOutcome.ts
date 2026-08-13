import { ApiError } from "@/lib/api"

/*
 * P4.4 · What a student is told when a friend action does not go through.
 *
 * The same lesson as `correctionOutcome.ts`, applied to the surface that still
 * had the defect. `Friends.tsx` rendered `err.message` verbatim for all three
 * of its mutations, and one of those three was right to do so while the other
 * two were not:
 *
 * - **Sending a request** genuinely wants the backend's own words. The
 *   endpoint distinguishes "no such code" from "you two are already friends"
 *   from "that is your own code", and each tells the student a different next
 *   step. That was a considered decision and it survives here, as the
 *   detail-first branch.
 * - **Accepting and removing** had no such wording behind them. Their errors
 *   are whatever was thrown, so a dropped connection put the browser's
 *   `TypeError: Failed to fetch` on screen — engine-specific machine text, in
 *   front of a fifteen-year-old, with no suggested action.
 *
 * The fix is not to stop showing the backend's sentence. It is to stop showing
 * the *browser's*.
 *
 * The second half of the defect was placement, and it is fixed in the screen
 * rather than here: all three messages rendered in a block at the very bottom
 * of the page, below every section. A student who declined a request at the
 * top of a long list got a failure notice off-screen.
 */

/** No response at all, as opposed to a bad one. */
export const FRIEND_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again. Nothing has changed."

/** A fault on the server's side, which the student can do nothing about. */
export const FRIEND_SERVICE_FAILURE =
  "Something went wrong on our side. Nothing has changed, and trying again is safe."

/**
 * Turn a thrown friend-action error into a sentence written for a student.
 *
 * Ordering mirrors `correctionFailureMessage`: a FastAPI `detail` is the
 * endpoint's own words for a human and beats anything generic that could be
 * said about the status code it arrived with.
 *
 * Every branch ends on "nothing has changed", because for these three
 * mutations that is both true and the thing the student actually wants to
 * know: a failed decline has not silently accepted anybody.
 */
export function friendActionFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === "string" && err.detail.trim() !== "") {
      return err.detail.trim()
    }
    if (err.status >= 500) return FRIEND_SERVICE_FAILURE
    // `request()` wraps a `fetch` rejection as `ApiError(0, String(err))`, so
    // status 0 is this codebase's spelling of "no response at all".
    if (err.status === 0) return FRIEND_NETWORK_FAILURE
    return "That didn't go through, and we couldn't tell why. Nothing has changed, so trying again is safe."
  }

  if (err instanceof TypeError) return FRIEND_NETWORK_FAILURE

  if (err instanceof Error && err.message.trim() !== "") return err.message
  return FRIEND_SERVICE_FAILURE
}
