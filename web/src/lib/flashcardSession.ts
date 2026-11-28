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
  /** The idempotency key minted with this rating; a Retry re-sends it so the server replays. */
  clientReviewId: string
}

/** One idempotency key per rating. Minted when the grade is pressed, kept on a failure. */
export function newClientReviewId(): string {
  return crypto.randomUUID()
}

export interface FlashcardSessionState {
  results: ReviewResultDTO[]
  failed: FailedGrade[]
  inFlight: number
  /** Consecutive "knew it" grades (anything but Again) in this session. */
  combo: number
  bestCombo: number
}

export function startSession(): FlashcardSessionState {
  return { results: [], failed: [], inFlight: 0, combo: 0, bestCombo: 0 }
}

/** A grade was pressed: count it in flight and move the combo. Called before the request. */
export function registerGrade(state: FlashcardSessionState, grade: ReviewGrade): FlashcardSessionState {
  const combo = grade === "again" ? 0 : state.combo + 1
  return { ...state, inFlight: state.inFlight + 1, combo, bestCombo: Math.max(state.bestCombo, combo) }
}

/** "Retry" on the banner: every failed grade is re-sent at once. */
export function beginRetry(state: FlashcardSessionState): {
  state: FlashcardSessionState
  retries: FailedGrade[]
} {
  return {
    state: { ...state, failed: [], inFlight: state.inFlight + state.failed.length },
    retries: state.failed,
  }
}

export function knewCount(results: readonly ReviewResultDTO[]): number {
  return results.filter((r) => r.grade !== "again").length
}

/** XP the server actually awarded (capped days award 0). Never an estimate. */
export function xpEarned(results: readonly ReviewResultDTO[]): number {
  return results.reduce((sum, r) => sum + r.xpAwarded, 0)
}

export type GradeOutcome =
  | { kind: "settled"; result: ReviewResultDTO }
  | { kind: "failed"; cardId: string; front: string; grade: ReviewGrade; clientReviewId: string }

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
      ...session,
      results: [...session.results, outcome.result],
      failed: session.failed.filter((f) => f.cardId !== outcome.result.card.id),
      inFlight,
    }
  }

  return {
    ...session,
    results: session.results,
    failed: [
      ...session.failed.filter((f) => f.cardId !== outcome.cardId),
      {
        cardId: outcome.cardId,
        front: outcome.front,
        grade: outcome.grade,
        clientReviewId: outcome.clientReviewId,
      },
    ],
    inFlight,
  }
}
