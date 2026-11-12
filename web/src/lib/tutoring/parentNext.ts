/*
 * T27 · the one piece of the parent's tutoring addresses that the sign-in screen
 * needs. It lives alone, with no imports, so `postLoginTarget` (and with it the
 * Login bundle) does not pull in the parent screens' view code.
 */

export const PARENT_TUTORS_PATH = "/parent/tutors"

/** A tutor id as the API issues it. Anything else is not a tutor page. */
const TUTOR_ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
const STUDENT_TUTOR_PAGE = new RegExp(`^/student/tutors/(${TUTOR_ID})$`, "i")

/**
 * G-17's "Sign in to book" carries `?next=/student/tutors/{id}`, because the
 * public page cannot know who will sign in. `postLoginTarget` keeps a `next`
 * only when it sits inside the signed-in role's own portal, so a parent who
 * followed that link would land on the parent home and lose the tutor. A parent's
 * login maps the student tutor page to the parent's page for the same tutor;
 * every other address is returned as it came (the portal check still applies).
 * Only the exact tutor page of a real tutor id maps: the student's booking step
 * is not a parent's, and a segment that is not an id is not a tutor.
 */
export function parentNextTarget(next: string | null): string | null {
  if (next === null) return null
  const match = STUDENT_TUTOR_PAGE.exec(next)
  return match ? `${PARENT_TUTORS_PATH}/${match[1]}` : next
}
