import { ApiError } from "@/lib/api"

/*
 * P4.10 · What any signed-in reader is told when a settings screen fails.
 *
 * The sixth member of the family, after `correctionOutcome.ts` (P4.2),
 * `friendOutcome.ts` (P4.4), `teacherOutcome.ts` (P4.5), `parentOutcome.ts`
 * (P4.6) and `authOutcome.ts` (P4.7). The two settings screens rendered a raw
 * `error.message` at four sites between them, which is the same defect the
 * previous five surfaces each fixed for their own audience.
 *
 * ── Why a sixth module, when the standing note says not to write one ────────
 *
 * `BUILD/STATE.md` warns, correctly, against copying any single module's
 * policy into a sixth. This is not that. The rule the family actually follows
 * is *decide per endpoint, by reading the endpoint, for the audience that
 * reads the screen* — and this lane is the first place where **the audience is
 * every role at once**.
 *
 * `/settings/devices` and `/settings/notifications` are mounted top-level and
 * guarded by `ALL_ROLES` on purpose: the device limit is enforced per account
 * regardless of role, and the at-risk-alert preference belongs to teachers and
 * parents. So one sentence here is read by a fifteen-year-old, their parent,
 * their teacher and a platform admin. It cannot be tuned to a register the way
 * the other five are. The constraint that follows is narrow and worth stating:
 * **plain enough for the student, never explanatory to the point of
 * condescension for the teacher.** No reassurance about schoolwork, no
 * "your account is fine" hand-holding, no jargon either.
 *
 * ── What the endpoints actually say ────────────────────────────────────────
 *
 * Read rather than assumed, in `lemely/web/routers/me.py`:
 *
 *   113  detail=f"{field} cannot be null."                    <- a JSON field
 *                                                                name
 *   137  "atRiskAlert is only settable for the teacher and
 *        parent roles."                                       <- camelCase API
 *                                                                vocabulary
 *   172  detail=str(exc)                                      <- a Python
 *   207  "Malformed user id."                                    exception or
 *   306  "leaderboardOptOut cannot be null; omit it to           an internal
 *        leave unchanged"                                        identifier
 *
 * Every one of those is written for a client author, not for a reader. There
 * is no case here like `teacherOutcome.ts`'s at-risk 422, where a human wrote
 * the sentence for a human and discarding it would lose the only useful fact.
 * So this module classifies on **status** and writes every sentence itself,
 * the same shape as `parentOutcome.ts` and for the same evidenced reason
 * rather than by imitation.
 *
 * ── The 422 is the one that carries information ────────────────────────────
 *
 * `PATCH /me/notification-preferences` answers 422 when a role sets a
 * preference it does not have (`atRiskAlert` on a student). The screen already
 * filters those toggles out, so a 422 reaching here means the filter and the
 * router disagree — a bug on our side, not a thing the reader did. It is
 * therefore worded as our fault and not as invalid input, which is the
 * opposite of what a status-code-driven default would produce.
 */

/** No response at all, as opposed to a bad one. */
export const SETTINGS_NETWORK_FAILURE =
  "We couldn't reach Lemely just then. Check your connection and try again."

/** A fault on our side, which the reader can do nothing about. */
export const SETTINGS_SERVICE_FAILURE =
  "Something went wrong on our side. Trying again is safe."

/**
 * A change the server refused.
 *
 * Worded as our fault on purpose: see the module note. The reader cannot type
 * anything into these screens that a 422 would be a fair answer to, apart from
 * quiet hours, which is validated in the browser before it is ever sent
 * (`quietHoursUpdate`).
 */
export const SETTINGS_REJECTED =
  "We couldn't save that change. It looks like a fault at our end rather than anything you did."

/** The session ended underneath the screen. */
export const SETTINGS_SIGNED_OUT =
  "You've been signed out. Sign in again to change your settings."

/**
 * Turn a failed read into a sentence, for the body of an `ErrorState`.
 *
 * `request()` wraps a `fetch` rejection as `ApiError(0, String(err))`, so
 * status 0 is this codebase's spelling of "no response at all" and is checked
 * before the generic arms rather than after them.
 */
export function settingsLoadFailureMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return SETTINGS_SERVICE_FAILURE
  if (err.status === 0) return SETTINGS_NETWORK_FAILURE
  if (err.status === 401 || err.status === 403) return SETTINGS_SIGNED_OUT
  return SETTINGS_SERVICE_FAILURE
}

/**
 * Turn a failed write into a sentence.
 *
 * Separate from the read helper because the reader's question is different:
 * a failed read asks "can I see this", a failed write asks "did my change
 * stick". Every sentence this returns answers the second question, and none of
 * them claims a change was saved.
 */
export function settingsSaveFailureMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return SETTINGS_SERVICE_FAILURE
  if (err.status === 0) return SETTINGS_NETWORK_FAILURE
  if (err.status === 401 || err.status === 403) return SETTINGS_SIGNED_OUT
  if (err.status === 422) return SETTINGS_REJECTED
  return SETTINGS_SERVICE_FAILURE
}

/**
 * What to say when a sign-out request succeeded and the device is still there.
 *
 * This is not an error path, which is exactly why it needs its own sentence.
 * `DELETE /me/devices/{id}` never raises: a device id that does not exist, is
 * already revoked, or belongs to another account all answer `removed: false`
 * with a 200, deliberately, so the route cannot be used to test whether an id
 * exists on somebody else's account (`schemas_devices.py`).
 *
 * The consequence for the screen is that the mutation's `onSuccess` fires for
 * a sign-out that did not happen. Before P4.10 nothing rendered that case, so
 * a reader on the one screen in the product they open *because* they suspect
 * someone else is signed in could press "Sign out", watch the row stay, and be
 * told nothing at all.
 *
 * The wording avoids the two available lies. It does not say the device was
 * signed out, and it does not say something went wrong, because nothing did:
 * the honest reading is that the device was already gone.
 */
export const DEVICE_ALREADY_GONE =
  "That device was already signed out. The list below is up to date."
