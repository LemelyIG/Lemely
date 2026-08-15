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
 * `tests/test_design_tokens.py` pins it against the Python definition, so the
 * two cannot drift silently — the same technique that file already uses to pin
 * CSS tokens against DESIGN.md.
 */

/**
 * Mirror of `lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD`. Below this, the
 * backend asks a human to look. Pinned by `tests/test_design_tokens.py`.
 */
export const REVIEW_CONFIDENCE_THRESHOLD = 0.9

/** The subset of a corrected question this bucketing reads. */
export interface ConfidenceInput {
  /** The backend's explicit "a human needs to look at this" signal. */
  reviewReason?: string
  /** 0–1. Absent on question types that carry no confidence score. */
  confidence?: number
}

/**
 * `reviewReason` always wins: it is a decision the backend already made, and a
 * question can be flagged for review at any confidence (integrity checks set it
 * without touching the score at all).
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
  if (q.reviewReason) return "needs-review"
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
} {
  return questions.reduce(
    (acc, q) => {
      const tier = confidenceTierFor(q)
      if (tier === "confident") acc.confident += 1
      else if (tier === "uncertain") acc.uncertain += 1
      else acc.needsReview += 1
      return acc
    },
    { confident: 0, uncertain: 0, needsReview: 0 },
  )
}
