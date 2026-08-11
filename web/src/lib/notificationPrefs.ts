/*
 * Wire types and pure rendering/validation logic for G-12 · Notification
 * preferences (P5.9 chunk C), mirroring `lemely/web/schemas_me.py`.
 *
 * Everything here is a pure function over plain data so vitest can drive it —
 * `vitest.config.ts:25` sets `environment: "node"` with no jsdom, so the screen
 * itself is not mountable in a unit test and the decisions worth pinning have to
 * live outside it. The same split chunk A used for the service worker.
 *
 * The route is **`GET`/`PUT /api/me/notification-preferences`**
 * (`routers/me.py:86`). Two corrections to the brief that wrote this task, both
 * found by reading the router rather than the note: the verb is **PUT, not
 * PATCH** (it is still a genuine partial update — the router distinguishes
 * "omitted" from "explicitly sent" via pydantic's `model_fields_set`), and
 * `atRiskAlert` is **role-gated on both directions**, arriving as `null` for
 * any role other than teacher/parent and 422-ing if such a role sends it at all.
 */

/** The five preference toggles. There is no sixth — see `NOTIFICATION_TOGGLES`. */
export type NotificationPrefKey =
  | "gradeReady"
  | "announcement"
  | "streakWarning"
  | "studyPlanReminder"
  | "atRiskAlert"

/**
 * `GET` response and the `PUT` echo.
 *
 * `atRiskAlert` is `boolean | null`, and the `null` is information rather than
 * an absent value: it means *this caller's role has no such preference*. The
 * screen renders that as the toggle simply not existing, never as a switch in
 * some third state.
 *
 * The quiet-hours pair arrives as pydantic-serialised `time` — `"HH:MM:SS"`,
 * not the `"HH:MM"` an `<input type="time">` speaks. `timeInputValue` and
 * `apiTimeValue` are the two directions of that conversion.
 */
export interface NotificationPreferences {
  gradeReady: boolean
  announcement: boolean
  streakWarning: boolean
  studyPlanReminder: boolean
  atRiskAlert: boolean | null
  quietHoursStart: string | null
  quietHoursEnd: string | null
}

/**
 * `PUT` body. Every field optional, and **an omitted field is untouched
 * server-side** — so a toggle flip sends exactly one key, never the whole
 * object. That matters beyond bandwidth: sending the whole object would include
 * `atRiskAlert`, which is a 422 for a student, and would clobber a change made
 * from another device between this screen's load and its save.
 */
export type NotificationPreferencesUpdate = Partial<{
  gradeReady: boolean
  announcement: boolean
  streakWarning: boolean
  studyPlanReminder: boolean
  atRiskAlert: boolean
  quietHoursStart: string | null
  quietHoursEnd: string | null
}>

export interface ToggleSpec {
  key: NotificationPrefKey
  label: string
  /** What this actually gates, in the reader's terms — never invented scope. */
  description: string
}

/**
 * The toggles this screen ships, in display order.
 *
 * **Exactly five, matching `NotificationType`'s five members.** UI spec §G-12
 * also lists a "weekly summary" toggle: there is no such enum value, no column,
 * no sender and no row, so a sixth switch here would be a control that gates
 * nothing — precisely what UI spec §1.4 forbids. It is reported as an honest
 * gap rather than mocked.
 *
 * The descriptions say what the toggle *does* and no more. D5.9 §2 makes a type
 * toggle a **content** preference: switching one off suppresses the inbox row
 * as well as the push, because the reader is saying they do not want to be told
 * this kind of thing at all. Quiet hours are the timing preference and suppress
 * only the push — the row is still written, so nothing is lost by arriving at
 * 2am. Those two sentences are the whole mental model this screen has to convey,
 * and getting them backwards would have a reader believe they had silenced a
 * night-time notification when they had actually deleted it.
 */
export const NOTIFICATION_TOGGLES: readonly ToggleSpec[] = [
  {
    key: "gradeReady",
    label: "Marks are ready",
    description: "When a paper you uploaded has finished marking.",
  },
  {
    key: "announcement",
    label: "New announcements",
    description: "When a teacher or your school posts something.",
  },
  {
    key: "streakWarning",
    label: "Streak at risk",
    description: "When your streak is about to break.",
  },
  {
    key: "studyPlanReminder",
    label: "Study session reminders",
    description: "When a session on your study plan is due.",
  },
  {
    key: "atRiskAlert",
    label: "At-risk alerts",
    description: "When a student you are responsible for needs attention.",
  },
]

/**
 * Convert a pydantic `time` to what an `<input type="time">` accepts.
 *
 * `"22:00:00"` → `"22:00"`; `null` → `""` (an empty time input, which is the
 * "no quiet hours" state). Anything unparseable also returns `""` rather than
 * being passed through: a time input silently rejects a value it cannot parse
 * and shows blank anyway, so returning the raw string would put the DOM and
 * React's idea of the value permanently out of step.
 */
export function timeInputValue(apiTime: string | null): string {
  if (apiTime === null) return ""
  const match = /^(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/.exec(apiTime)
  if (match === null) return ""
  return `${match[1]}:${match[2]}`
}

/**
 * Convert an `<input type="time">` value to what the API stores.
 *
 * `""` → `null` (an explicit `null` is how the API clears a bound; omission is
 * how it leaves one alone, and the caller chooses between them). `"22:00"` →
 * `"22:00:00"`, normalised to seconds precision rather than relying on the
 * server to widen it — pydantic does accept `"22:00"`, but the value this screen
 * sends and the value it reads back should be the same shape or a later
 * equality check somewhere will quietly be false.
 */
export function apiTimeValue(inputValue: string): string | null {
  if (inputValue === "") return null
  const match = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(inputValue)
  if (match === null) return null
  return `${match[1]}:${match[2]}:${match[3] ?? "00"}`
}

export type QuietHoursResult =
  | { ok: true; update: NotificationPreferencesUpdate }
  | { ok: false; message: string }

/**
 * Build the quiet-hours half of a `PUT` body, or refuse.
 *
 * **Both bounds or neither is the only representable state** — the service
 * raises `ValueError` on a merged result with exactly one set and the router
 * turns that into a 422 (`routers/me.py:170`). Catching it here is not
 * decoration: the alternative is a reader who types a start time, tabs away, and
 * gets a red error for a form they have not finished filling in. The message is
 * about what to do next, not about what the server rejected.
 *
 * A start equal to its end is deliberately **allowed through** rather than
 * second-guessed here — the backend accepts it and this function's job is to
 * mirror the backend's rule, not to invent a stricter one the server would not
 * have applied.
 */
export function quietHoursUpdate(start: string, end: string): QuietHoursResult {
  const quietHoursStart = apiTimeValue(start)
  const quietHoursEnd = apiTimeValue(end)
  if ((quietHoursStart === null) !== (quietHoursEnd === null)) {
    return {
      ok: false,
      message: "Quiet hours need both a start and an end time. Set both, or clear both.",
    }
  }
  return { ok: true, update: { quietHoursStart, quietHoursEnd } }
}

/**
 * Whether quiet hours wrap past midnight, for the summary line only.
 *
 * Purely descriptive — the backend supports a wrapping window and this changes
 * no request. It exists because "22:00 to 07:00" read literally is an empty
 * range, and a reader who cannot tell whether we understood them that way has no
 * way to check short of waiting until 2am.
 */
export function quietHoursSummary(start: string | null, end: string | null): string | null {
  const from = timeInputValue(start)
  const to = timeInputValue(end)
  if (from === "" || to === "") return null
  const overnight = from > to
  return overnight
    ? `Pushes are held between ${from} and ${to} the next morning.`
    : `Pushes are held between ${from} and ${to}.`
}
