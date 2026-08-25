/*
 * TS interfaces mirroring `lemely/web/schemas_admin.py` (camelCase), for the
 * platform-admin console (UI spec X-01/X-02/X-03).
 *
 * Scoped by role rather than by portal, like `schoolTypes.ts` and `meTypes.ts`:
 * `/api/admin/*` is gated to `platform_admin` alone, and no other role can reach
 * a single field in this file.
 *
 * Every field here is a counted fact. Where the spec asks for something the
 * system does not record, the backend sends `null` or prose and says why —
 * `markingAccuracyNote` is the one prose field in the family, and it exists
 * because a fabricated accuracy figure on the console nobody checks is the worst
 * place in the product to put one.
 */

/** `GET /api/admin/overview` → `counts`. Global row counts and live depths. */
export interface PlatformCounts {
  students: number
  parents: number
  teachers: number
  schoolAdmins: number
  platformAdmins: number
  schools: number
  classes: number
  /** Past-paper attempts only. A quiz submission is an attempt row the marking
   * pipeline never ran, so it is not throughput. */
  papersMarkedTotal: number
  papersMarkedLast24Hours: number
  papersMarkedLast7Days: number
  openReviewItems: number
  /** Keyed by `UploadStatus` value. Every status is present, zeroes included —
   * do not read "no failures" off a missing key. */
  uploadsByStatus: Record<string, number>
}

/** Gemini spend against the configured hard ceiling.
 *
 * `ceilingUsd` and `remainingUsd` are null together when no ceiling is
 * configured. That is a real state and is not the same as a ceiling of zero. */
export interface Spend {
  cumulativeUsd: number
  ceilingUsd: number | null
  remainingUsd: number | null
  /** The marks the runtime sends warnings at. A spend figure without its alarm
   * points cannot be read as safe or unsafe. */
  thresholdsUsd: number[]
}

/** What the console can honestly assert about the deployment. No uptime and no
 * dependency ping: nothing records them, and a green light with no check behind
 * it is worse than no light. */
export interface SystemHealth {
  databaseReachable: boolean
  geminiKeyConfigured: boolean
  version: string
}

/** One recently created account, any role. */
export interface Signup {
  userId: string
  email: string
  displayName: string | null
  role: string
  createdAt: string
}

/** Response for `GET /api/admin/overview` (X-01). */
export interface PlatformOverview {
  counts: PlatformCounts
  spend: Spend
  health: SystemHealth
  recentSignups: Signup[]
}

/** One subscription awaiting a manual decision (X-02).
 *
 * `priceMinor` is in `currency`'s minor unit, exactly as `plan_tiers` stores it.
 * The API passes it through unconverted; formatting happens once, on screen. */
export interface PendingActivation {
  subscriptionId: string
  userId: string
  email: string
  displayName: string | null
  role: string
  planCode: string
  planName: string
  priceMinor: number
  currency: string
  requestedAt: string
}

/** Response for `GET /api/admin/activations`. Oldest first. */
export interface ActivationQueue {
  pending: PendingActivation[]
}

/** Response for either decision route. `status` is `"active"` or `"rejected"` —
 * never `"cancelled"`, which means the subscriber ended it (migration 0019). */
export interface ActivationResult {
  subscriptionId: string
  status: string
}

/** Mark-scheme coverage for one subject (X-03). */
export interface SubjectCoverage {
  subjectCode: string
  papers: number
  papersWithScheme: number
  papersWithoutScheme: number
}

/** Response for `GET /api/admin/pipeline` (X-03). */
export interface PipelineHealth {
  subjects: SubjectCoverage[]
  /** Observed across recorded past-paper attempts, keyed by boundary source.
   * `exact` means a published boundary was found; the other two mean one was
   * substituted. This is the measured answer to "real or estimated". */
  boundarySourceCounts: Record<string, number>
  exactBoundaryKeys: number
  subjectDefaultBoundaryKeys: number
  uploadsByStatus: Record<string, number>
  recentFailedUploadIds: string[]
  /** Prose, not a number, and the only such field in this family. Accuracy
   * against the golden fixture set is produced by the harness into `reports/`,
   * not by anything a request can reach. */
  markingAccuracyNote: string
}

// ── Schools (D7.8, spec §1.1: the account graph's missing first link) ──────
//
// Before `lemely/web/routers/admin.py` grew these four routes, no production
// code path created a `School` row or a `school_admin` account, so
// `POST /api/school/teachers/invite` — the only teacher-creation path D1.7
// allows — was unreachable in any real deployment. Mirrors
// `lemely/web/schemas_admin.py` field-for-field, same as every interface
// above it in this file.

/** One school_admin staffing a school, for the roster on the schools list. */
export interface SchoolAdminSummary {
  userId: string
  email: string
  displayName: string | null
}

/** One school's provisioning state: quota, seat usage, and its admins.
 *
 * `seatsAssigned` counts non-revoked seats — the identical definition
 * `SeatUsage`'s own `used` already uses (`schoolTypes.ts`), so a seat count
 * never means two different things depending on which screen reads it.
 * `seatsAvailable` is sent rather than left for the screen to derive, so
 * "how many seats are free" is a counted fact in every reader, not a
 * `quota - assigned` a screen could get wrong at the edges (it is never
 * negative on the wire, even when usage briefly exceeds a lowered quota). */
export interface SchoolSummary {
  schoolId: string
  name: string
  seatQuota: number
  seatsAssigned: number
  seatsAvailable: number
  admins: SchoolAdminSummary[]
}

/** Response for `GET /api/admin/schools`. Every school on the platform — a
 * platform admin has no tenant to scope to (D1.6/D1.10), so this is
 * everything there is, not a caller-owned subset. */
export interface SchoolList {
  schools: SchoolSummary[]
}

/** Body for `POST /api/admin/schools`. `seatQuota` is required rather than
 * defaulted: a platform admin creating a school is the one moment a real
 * commercial quota should be set (D7.2 is why self-service signup never gets
 * to create a school at all — it would carry a quota of 0 and sit unusable
 * until a platform admin intervened anyway). */
export interface CreateSchoolRequest {
  name: string
  seatQuota: number
}

/** Body for `PATCH /api/admin/schools/{id}`. Both fields optional and
 * independently settable, so a name correction is never forced to resend
 * (and risk clobbering) a quota someone else is mid-edit on. A quota that
 * would fall below the seats already assigned is refused with a 409 naming
 * both numbers — see `schoolUpdateFailureMessage` in `adminOutcome.ts`. */
export interface UpdateSchoolRequest {
  name?: string | null
  seatQuota?: number | null
}

/** Body for `POST /api/admin/schools/{id}/admins`. Same credential handling
 * as `InviteTeacherRequest` (`schoolTypes.ts`): no email provider exists in
 * v1 (D7.6), so `password` is left unset here and the backend always
 * generates one rather than the console ever asking a platform admin to
 * invent a credential. */
export interface CreateSchoolAdminRequest {
  email: string
  displayName?: string | null
  password?: string | null
}

/** Response for `POST /api/admin/schools/{id}/admins`. `temporaryPassword` is
 * non-null only when the caller omitted `password` in the request — true for
 * every call this console makes. Shown once: the backend keeps only its
 * hash, and no email is sent for it in v1. */
export interface CreateSchoolAdminResponse {
  userId: string
  membershipId: string
  email: string
  temporaryPassword: string | null
}
