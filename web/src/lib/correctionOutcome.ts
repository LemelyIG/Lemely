import { ApiError } from "@/lib/api"
import { AUTH_EMAIL_UNVERIFIED } from "@/lib/authOutcome"
import { isEmailUnverifiedError } from "@/lib/authTypes"

/*
 * P4.2 · What the student is told when a marking run does not produce a result.
 *
 * Split out of `CorrectPaper.tsx` so it can be tested without a DOM, in the
 * same spirit as `pipelineStages.ts`. It lives here rather than there because
 * `pipelineStages` is shared with the teacher console and this wording is the
 * student's — a teacher and a fifteen-year-old need different sentences about
 * the same 503.
 *
 * TWO REAL DEFECTS ARE ANSWERED HERE, both found while redesigning the surface
 * rather than by reading the audit.
 *
 * 1. **A run could end silently.** `streamActivity` yields frames until the
 *    body is exhausted; if the stream closes without a terminal
 *    `marking_progress { phase: "complete" }` frame and without an error frame,
 *    `CorrectPaper`'s loop simply fell out of the bottom, `finally` set
 *    `running` to false, and the panel went back to reading "Ready when you
 *    are" with two ticks and a half-drawn third stage. Nothing said the run had
 *    failed, and nothing offered a way forward. `api.ts` now throws on a
 *    non-OK response so the common case of that (a 500 or 503 with a JSON body,
 *    which has a `res.body` and therefore parsed to zero frames) surfaces as an
 *    error; `STREAM_ENDED_WITHOUT_RESULT` covers what is left, which is a
 *    connection that dropped mid-run.
 *
 * 2. **The server's own words reached the student.** The failure path rendered
 *    `err.message` verbatim, so a dropped Wi-Fi connection showed the browser's
 *    "Failed to fetch" and a backend fault showed "500 Internal Server Error".
 *    `lib/api.ts` already carries this lesson for the auth path, where a stale
 *    token used to print "Invalid access token: Signature has expired" on every
 *    screen. The rule applied here is narrow on purpose: a message the *backend
 *    wrote for a user* (a FastAPI `detail` string, which is how "No mark scheme
 *    available for this paper" reaches the screen) is kept, because it is
 *    specific and actionable and this screen has no better sentence for it.
 *    What is replaced is the machine wording that no student can act on.
 */

/**
 * The stream closed cleanly but never said the paper was marked. The second
 * sentence matters more than the first: the scan is already uploaded, so retry
 * costs nothing and re-uploading would be wasted work.
 */
export const STREAM_ENDED_WITHOUT_RESULT =
  "The connection to the marking service closed before your result came back. Your scan is still uploaded, so you can start marking again without picking the file a second time."

/** A network-layer failure: no response at all, rather than a bad one. */
export const NETWORK_FAILURE =
  "We couldn't reach the marking service. Check your connection and start marking again."

/** A fault on the server side, which the student can do nothing about but wait. */
export const SERVICE_FAILURE =
  "The marking service ran into a problem on its side. Nothing was charged against your paper, and starting again is safe."

/**
 * Turn whatever `runCorrection` threw into a sentence written for a student.
 *
 * Order matters twice over.
 *
 * `email_unverified` is checked first because it is the one `detail` on this
 * route that is a *field* rather than prose, and the two branches below can
 * only read prose. `deps.require_verified_email` raises
 * `403 {"code": "email_unverified"}` and its own docstring calls that "a
 * stable, machine-readable marker (never prose) the frontend's
 * `lib/authOutcome.ts`-family outcome modules match on" — `authOutcome.ts`'s
 * note 6 says the same from the other side, that the marker reaches that
 * module because "some other screen's failed request (today, only
 * `POST /student/correct`)" hands it over. This screen is that other screen,
 * and until now it never handed anything over: `typeof err.detail === "string"`
 * is false for an object, so the marker fell through to the 4xx branch and a
 * student whose email was simply unverified was told the marking service
 * "didn't say why" — about the one refusal that says exactly why, and the one
 * this product can do something about. Reproduced against staging on
 * 2026-09-04, where it is the whole of why marking stops.
 *
 * `AUTH_EMAIL_UNVERIFIED` is borrowed rather than reworded because that
 * constant is written for exactly this: "wherever `require_verified_email`
 * eventually guards something, not only today's one route". What is *not*
 * borrowed is `verificationFailureMessage` itself — its other branches speak
 * in the auth screens' voice ("We couldn't reach Lemely just then"), and this
 * module's whole reason for existing is that a marking run and a sign-in
 * failure are not the same sentence.
 *
 * Then a FastAPI `detail` is checked before the status class, because a 422
 * that says "This paper has already been marked" is far more useful than
 * anything generic that could be said about a 422.
 */
export function correctionFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // D7.5's soft gate. Structured, so it has to be read as a shape — by the
    // time it arrives `err.message` is only the "403 Forbidden" status line.
    if (err.status === 403 && isEmailUnverifiedError(err.detail)) return AUTH_EMAIL_UNVERIFIED
    // `detail` is what the endpoint chose to tell a human. A status line
    // ("500 Internal Server Error") is what `api.ts` synthesises when the body
    // carried nothing, and that is not a sentence to show anybody.
    if (typeof err.detail === "string" && err.detail.trim() !== "") {
      return err.detail.trim()
    }
    if (err.status >= 500) return SERVICE_FAILURE
    // `request()` wraps a `fetch` rejection as `ApiError(0, String(err))`, so
    // status 0 is this codebase's spelling of "no response at all" — and its
    // message is the browser's raw `TypeError: Failed to fetch`, which is
    // exactly the wording this function exists to keep off the screen.
    if (err.status === 0) return NETWORK_FAILURE
    // A 4xx with no detail is a client-side mismatch we cannot describe
    // honestly, so say what is true: it did not run, and retrying is safe.
    return "The marking service turned this run down and didn't say why. Starting again is safe."
  }

  // `fetch` rejects with a TypeError for DNS failures, offline devices, and
  // CORS faults alike. The browser's own wording ("Failed to fetch",
  // "NetworkError when attempting to fetch resource") differs per engine and
  // means nothing to a reader, so all of it becomes one sentence.
  if (err instanceof TypeError) return NETWORK_FAILURE

  if (err instanceof Error && err.message.trim() !== "") return err.message
  return SERVICE_FAILURE
}

/**
 * Whether a paper that has already been uploaded can be re-marked without
 * re-uploading. This is the whole of audit finding M5's fix: `uploadScan` and
 * `runCorrection` are two calls, and only the second one failed, so sending the
 * same multipart body a second time would upload a scan the server already has.
 */
export function canRetryInPlace(paperId: string | null): paperId is string {
  return typeof paperId === "string" && paperId !== ""
}
