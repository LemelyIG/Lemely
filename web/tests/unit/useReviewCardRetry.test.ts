import { MutationObserver, QueryClient } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { flashcardApi } from "@/lib/flashcardApi"
import { reviewCardMutationOptions } from "@/lib/hooks/useFlashcardApi"

describe("review mutation", () => {
  it("never retries on its own: the banner Retry is the only second attempt, and it reuses the key", async () => {
    const spy = vi.spyOn(flashcardApi, "reviewCard").mockRejectedValue(new Error("boom"))
    const qc = new QueryClient()
    const observer = new MutationObserver(qc, reviewCardMutationOptions(qc))
    await expect(observer.mutate({ cardId: "c1", grade: "good", clientReviewId: "11111111-1111-4111-8111-111111111111" })).rejects.toThrow("boom")
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
