import { describe, expect, it } from "vitest"
import { applyGradeOutcome, type FlashcardSessionState } from "@/lib/flashcardSession"
import type { CardDTO, ReviewResultDTO } from "@/lib/flashcardTypes"

/*
 * Task 7 (B5a) · the pure reducer behind optimistic flashcard grading.
 *
 * `FlashcardReview.tsx` advances `index` the moment a grade button is
 * pressed, before the network call settles — this module is the state that
 * catches up once it does: a settled outcome joins `results` (what the
 * end-of-session summary reads), a failed one joins `failed` (what the
 * retry banner reads), and either way `inFlight` drops by one.
 */

function card(overrides: Partial<CardDTO> & { id: string }): CardDTO {
  return {
    front: "front",
    back: "back",
    position: 0,
    source: "manual",
    sourceQuestionId: null,
    repetitions: 0,
    easeFactor: 2.5,
    intervalDays: 0,
    lapses: 0,
    dueAt: "2026-08-09T00:00:00Z",
    lastReviewedAt: null,
    ...overrides,
  }
}

function reviewResult(overrides: Partial<ReviewResultDTO> & { card: CardDTO }): ReviewResultDTO {
  return {
    reviewId: "review-1",
    grade: "good",
    intervalBeforeDays: 1,
    intervalAfterDays: 3,
    ...overrides,
  }
}

function emptySession(overrides: Partial<FlashcardSessionState> = {}): FlashcardSessionState {
  return { results: [], failed: [], inFlight: 0, ...overrides }
}

describe("applyGradeOutcome", () => {
  it("a settled outcome appends to results and decrements inFlight", () => {
    const result = reviewResult({ card: card({ id: "c1" }) })
    const next = applyGradeOutcome(emptySession({ inFlight: 1 }), { kind: "settled", result })

    expect(next.results).toEqual([result])
    expect(next.failed).toEqual([])
    expect(next.inFlight).toBe(0)
  })

  it("a failed outcome appends to failed, not results, and decrements inFlight", () => {
    const next = applyGradeOutcome(emptySession({ inFlight: 1 }), {
      kind: "failed",
      cardId: "c1",
      front: "What is 2+2?",
      grade: "again",
    })

    expect(next.results).toEqual([])
    expect(next.failed).toEqual([{ cardId: "c1", front: "What is 2+2?", grade: "again" }])
    expect(next.inFlight).toBe(0)
  })

  it("a retry of a failed card removes it from failed on settle", () => {
    const failedSession = emptySession({
      failed: [{ cardId: "c1", front: "What is 2+2?", grade: "again" }],
      inFlight: 1,
    })
    const result = reviewResult({ card: card({ id: "c1" }), grade: "again" })

    const next = applyGradeOutcome(failedSession, { kind: "settled", result })

    expect(next.failed).toEqual([])
    expect(next.results).toEqual([result])
  })

  it("a settled outcome for one card leaves an unrelated failed card alone", () => {
    const failedSession = emptySession({
      failed: [{ cardId: "other", front: "Unrelated", grade: "hard" }],
      inFlight: 2,
    })
    const result = reviewResult({ card: card({ id: "c1" }) })

    const next = applyGradeOutcome(failedSession, { kind: "settled", result })

    expect(next.failed).toEqual([{ cardId: "other", front: "Unrelated", grade: "hard" }])
    expect(next.inFlight).toBe(1)
  })
})
