import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"
import { flashcardKeys } from "@/lib/flashcardApi"
import type { DeckDetailDTO, DeckSummaryDTO } from "@/lib/flashcardTypes"
import { afterDeleteDeck } from "@/lib/hooks/useFlashcardApi"

const summary = (id: string, subjectCode = "0580"): DeckSummaryDTO => ({
  id, subjectCode, topic: null, title: id, description: null, origin: "manual", cardCount: 0, dueCount: 0,
  createdAt: "2026-11-16T08:00:00Z", newCount: 0, learningCount: 0, knownCount: 0, marksLost: null,
  generationStatus: "ready", requestedCount: null,
})

describe("afterDeleteDeck", () => {
  it("takes the deck out of every cached list before anything is told it is gone", () => {
    const qc = new QueryClient()
    qc.setQueryData(flashcardKeys.decks(null), [summary("d1"), summary("d2")])
    qc.setQueryData(flashcardKeys.decks("0580"), [summary("d1"), summary("d3")])
    qc.setQueryData(flashcardKeys.decks("0625"), [summary("d4", "0625")])
    qc.setQueryData(flashcardKeys.deck("d1"), { id: "d1" } as DeckDetailDTO)

    afterDeleteDeck(qc, "d1")

    expect(qc.getQueryData<DeckSummaryDTO[]>(flashcardKeys.decks(null))?.map((d) => d.id)).toEqual(["d2"])
    expect(qc.getQueryData<DeckSummaryDTO[]>(flashcardKeys.decks("0580"))?.map((d) => d.id)).toEqual(["d3"])
    expect(qc.getQueryData<DeckSummaryDTO[]>(flashcardKeys.decks("0625"))?.map((d) => d.id)).toEqual(["d4"])
    expect(qc.getQueryData(flashcardKeys.deck("d1"))).toBeUndefined()
  })

  it("leaves a list that was never loaded alone", () => {
    const qc = new QueryClient()
    afterDeleteDeck(qc, "d1")
    expect(qc.getQueryData(flashcardKeys.decks(null))).toBeUndefined()
  })
})
