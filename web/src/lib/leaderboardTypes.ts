/*
 * Wire types for S-29, mirroring `lemely/web/schemas_leaderboard.py` and
 * `lemely/web/schemas_student_classes.py` field for field.
 *
 * `JoinClassResponse` below is the one exception: it mirrors
 * `JoinClassResponseDTO` from the sibling `lemely/web/schemas_classes.py`
 * (the `POST /api/student/classes/join` response), not either module named
 * above. It lives here rather than in its own file because it answers the
 * same question — "which class" — as `StudentClass` two exports below, and a
 * screen reading one is reading both.
 *
 * **These types carry no mark, grade or percentage, and that is structural.**
 * The backend DTOs do not declare such a field (D5.1 §0) and
 * `tests/test_schemas_leaderboard.py` fails if one is ever added, so this
 * mirror has nothing to filter out. Do not add a "score" or "average" here
 * either — there would be nothing on the wire to populate it from.
 *
 * `streak: number | null` is the one contract worth stating twice: `null`
 * means the student has **no `streaks` row at all**, while `0` is a real
 * broken streak (D5.14 §2). The screen must render the first as absent and
 * never as "0 days" — that would be a claim about someone the database knows
 * nothing about (UI spec §1.4).
 */

/** The four ranking scopes (`LeaderboardScope`). */
export type LeaderboardScope = "friends" | "class" | "school" | "global"

/**
 * The XP basis: all subjects, or one subject's code.
 *
 * A plain string rather than a union of subject codes — the codes come from
 * the student's own declared enrolments at runtime, and hardcoding
 * `"0580" | "0606" | "0625"` here would need an edit every time a board is
 * added.
 */
export type LeaderboardBasis = string

export interface LeaderboardRow {
  userId: string
  displayName: string
  xp: number
  /** Standard competition ranking: equal XP earns equal rank, and ties skip
   * the next rank (1, 2, 2, 4). Never re-derive this from array position. */
  rank: number
  /** `null` means no `streaks` row exists; `0` is a real broken streak. */
  streak: number | null
}

export interface LeaderboardViewer {
  userId: string
  displayName: string
  xp: number
  /** `null` when the viewer has no XP this week or has opted out — never a
   * fabricated last place. */
  rank: number | null
  streak: number | null
}

export interface Leaderboard {
  /** `"unavailable"` is a **successful** response, not an error: the school
   * scope has nothing to rank the viewer against because they hold no seat.
   * It is a different claim from an empty board, which would assert "nobody
   * scored this week". */
  status: "ok" | "unavailable"
  unavailableReason: "no_school" | null
  /** Monday, Cairo (D5.1 §6). A date, not a timestamp. */
  weekStart: string
  /** Sunday, Cairo. The reset boundary the screen counts down to in whole
   * civil days — there is no hour-precision on the wire to spend. */
  weekEnd: string
  /** Top-N ranked rows. Never contains an opted-out student (removed in the
   * query's own WHERE clause), and empty when `status === "unavailable"`. */
  rows: LeaderboardRow[]
  /** The viewer's own pinned row. `null` iff `status === "unavailable"`. */
  viewer: LeaderboardViewer | null
  /** Stated explicitly rather than inferred from a null rank: "you opted out"
   * and "you have no XP this week" are different sentences owed to different
   * students. */
  viewerOptedOut: boolean
}

/** One class the student is enrolled in (`StudentClassDTO`, D5.14 §1). */
export interface StudentClass {
  classId: string
  name: string
  /** `null` for a class its teacher never scoped to a subject. */
  subjectCode: string | null
  /** `null` for an independent teacher's class — genuinely no school, not
   * "unknown". */
  schoolName: string | null
}

/** `GET /api/student/classes` response. An empty list is a normal account
 * state (a direct subscriber with no teacher), never an error. */
export interface StudentClassList {
  classes: StudentClass[]
}

/**
 * `POST /api/student/classes/join` response (`JoinClassResponseDTO`,
 * `schemas_classes.py`). The class the caller just joined, or was already
 * enrolled in — the endpoint is idempotent, so a repeat call with the same
 * code returns the same body rather than an error.
 */
export interface JoinClassResponse {
  classId: string
  className: string
}
