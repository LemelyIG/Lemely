import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { DeckContent } from "@/portals/student/screens/flashcards/parts/DeckContent"
import { deckDetailView } from "@/portals/student/screens/flashcards/deckView"
import type { CardDTO, DeckDetailDTO } from "@/lib/flashcardTypes"

const card = (id: string, source: CardDTO["source"]): CardDTO => ({
  id, front: `Front ${id}`, back: `Back ${id}`, position: 1, source, sourceQuestionId: null, repetitions: 0,
  easeFactor: 2.5, intervalDays: 0, lapses: 0, dueAt: "2026-11-16T08:00:00Z", lastReviewedAt: null,
  nextIntervalDays: { again: 0, hard: 1, good: 1, easy: 1 },
})

const deck = (o: Partial<DeckDetailDTO> = {}): DeckDetailDTO => ({
  id: "d", subjectCode: "0580", topic: "E7 Vectors", title: "Vectors", description: null, origin: "weakness",
  dueCount: 9, newCount: 4, learningCount: 8, knownCount: 6, marksLost: 9, generationStatus: "ready",
  requestedCount: 18, cards: [card("1", "ai"), card("2", "manual")], ...o,
})

function render(d: DeckDetailDTO, extra: Partial<Parameters<typeof DeckContent>[0]> = {}) {
  const noop = vi.fn()
  return renderToStaticMarkup(createElement(DeckContent, {
    view: deckDetailView(d, "Maths", "x"), deck: d, variant: "page", shortfall: null, retrying: false,
    onReview: noop, onAdd: noop, onEdit: noop, onRetry: noop, onDeleteFailed: noop, ...extra,
  }))
}

describe("DeckContent states", () => {
  it("ready: origin, bar, legend, Review, Cards with Add card and an edit control per row", () => {
    const html = render(deck())
    expect(html).toContain("From a weakness · cost you 9 marks")
    expect(html).toContain("Review 9 due")
    expect(html).toContain("Add card")
    expect(html).toContain('aria-label="Edit card: Front 1"')
    expect(html).toContain('aria-label="Edit card: Front 2"')
  })

  it("marks the AI card and not the student's own", () => {
    const html = render(deck())
    expect(html.match(/AI-generated/g)).toHaveLength(1)
  })

  it("nothing due: Review is disabled and says so", () => {
    const html = render(deck({ dueCount: 0 }))
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Nothing due<\/button>/)
  })

  it("an empty deck says so and still offers Add card", () => {
    const html = render(deck({ cards: [], origin: "manual", marksLost: null, dueCount: 0 }))
    expect(html).toContain("No cards in this deck yet")
    expect(html).toContain("Add card")
  })

  it("a short generation keeps its honest line", () => {
    expect(render(deck(), { shortfall: "9 of 12 cards written" })).toContain("9 of 12 cards written")
  })

  it("the short-generation line is plain text: the toast already announced it, so it is not a live region", () => {
    const html = render(deck(), { shortfall: "9 of 12 cards written" })
    expect(html).toContain("9 of 12 cards written")
    expect(html).not.toContain('role="status"')
  })

  it("failed: the reason, Try again and Delete deck, and no card list", () => {
    const html = render(deck({ generationStatus: "failed", cards: [] }))
    expect(html).toContain("Couldn&#x27;t write the cards. Nothing was saved.")
    expect(html).toContain("Try again")
    expect(html).toContain("Delete deck")
    expect(html).not.toContain("Add card")
  })

  it("failed and retrying: the retry is held", () => {
    const html = render(deck({ generationStatus: "failed", cards: [] }), { retrying: true })
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Trying again…<\/button>/)
  })

  it("writing: the status region, no cards", () => {
    const html = render(deck({ generationStatus: "writing", cards: [] }))
    expect(html).toContain('role="status"')
    expect(html).toContain("Writing 18 cards…")
    expect(html).not.toContain("Add card")
  })

  it("never uses an exclamation mark", () => {
    for (const d of [deck(), deck({ generationStatus: "failed" }), deck({ generationStatus: "writing" })]) {
      expect(render(d)).not.toContain("!")
    }
  })
})
