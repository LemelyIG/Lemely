import { ApiError } from "@/lib/api"

/*
 * Loading/error primitives PR, part A · what `<QueryState>` says when a
 * react-query result comes back `status: "error"` and the call site did not
 * supply its own `body`.
 *
 * ── Why this exists alongside seven surface-specific outcome modules ───────
 *
 * `correctionOutcome.ts`, `authOutcome.ts`, `teacherOutcome.ts`,
 * `parentOutcome.ts`, `friendOutcome.ts`, `settingsOutcome.ts` and
 * `studentOutcome.ts` each answer one portal's own failure vocabulary, and
 * each is right to: a 403 on the marking stream and a 403 on the parent
 * portal's child-linking screen are different facts read by different people,
 * and `studentOutcome.ts`'s own header explains at length why folding two of
 * those together was the wrong move even for two modules with the same
 * reader. None of the seven is a generic, portal-agnostic mapping — every one
 * of them is written for its own routes and its own reader.
 *
 * `<QueryState>` is a general-purpose wrapper any screen can reach for, so its
 * fallback has to be genuinely generic: a sentence that is true regardless of
 * which endpoint failed, for the ~25 screens a follow-up PR converts that have
 * no outcome module of their own (yet, or ever — a screen with a real one
 * keeps passing its own `body`, and this only fires when none was supplied).
 * It follows the family's shared rule rather than inventing a new one: keep a
 * `detail` a human wrote, translate a status the reader can act on, and never
 * let a machine's own words reach a screen.
 *
 * ── The rule this exists to keep off the screen ─────────────────────────────
 *
 * `correctionOutcome.ts`'s header records how "Failed to fetch" and "500
 * Internal Server Error" reached students before that module existed: a
 * render read `err.message` on whatever `fetch` or `api.ts` threw. This
 * module never does that. A non-`ApiError` (a bare `TypeError`, a thrown
 * string, anything) always falls through to `QUERY_GENERIC_FAILURE`, which is
 * this codebase's own sentence, not the runtime's.
 */

/** No response at all, as opposed to a bad one. `request()` in `lib/api.ts`
 * wraps a `fetch` rejection as `ApiError(0, String(err))`, so status 0 is
 * this codebase's spelling of "the request never completed". */
export const QUERY_NETWORK_FAILURE = "We couldn't reach Lemely. Check your connection and try again."

/** The session ended underneath the screen. */
export const QUERY_SESSION_EXPIRED = "Your session has ended. Sign in again to continue."

/** The reader is signed in, but this isn't theirs to see. */
export const QUERY_ACCESS_DENIED = "You don't have access to this."

/** The thing being asked for is not there. */
export const QUERY_NOT_FOUND =
  "We couldn't find what you were looking for. It may have been moved or removed."

/** Too many requests in too little time. The wording is deliberately calm:
 * this is this codebase's own throttle, not a punishment. */
export const QUERY_RATE_LIMITED = "Slow down for a moment. Wait a little, then try again."

/** A fault on the server side. Says plainly that nothing was lost, since an
 * unexplained failure on a screen showing a reader's own work reads as data
 * loss even when none occurred. */
export const QUERY_SERVICE_FAILURE =
  "Lemely is having trouble right now. Your work is safe. Try again in a few minutes."

/** Anything else: a status this module has no specific sentence for, or a
 * rejection that never reached the network layer at all. */
export const QUERY_GENERIC_FAILURE = "Something went wrong loading this. Try again in a moment."

/**
 * Turn whatever a react-query result's `error` field holds into one
 * student-readable sentence.
 *
 * Order matters, the same way it does in `correctionOutcome.ts`: a `detail`
 * FastAPI wrote for a human is checked before the status class, because a 422
 * that names the actual problem is worth more than anything generic this
 * module could say about a 422. Status 0 is checked first among the status
 * branches because it is a client-side synthesised code, not a real HTTP
 * response, and would otherwise fall into the `>= 500` test by coincidence of
 * ordering on some future refactor.
 */
export function describeQueryFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string" && error.detail.trim() !== "") {
      return error.detail.trim()
    }
    if (error.status === 0) return QUERY_NETWORK_FAILURE
    if (error.status === 401) return QUERY_SESSION_EXPIRED
    if (error.status === 403) return QUERY_ACCESS_DENIED
    if (error.status === 404) return QUERY_NOT_FOUND
    if (error.status === 429) return QUERY_RATE_LIMITED
    if (error.status >= 500) return QUERY_SERVICE_FAILURE
    return QUERY_GENERIC_FAILURE
  }

  // A bare `TypeError` (a dropped connection), a thrown string, or anything
  // else that isn't this client's own error type. None of these carry a
  // sentence written for a reader, so none of them are read here — see the
  // module header for what used to reach the screen when this function read
  // `.message` instead.
  return QUERY_GENERIC_FAILURE
}
