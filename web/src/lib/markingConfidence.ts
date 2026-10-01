import type { ConfidenceTier } from "@/components/ui/confidence-indicator"

/*
 * P4.2 · Where a mark's confidence gets its tier.
 *
 * THE DEFECT THIS EXISTS TO FIX. `PaperResult` bucketed confidence against
 * **0.85**, described in its own comment as "a frontend judgement call made for
 * this retrofit". The backend's threshold is **0.90**
 * (`lemely/core/schemas.py::REVIEW_CONFIDENCE_THRESHOLD`), it is not
 * operator-tunable, and the teacher portal reports against it directly
 * (`routers/teacher.py:688` counts `confidence_score >= REVIEW_CONFIDENCE`).
 *
 * So a mark at 0.87 was called "confident" on the student's copy of the paper
 * and "not confident" on the teacher's copy of the same paper. Two readers,
 * one mark, two answers — and the number the *student* was shown was the
 * invented one. That is worse than a cosmetic inconsistency: the whole claim
 * this product makes about its marking is that it tells you when it is unsure,
 * and a student is the reader least able to notice that the line moved.
 *
 * The landing page has already been corrected on this point once: `data.ts`
 * records that its stated "confidence floor" read 0.70, which was simply the
 * wrong number. This is the same number, wrong in a different place.
 *
 * The constant is duplicated here rather than imported because it lives in
 * Python and there is no shared schema artefact between the two languages.
 * `tests/test_web_shared_constants.py` pins it against the Python definition, so
 * the two cannot drift silently — the same technique `tests/test_design_tokens.py`
 * already uses to pin CSS tokens against DESIGN.md. (This comment and the one on
 * the constant below named `test_design_tokens.py` itself until task #36; that
 * file contains no reference to this one, and the pin has always lived in
 * `test_web_shared_constants.py`.)
 */

/**
 * Mirror of `lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD`. Below this, the
 * backend asks a human to look. Pinned by `tests/test_web_shared_constants.py`.
 */
export const REVIEW_CONFIDENCE_THRESHOLD = 0.9

/**
 * Mirror of `lemely.core.schemas.UNSCORED_MARKER_SOURCES`. Pinned against the
 * Python set by `tests/test_web_shared_constants.py`, the same file that pins
 * `REVIEW_CONFIDENCE_THRESHOLD` above.
 */
export const UNSCORED_MARKER_SOURCES: ReadonlySet<string> = new Set([
  "missing",
  "dropped",
  "blank",
])

/**
 * Did a marker (deterministic or AI) actually form an opinion about this
 * question? The single frontend formulation — mirror of
 * `lemely.core.schemas.marker_scored`.
 *
 * `undefined` reads as scored. Several callers have no marker source on the
 * wire at all (`ReviewQueueItemDTO`, a live `/student/correct` frame), and
 * before this function existed each of them spelled the check out itself:
 * `markerSource === "missing" || markerSource === "dropped"`, in two places,
 * which is how `"blank"` would have been missed in both. Treating an absent
 * value as scored preserves exactly what those spellings did.
 *
 * A `false` question's `confidence` is a placeholder, not a signal: it must
 * not reach a confidence tier, a tone, or a summary count as if a marker had
 * produced it.
 */
export function markerScored(markerSource?: string | null): boolean {
  if (markerSource == null) return true
  return !UNSCORED_MARKER_SOURCES.has(markerSource)
}

/** The subset of a corrected question this bucketing reads. */
export interface ConfidenceInput {
  /** The backend's explicit "a human needs to look at this" signal. */
  reviewReason?: string
  /** 0–1. Absent on question types that carry no confidence score. */
  confidence?: number
  /**
   * The backend's own per-question "does this need a human" signal (mirrors
   * `QuestionResultDTO.needsTeacherReview`) — distinct from `reviewReason`.
   *
   * US-039 MUST-FIX 2 (independent review, blocking 674f309d): `reviewReason`
   * alone used to mean "needs review" for every case except one --
   * `_build_blank_corrected`'s unflagged blank, which sets a `reviewReason`
   * message purely so the review queue/DB can tell a genuine blank apart from
   * every other blank-shaped state, while deliberately leaving
   * `needsTeacherReview` false. `undefined` (every existing caller, and every
   * other `reviewReason`-setting path) preserves today's behaviour: only an
   * explicit `false` suppresses the review signal.
   */
  needsTeacherReview?: boolean
  /**
   * The backend's own per-question marking method (mirrors
   * `QuestionResultDTO.markerSource`). Read through `markerScored` above:
   * `"missing"`, `"dropped"` and `"blank"` all mean no marker (human or AI)
   * ever produced an opinion about this question. Optional because several
   * callers (`Review.tsx`'s queue-list row, `ReviewQueueItemDTO`) have no
   * marker source on the wire at all — `undefined` behaves exactly as before
   * this field existed.
   */
  markerSource?: string
  /**
   * Whether a teacher review is open for this question *right now*
   * (`QuestionResultDTO.pendingTeacher`) — as opposed to `reviewReason`,
   * which is the marker's record of why it was once flagged and is never
   * rewritten. `undefined` where nothing computed this (a teacher-console
   * grade, a live `/student/correct` frame): those sources have no queue to
   * ask, so this function falls back to `reviewReason` exactly as before.
   * `false` is a positive, current claim that nothing is pending, and wins
   * over a stale `reviewReason` outright — a self-mark that settled the
   * queue row does not leave a "needs review" chip on a "3/3" question.
   *
   * NOT the same field as `needsTeacherReview` above, and neither is a rename
   * of the other: that one is the marker's flag frozen at marking time, this
   * one is the live queue state. Both are read below, in that order, and
   * dropping either loses a fix — see the guard order there.
   */
  pendingTeacher?: boolean
}

/**
 * US-039 finding G: a genuinely-blank answer (`_build_blank_corrected`) gets
 * `confidence = 0.0` and `needsTeacherReview = false` — the backend's
 * deliberate "unflagged zero", exempting a question no marker ever looked at
 * from the review queue. Before this tier existed that combination fell
 * through to `q.confidence < REVIEW_CONFIDENCE_THRESHOLD` and came out
 * `"uncertain"`, which tells the student "the marker looked and was unsure" —
 * false, because no marker looked. `"not-marked"` is the honest third
 * tier: neither a pass nor a warning, matching the "not marked" label
 * `PaperResult.markerSourceLabel` already renders for the same
 * `markerSource` values.
 *
 * `pendingTeacher === false` then wins: it is the current truth about whether
 * a teacher is going to look, and a `reviewReason` frozen from marking time
 * cannot outrank it (a resolved question must not still read "needs review"
 * merely because `reviewReason` is immutable by design).
 *
 * Short of that, `reviewReason` wins whenever `needsTeacherReview` is not
 * explicitly `false`: it is a decision the backend already made, and a
 * question can be flagged for review at any confidence (integrity checks set
 * it without touching the score at all). The one exception is the unflagged
 * blank described on `ConfidenceInput.needsTeacherReview` above, which the
 * `not-marked` guard names explicitly rather than letting it fall through to
 * the score check.
 *
 * ORDER MATTERS, AND `not-marked` MUST COME FIRST. `pendingTeacher === false`
 * is *true* for an unflagged blank — no review is open for it, by design —
 * so putting that guard first returns `"confident"`: the marker is confident
 * about a question no marker read. That is strictly worse than the
 * `"uncertain"` this tier was added to replace, and it leaves `not-marked`
 * dead code. Measured on a paper of 8 blanks + 2 clean marks, guard-first
 * gives `confident: 10`.
 *
 * Putting `not-marked` first does NOT cost the `pendingTeacher` fix, which was
 * the row that could not be settled by reading: a question a self-mark has
 * settled has a real `markerSource` (`"ai"`), so it fails the `not-marked`
 * gate, falls through, and still returns `"confident"`.
 *
 * `confidenceSummaryOf`'s four-key return type is the third part of the same
 * spec, not a separate concern: with a three-key summary, `not-marked` falls
 * through the final `else` into `needsReview` and the strip reports
 * `needsReview: 8` on those same 8 blanks — the exact "8 items a teacher
 * bulk-dismisses" outcome US-039 removed from the queue, the tier and the DB.
 * Guard order, four-key return type, and the five `ConfidenceInput` fields are
 * one spec; any two of the three is half a spec.
 *
 * A missing or non-finite `confidence` is treated as confident rather than
 * uncertain. That is deliberate and it is the arguable call in this function:
 * the alternative is to mark every question with no score as "uncertain", which
 * on an MCQ paper — where marking is deterministic string comparison and there
 * is no judgement to be unsure about — would flag all forty questions as
 * doubtful. `reviewReason` remains the escape hatch for the cases that are
 * genuinely in doubt.
 */
export function confidenceTierFor(q: ConfidenceInput): ConfidenceTier {
  // FIRST — see the guard-order note above. `pendingTeacher === false` is true
  // for a question no marker read, so the guard below would claim "confident"
  // for it.
  if (q.needsTeacherReview === false && !markerScored(q.markerSource)) {
    return "not-marked"
  }
  if (q.pendingTeacher === false) return "confident"
  if (q.reviewReason && q.needsTeacherReview !== false) return "needs-review"
  if (typeof q.confidence !== "number" || !Number.isFinite(q.confidence)) {
    return "confident"
  }
  return q.confidence < REVIEW_CONFIDENCE_THRESHOLD ? "uncertain" : "confident"
}

/** Tier counts across a paper, for the summary strip above the question list. */
export function confidenceSummaryOf(questions: ConfidenceInput[]): {
  confident: number
  uncertain: number
  needsReview: number
  notMarked: number
} {
  return questions.reduce(
    (acc, q) => {
      const tier = confidenceTierFor(q)
      if (tier === "confident") acc.confident += 1
      else if (tier === "uncertain") acc.uncertain += 1
      else if (tier === "not-marked") acc.notMarked += 1
      else acc.needsReview += 1
      return acc
    },
    { confident: 0, uncertain: 0, needsReview: 0, notMarked: 0 },
  )
}
