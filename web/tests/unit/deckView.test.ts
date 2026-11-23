import { describe, expect, it } from "vitest"
import {
  cardSourceLabel,
  deckActionConfirm,
  deckDetailView,
  writingProgress,
  writingView,
} from "@/portals/student/screens/flashcards/deckView"
import type { CardDTO, DeckDetailDTO } from "@/lib/flashcardTypes"

const card = (id: string, source: CardDTO["source"]): CardDTO => ({
  id, front: `F${id}`, back: `B${id}`, position: 1, source, sourceQuestionId: null, repetitions: 0,
  easeFactor: 2.5, intervalDays: 0, lapses: 0, dueAt: "2026-11-16T08:00:00Z", lastReviewedAt: null,
  nextIntervalDays: { again: 0, hard: 1, good: 1, easy: 1 },
})

function deck(o: Partial<DeckDetailDTO> = {}): DeckDetailDTO {
  return {
    id: "d", subjectCode: "0580", topic: "E7 Vectors", title: "Vectors", description: null,
    origin: "weakness", dueCount: 9, newCount: 4, learningCount: 8, knownCount: 6, marksLost: 9,
    generationStatus: "ready", requestedCount: 18, cards: [card("1", "ai"), card("2", "manual")], ...o,
  }
}

describe("deckDetailView", () => {
  it("builds the header, origin line, legend, review button and card rows", () => {
    const v = deckDetailView(deck(), "Maths", "var(--color-grade-a)")
    expect(v.title).toBe("Vectors")
    expect(v.sub).toBe("Maths · 2 cards")
    expect(v.originLine).toBe("From a weakness · cost you 9 marks")
    expect(v.legend).toEqual([
      { key: "known", count: 6, label: "known" },
      { key: "learning", count: 8, label: "learning" },
      { key: "new", count: 4, label: "new" },
    ])
    expect(v.review).toEqual({ label: "Review 9 due", enabled: true })
    expect(v.cards.map((c) => [c.id, c.ai])).toEqual([["1", true], ["2", false]])
    expect(v.emptyCards).toBe(false)
    expect(v.state).toBe("ready")
  })

  it("disables review when nothing is due and flags an empty deck", () => {
    const v = deckDetailView(deck({ dueCount: 0, cards: [], origin: "manual", marksLost: null }), "Maths", "x")
    expect(v.review).toEqual({ label: "Nothing due", enabled: false })
    expect(v.originLine).toBe("Written by you")
    expect(v.emptyCards).toBe(true)
  })

  it("passes writing and failed through as states", () => {
    expect(deckDetailView(deck({ generationStatus: "writing" }), "Maths", "x").state).toBe("writing")
    expect(deckDetailView(deck({ generationStatus: "failed" }), "Maths", "x").state).toBe("failed")
  })

  it("says 1 mark, not 1 marks", () => {
    expect(deckDetailView(deck({ marksLost: 1 }), "Maths", "x").originLine).toBe("From a weakness · cost you 1 mark")
  })
})

describe("writing", () => {
  it("names the count and the topic, and why for a weakness deck", () => {
    expect(writingView({ topic: "E7 Vectors", origin: "weakness", requestedCount: 12 })).toEqual({
      title: "Writing 12 cards…",
      body: "On Vectors, from the questions that cost you marks.",
      hint: "You can leave. The deck shows up when it's ready.",
    })
    expect(writingView({ topic: "1 Motion", origin: "topic", requestedCount: 1 }).body).toBe("On Motion.")
  })

  it("does not invent a count when the server sent none", () => {
    expect(writingView({ topic: null, origin: "topic", requestedCount: null }).title).toBe("Writing your cards…")
  })

  it("eases toward 90% and never claims done", () => {
    expect(writingProgress(0, 12)).toBe(0)
    expect(writingProgress(1_000_000, 12)).toBe(0.9)
    const mid = writingProgress(7_500, 12)
    expect(mid).toBeGreaterThan(0.3)
    expect(mid).toBeLessThan(0.9)
  })
})

it("keeps the two source labels distinct", () => {
  expect(cardSourceLabel("ai")).toBe("AI-generated")
  expect(cardSourceLabel("manual")).toBe("Your card")
})

describe("deckActionConfirm", () => {
  it("asks before renaming and before deleting, with no exclamation marks", () => {
    const rename = deckActionConfirm("rename", { title: "Vectors", next: "  Vector drills " })
    expect(rename).toEqual({
      title: "Rename this deck?",
      body: "“Vectors” will be called “Vector drills”.",
      confirm: "Rename",
      destructive: false,
    })
    const del = deckActionConfirm("delete", { title: "Vectors", cardCount: 2 })
    expect(del).toEqual({
      title: "Delete this deck?",
      body: "“Vectors” and its 2 cards will be deleted. This can't be undone.",
      confirm: "Delete deck",
      destructive: true,
    })
    expect(deckActionConfirm("delete", { title: "V", cardCount: 1 }).body).toContain("its 1 card will")
    expect(JSON.stringify([rename, del])).not.toContain("!")
  })
})
