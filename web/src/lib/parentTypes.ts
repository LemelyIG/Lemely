/*
 * TS interfaces mirroring lemely/web/schemas_parent.py field-for-field
 * (camelCase). That module is the authoritative source for what each field
 * means and, crucially, where it comes from — every field there carries a
 * provenance note. Read it before rendering anything here as a claim.
 *
 * Two honesty constraints the backend encodes and the UI must not paper over:
 *
 *   - `SubjectOverview.target` is **always null** today. No target-grade
 *     column exists anywhere until Phase 4's onboarding questionnaire (D3.3 /
 *     D3.11), so "predicted vs target" renders as "no target set" — never a
 *     defaulted target, and never a target back-derived from predictedGrade,
 *     which would make every child look on track.
 *   - Nullable numeric/date fields mean *absent*, never zero. A child with no
 *     recorded activity has `lastActivityAt: null`; rendering that as "0 days
 *     ago" or "0%" invents a fact.
 */

// ── Parent links (shared with the student-side invite routes) ───────────────

/**
 * A parent linked to the current student. `email` is the parent-invites
 * design's addition (superseding D3.11): a parent is an ordinary email/
 * password account now, so this is always present, unlike `phone`, which
 * stays nullable — kept, unused by any live signup path, per D3.11's own
 * scope note in the design spec ("kept untouched for a possible future paid
 * SMS channel").
 */
export interface LinkedParent {
  parentId: string
  displayName: string
  email: string
  phone: string | null
}

export interface ParentLinkList {
  parents: LinkedParent[]
}

// ── Student-side parent invites (design spec §4, superseding D3.11) ────────

/**
 * The student's single reusable parent code, always present — `invite_repo.
 * py`'s `get_or_create_parent_code` mints one lazily the first time it is
 * asked for, the same "a class always has a join code" rule `classes.
 * join_code` already follows. `url` is the ready-to-share `/join/<code>`
 * link, built server-side from `settings.email.app_base_url` — never
 * assembled client-side, so this screen carries no opinion about the
 * product's own origin.
 */
export interface ParentInviteCode {
  code: string
  url: string
}

/** One single-use, 7-day link the student has minted and not yet spent,
 * revoked, or expired. */
export interface ParentInviteLink {
  code: string
  url: string
  expiresAt: string
}

/** `GET /api/student/parent-invites` — the whole of what `Parents.tsx`
 * (student) needs to render the "Your parent code" card and the pending
 * one-time-link list in a single request. */
export interface ParentInvites {
  code: ParentInviteCode
  links: ParentInviteLink[]
}

// ── P-01: parent home / children ────────────────────────────────────────────

export interface ChildClass {
  name: string
  subjectCode: string | null
  /** null for an independent teacher's class — not a missing value to fill in. */
  schoolName: string | null
}

export interface ChildSummary {
  childId: string
  displayName: string
  classes: ChildClass[]
  /**
   * A plain-language translation of the child's real grade-bearing subjects and
   * at-risk flags, composed by the backend (`_status_line`). Render it as
   * given — it is not a template the client fills in.
   */
  statusLine: string
  /** Percentage-point delta between the latest paper and its prior attempt. */
  trend: number | null
  /** Most recent record of any kind — a quiz counts as activity (D3.9). */
  lastActivityAt: string | null
}

export interface ChildList {
  children: ChildSummary[]
}

// ── Shared across P-02 / P-03 / P-04 ────────────────────────────────────────

export interface ParentAtRiskFlag {
  reason: string
  summary: string
  evidence: Record<string, string | number | number[]>
}

export interface WeakTopic {
  topic: string
  lostMarks: number
  maximumMarks: number
  accuracy: number
}

export interface RecentPaper {
  paperId: string
  subjectCode: string
  subjectName: string
  marks: string
  grade: string
  recordedAt: string
}

export interface ChildActivity {
  /** Real past papers only (`is_paper`) — it says *papers*, so it counts papers. */
  totalPapers: number
  lastActiveAt: string | null
  daysSinceLastActivity: number | null
}

// ── P-02: child overview ────────────────────────────────────────────────────

export interface SubjectTrendPoint {
  recordedAt: string
  percentage: number
}

export interface SubjectOverview {
  subjectCode: string
  /** Translated name, falling back to the raw code when unknown — never invented. */
  subjectName: string
  qualificationLevel: string | null
  predictedGrade: string
  /** Always null until Phase 4 (see the module header). */
  target: string | null
  latestPercentage: number
  paperCount: number
  /** Oldest first. */
  trend: SubjectTrendPoint[]
}

export interface ChildOverview {
  childId: string
  displayName: string
  subjects: SubjectOverview[]
  recentPapers: RecentPaper[]
  weakTopics: WeakTopic[]
  activity: ChildActivity
  atRiskFlags: ParentAtRiskFlag[]
}

// ── P-03: child subject detail ──────────────────────────────────────────────

export interface SubjectPaper {
  paperId: string
  marks: string
  grade: string
  recordedAt: string
}

export interface GradeBoundaryDistance {
  nextGrade: string
  marksNeeded: number
  summary: string
}

export interface SubjectDetail {
  childId: string
  subjectCode: string
  subjectName: string
  qualificationLevel: string | null
  predictedGrade: string
  papers: SubjectPaper[]
  /** null when not computable (already on A*, or no boundary row) — omit the panel. */
  boundaryDistance: GradeBoundaryDistance | null
  weakTopics: WeakTopic[]
}

// ── P-04: child weaknesses ──────────────────────────────────────────────────

export interface ChildWeaknesses {
  childId: string
  /** Ranked worst-accuracy-first by the backend; do not re-sort. */
  weakTopics: WeakTopic[]
}
