import { MutationObserver, QueryClient } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

const request = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request,
}))

import { flashcardApi } from "@/lib/flashcardApi"
import {
  applyGradeOutcome,
  beginRetry,
  newClientReviewId,
  startSession,
} from "@/lib/flashcardSession"
import { reviewCardMutationOptions } from "@/lib/hooks/useFlashcardApi"

const KEY = "11111111-1111-4111-8111-111111111111"

beforeEach(() => request.mockReset())

describe("review idempotency key", () => {
  it("invalidates open deck details after grading", async () => {
    request.mockResolvedValue({})
    const qc = new QueryClient()
    const invalidate = vi.spyOn(qc, "invalidateQueries")
    await new MutationObserver(qc, reviewCardMutationOptions(qc)).mutate({ cardId: "c1", grade: "good", clientReviewId: KEY })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["flashcards", "deck"] })
  })
  it("sends clientReviewId in the POST body", async () => {
    request.mockResolvedValue({})
    await flashcardApi.reviewCard("c1", "good", KEY)
    const [url, init] = request.mock.calls[0]
    expect(url).toBe("/student/flashcards/cards/c1/review")
    expect(JSON.parse(init.body)).toEqual({
      grade: "good",
      clientReviewId: KEY,
    })
  })

  it("reuses the same key when a failed rating is retried", async () => {
    request
      .mockRejectedValueOnce(new Error("lost response"))
      .mockResolvedValueOnce({})
    const qc = new QueryClient()
    const observer = new MutationObserver(qc, reviewCardMutationOptions(qc))

    // First attempt: the key is minted once, with the rating.
    const clientReviewId = newClientReviewId()
    let session = { ...startSession(), inFlight: 1 }
    await expect(
      observer.mutate({ cardId: "c1", grade: "good", clientReviewId }),
    ).rejects.toThrow()
    session = applyGradeOutcome(session, {
      kind: "failed",
      cardId: "c1",
      front: "Q",
      grade: "good",
      clientReviewId,
    })

    // Retry from the banner: the stored key goes back out unchanged.
    const { retries } = beginRetry(session)
    await observer.mutate({
      cardId: "c1",
      grade: "good",
      clientReviewId: retries[0].clientReviewId,
    })

    const bodies = request.mock.calls.map(([, init]) => JSON.parse(init.body))
    expect(bodies).toEqual([
      { grade: "good", clientReviewId },
      { grade: "good", clientReviewId },
    ])
  })
})
