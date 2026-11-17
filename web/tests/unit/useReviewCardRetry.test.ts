import { MutationObserver, QueryClient } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { flashcardApi } from "@/lib/flashcardApi"
import { reviewCardMutationOptions } from "@/lib/hooks/useFlashcardApi"

describe("review mutation", () => {
  it("never retries a failed grade: the endpoint records a new review on every POST", async () => {
    const spy = vi.spyOn(flashcardApi, "reviewCard").mockRejectedValue(new Error("boom"))
    const qc = new QueryClient()
    const observer = new MutationObserver(qc, reviewCardMutationOptions(qc))
    await expect(observer.mutate({ cardId: "c1", grade: "good" })).rejects.toThrow("boom")
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
