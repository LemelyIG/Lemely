import type { ReviewGrade, ReviewResultDTO } from "@/lib/flashcardTypes"

/*
 * S-23's optimistic grading state (Task 7 / B5a).
 *
 * `FlashcardReview.tsx` advances `index` the instant a grade button is
 * pressed — the network call is not on the critical path of moving to the
 * next card. This reducer is what catches the request up once it settles:
 * a success joins `results` (the only thing the end-of-session summary
 * reads — `summarizeSession` in `flashcardData.ts`), a failure joins
 * `failed` (what the retry banner renders), and `inFlight` always drops by
 * one, regardless of which branch a card takes.
 */

/** A grade that reached the server but was never confirmed. */
export interface FailedGrade {
  cardId: string
  front: string
  grade: ReviewGrade
}

export interface FlashcardSessionState {
  results: ReviewResultDTO[]
  failed: FailedGrade[]
  inFlight: number
}

export type GradeOutcome =
  | { kind: "settled"; result: ReviewResultDTO }
  | { kind: "failed"; cardId: string; front: string; grade: ReviewGrade }

/**
 * Fold one settled or failed grade into the session state.
 *
 * A settled outcome always clears any earlier failure recorded for the same
 * card — the one path by which a retry banner entry disappears — because a
 * card can only be graded once at a time and a later settle is the true,
 * current answer for it.
 */
export function applyGradeOutcome(
  session: FlashcardSessionState,
  outcome: GradeOutcome,
): FlashcardSessionState {
  const inFlight = session.inFlight - 1

  if (outcome.kind === "settled") {
    return {
      results: [...session.results, outcome.result],
      failed: session.failed.filter((f) => f.cardId !== outcome.result.card.id),
      inFlight,
    }
  }

  return {
    results: session.results,
    failed: [
      ...session.failed.filter((f) => f.cardId !== outcome.cardId),
      { cardId: outcome.cardId, front: outcome.front, grade: outcome.grade },
    ],
    inFlight,
  }
}
