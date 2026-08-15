import { ApiError } from "@/lib/api"

/*
 * P4.6 · What a parent is told when a screen does not load.
 *
 * The fourth member of the family, after `correctionOutcome.ts` (P4.2),
 * `friendOutcome.ts` (P4.4) and `teacherOutcome.ts` (P4.5). All four of the
 * parent portal's screens rendered a raw `error.message` as the body of their
 * `ErrorState`, which is the same defect the previous three surfaces each
 * fixed for their own audience.
 *
 * ── Why this is not `teacherOutcome.ts` with the nouns changed ──────────────
 *
 * The obvious move was to reuse the teacher module, or to copy it and soften
 * the wording. Both would have been wrong, for a reason that is specific to
 * this portal and was found by reading the endpoints rather than assumed:
 * **every `detail` the parent API can produce is machine text.**
 *
 *   lemely/web/routers/parent.py
 *     122–130  HTTPException(422, detail=str(exc))            <- a Python
 *                                                                exception,
 *                                                                stringified
 *     132      "Unknown child: {child_id}"                    <- a raw UUID
 *     133      "Child {child_id} is not linked to this parent" <- a raw UUID
 *     469      "No papers for subject {code}"                 <- a syllabus code
 *
 * `teacherOutcome.ts` is deliberately detail-first because several teacher
 * endpoints write their 4xx `detail` *for a human* (the at-risk acknowledge
 * route's 422 is the example it names), and discarding those would lose the
 * only useful fact. The parent routes have no such case. A detail-first
 * classifier here would put `Child 6f2c1b7e-… is not linked to this parent` in
 * front of the reader PRODUCT.md describes as having "no interest in learning
 * an interface", and `str(ValueError(…))` in front of them on a bad date
 * range. So this module classifies on **status** and writes every sentence
 * itself.
 *
 * That is the whole point of the family being four modules rather than one
 * shared helper: the audience decides what a failure is allowed to say, and
 * these four audiences genuinely differ.
 *
 * ── Why there is no `mutationFailureMessage` here ───────────────────────────
 *
 * `useParentApi.ts` exposes no mutation, because `routers/parent.py` has no
 * write route: the whole portal is read-only, and linking is student-side.
 * A write-failure helper would therefore be a function with no caller,
 * asserting "nothing was saved" about saves that cannot happen. Its absence is
 * the honest shape, and this note exists so the next surface does not add it
 * back for symmetry.
 */

/** No response at all, as opposed to a bad one. */
export const PARENT_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again."

/** A fault on our side, which the parent can do nothing about. */
export const PARENT_SERVICE_FAILURE =
  "Something went wrong on our side. Nothing is wrong with your account, and trying again is safe."

/**
 * Not linked, or no longer linked, to this child.
 *
 * Written as a fact about the link rather than about permission: a parent
 * reading "forbidden" or "not authorised" reasonably wonders whether they have
 * done something wrong, and the real situation is simply that the child has not
 * added them (or has removed them), which is a thing the child controls and the
 * portal has already explained once on the no-children screen.
 */
export const PARENT_NOT_LINKED =
  "This child's results aren't shared with your account. They can add you again from their own Lemely account."

/** The thing being asked for is not there. */
export const PARENT_NOT_FOUND =
  "We couldn't find that. It may have been removed, or the link you followed may be out of date."

/**
 * Turn a failed read into a sentence, for the body of an `ErrorState`.
 *
 * `request()` wraps a `fetch` rejection as `ApiError(0, String(err))`, so
 * status 0 is this codebase's spelling of "no response at all" and is checked
 * before the generic arms rather than after them.
 */
export function parentLoadFailureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return PARENT_NETWORK_FAILURE
    if (err.status === 403) return PARENT_NOT_LINKED
    if (err.status === 404) return PARENT_NOT_FOUND
    if (err.status >= 500) return PARENT_SERVICE_FAILURE
    return "We couldn't load this just now. Trying again usually sorts it."
  }
  if (err instanceof TypeError) return PARENT_NETWORK_FAILURE
  return "We couldn't load this just now. Trying again usually sorts it."
}
