/*
 * TS interfaces mirroring lemely/web/schemas_me.py field-for-field (camelCase).
 * `/api/me/*` is reachable by every authenticated role (teacher, student,
 * parent, school_admin, platform_admin) — unlike teacherTypes.ts/studentTypes.ts,
 * this module isn't scoped to one portal.
 */

/**
 * Response for `GET /api/me/profile` (mirrors `ProfileDTO`). `displayName` is
 * nullable — a caller who never set one — and must be rendered as an honest
 * absence (e.g. the email's local part, or the role), never a fabricated name.
 * `emailVerified` is D7.5's gate condition, read by the verify-email banner.
 */
export interface Profile {
  displayName: string | null
  email: string
  role: string
  /**
   * `users.email_verified_at is not None`, published by `ProfileDTO` for the
   * verify-email banner. Required, not optional: the pipeline deploys the
   * backend before the frontend (`deploy-frontend` declares
   * `needs: [resolve-env, deploy-backend]` in `.github/workflows/deploy.yml`),
   * so a client that reads this field is never published against a server
   * that does not serve it.
   */
  emailVerified: boolean
  /**
   * A short-lived signed URL for the caller's uploaded profile picture, or
   * `null` when none is set. Not a stable identifier: it expires, so it must
   * never be cached beyond the lifetime of this `Profile` object or persisted
   * anywhere — always re-read from a fresh `/me/profile` fetch.
   */
  avatarUrl: string | null
}

// ── Student onboarding profile (P4.3 chunk B, D4.5 / P4.8 chunk A) ─────────
//
// Mirrors `lemely/web/schemas_student_profile.py` field-for-field. Every
// scalar on `StudentProfile` and every optional field on `SubjectEnrolment`
// is nullable, matching the backend's D4.5 rule: a skipped S-02 answer is
// `NULL`, never a defaulted sentinel. `StudentProfileUpdate` is a genuine
// partial update — a key entirely absent from the object is left untouched
// server-side (`JSON.stringify` drops `undefined`-valued keys, so building
// the payload with only the touched keys present reproduces the backend's
// `model_fields_set` semantics without a client-side "was this touched" flag
// leaking into the wire format); an explicit `null` on a present key clears
// that field.

/** One (topic, rating) self-assessment pair (mirrors `ConfidenceRatingDTO`).
 * `topic` is the P4.2 `"<code> <name>"` vocabulary shared with the bank and
 * the weakness engine — never a free-typed string. `rating` is 1..5. */
export interface ConfidenceRating {
  topic: string
  rating: number
}

/** One subject enrolment, with its papers and confidence ratings (S-01).
 * Mirrors `SubjectEnrolmentDTO`. */
export interface SubjectEnrolment {
  subjectCode: string
  qualificationLevel: string | null
  targetGrade: string | null
  sessionMonth: string | null
  sessionYear: number | null
  papers: number[]
  confidenceRatings: ConfidenceRating[]
}

/** The scalar onboarding fields (S-02) — mirrors `StudentProfileDTO`. */
export interface StudentProfile {
  qualificationLevel: string | null
  gradeLevel: string | null
  schoolName: string | null
  hasExternalLessons: boolean | null
  weeklyStudyHours: number | null
  onboardingCompletedAt: string | null
  /**
   * Whether this student is hidden from public leaderboards (P5.3 chunk A).
   *
   * `NOT NULL` on the model with a `false` default, so unlike every field
   * above it is a plain boolean and never `null` — the column has no "not
   * answered" state to represent.
   */
  leaderboardOptOut: boolean
}

/** `GET /api/me/student-profile` response (mirrors `StudentProfileWithEnrolmentsDTO`). */
export interface StudentProfileWithEnrolments {
  profile: StudentProfile
  enrolments: SubjectEnrolment[]
}

/** Body for `PATCH /api/me/student-profile` (mirrors `StudentProfileUpdateDTO`).
 * Build with only the keys the student actually touched present — an
 * omitted key must never be sent as `undefined`, since a defaulted/sent
 * sentinel is exactly what D4.5 forbids. */
export interface StudentProfileUpdate {
  qualificationLevel?: string | null
  gradeLevel?: string | null
  schoolName?: string | null
  hasExternalLessons?: boolean | null
  weeklyStudyHours?: number | null
  /**
   * Deliberately `boolean | undefined`, **not** `boolean | null` like its
   * siblings above: `leaderboard_opt_out` is NOT NULL on the model, so an
   * explicit `null` is a 422 rather than a coerced `false`. Omit the key to
   * leave it alone; send a real boolean to change it.
   */
  leaderboardOptOut?: boolean
}

/** One item of a `PUT /api/me/student-profile/enrolments` body (mirrors
 * `EnrolmentUpsertDTO`). Every field here is the enrolment's full desired
 * state, not a patch — `papers: null`/omitted means "no papers". */
export interface EnrolmentUpsert {
  subjectCode: string
  qualificationLevel: string | null
  targetGrade: string | null
  sessionMonth: string | null
  sessionYear: number | null
  papers: number[] | null
}

/** Body for `PUT /api/me/student-profile/enrolments` (mirrors `EnrolmentListRequestDTO`). */
export interface EnrolmentListRequest {
  enrolments: EnrolmentUpsert[]
}

/** Body for `PUT /api/me/student-profile/enrolments/{subjectCode}/confidence-ratings`
 * (mirrors `ConfidenceRatingsUpdateDTO`). Full-replace: a topic omitted from
 * `ratings` has its existing rating deleted. */
export interface ConfidenceRatingsUpdate {
  ratings: Record<string, number>
}
