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
