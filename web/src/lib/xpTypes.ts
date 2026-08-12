/*
 * Wire types for S-31, mirroring `lemely/web/schemas_xp.py` field for field.
 *
 * **`bySource` is XP per source, never a count of actions** (D5.13 §3).
 * `paper_corrected: 150` is tempting to read as "three papers"; D5.1 §3's daily
 * caps mean a capped award writes no row at all, and §8's dedupe means a
 * re-corrected paper writes one row for two markings. Any count derived from
 * this is wrong by construction, which is why there is no `count` field here
 * and why the screen labels every one of these numbers as XP.
 *
 * **The level curve is on the wire, not in this file.** `levelStartXp` and
 * `nextLevelXp` come from the server (`lemely/web/xp_levels.py`), so a progress
 * bar needs no arithmetic and there is no second, drifting copy of the curve in
 * TypeScript. Do not add one.
 */

/** One of the four `xpsource` values D5.1 §1 fixes as Phase 5's whole scope. */
export type XpSource =
  | "paper_corrected"
  | "quiz_completed"
  | "flashcard_reviewed"
  | "study_session_completed"

export interface XpSourceAmount {
  source: XpSource
  /** XP, not a tally of actions. See this file's header. */
  xp: number
}

export interface XpWeek {
  /** Monday, Cairo (D5.1 §6) — the same window the leaderboard uses, resolved
   * by the same helper, so S-29 and S-31 cannot report two different weeks. */
  start: string
  end: string
  total: number
  /** All four sources, always, `0` for any that earned nothing — so a chart
   * never has to special-case a missing key. */
  bySource: XpSourceAmount[]
}

export interface XpDay {
  day: string
  xp: number
}

export interface Streak {
  current: number
  longest: number
  /** `null` for a student who has never earned XP — never a fabricated
   * "today". */
  lastActiveOn: string | null
  freezesAvailable: number
}

/** `GET /api/student/xp` — S-31's whole data dependency. */
export interface XpProfile {
  totalXp: number
  level: number
  /** XP at which the current level began; `totalXp - levelStartXp` is progress
   * into it. */
  levelStartXp: number
  /** XP at which the next level begins. Always strictly greater than
   * `levelStartXp`, so a progress bar's denominator is never zero. */
  nextLevelXp: number
  streak: Streak
  week: XpWeek
  /**
   * The days in the window that earned XP, oldest first.
   *
   * **Days with no XP are absent, not zero-valued** (D5.13 §4). Fill the grid
   * from `calendarStart`/`calendarEnd` and render an absent day exactly as a
   * zero one — treating them differently would invent a distinction the
   * backend deliberately does not make.
   */
  calendar: XpDay[]
  calendarStart: string
  calendarEnd: string
}
