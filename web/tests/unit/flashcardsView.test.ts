// web/tests/unit/flashcardsView.test.ts
import { describe, expect, it } from "vitest"
import {
  comingBackLine,
  decksScreenView,
  deckRowView,
  estimateMinutes,
  masteryView,
  originView,
  subjectDot,
  topicName,
  type DecksScreenInput,
} from "@/portals/student/screens/flashcards/flashcardsView"
import type { DeckSummaryDTO, DueSessionDTO, WeakTopicDTO } from "@/lib/flashcardTypes"

const NOW = new Date("2026-11-16T09:00:00")

function deck(o: Partial<DeckSummaryDTO> & { id: string }): DeckSummaryDTO {
  return {
    subjectCode: "0580",
    topic: null,
    title: o.id,
    description: null,
    origin: "manual",
    cardCount: 10,
    dueCount: 0,
    createdAt: "2026-11-01T00:00:00Z",
    newCount: 4,
    learningCount: 4,
    knownCount: 2,
    marksLost: null,
    generationStatus: "ready",
    requestedCount: null,
    ...o,
  }
}

function due(o: Partial<DueSessionDTO> = {}): DueSessionDTO {
  return { cards: [], totalDue: 0, nextDueAt: null, upcoming: [], againDelayMinutes: 10, ...o }
}

const names: Record<string, string> = { "0580": "Maths", "0625": "Physics", "0606": "Add Maths" }

function input(o: Partial<DecksScreenInput>): DecksScreenInput {
  return {
    decks: [],
    decksStatus: "success",
    due: due(),
    dueStatus: "success",
    weakTopics: [],
    subjectName: (c) => names[c] ?? c,
    subjectOrder: ["0580", "0625", "0606"],
    filterSubject: null,
    now: NOW,
    ...o,
  }
}

describe("small helpers", () => {
  it("strips the syllabus code from a topic label", () => {
    expect(topicName("4.3 Electric circuits")).toBe("Electric circuits")
    expect(topicName("E7 Vectors")).toBe("Vectors")
    expect(topicName("Vectors")).toBe("Vectors")
  })

  it("gives each subject a stable dot colour by enrolment order", () => {
    expect(subjectDot("0580", ["0580", "0625"])).toBe("var(--color-grade-a)")
    expect(subjectDot("0625", ["0580", "0625"])).toBe("var(--color-inverse-primary)")
    expect(subjectDot("9999", ["0580"])).toBe("var(--color-on-surface-variant)")
  })

  it("labels origins the way the mock does", () => {
    expect(originView("weakness")).toEqual({ icon: "target", label: "From a weakness" })
    expect(originView("topic")).toEqual({ icon: "sparkle", label: "For a topic" })
    expect(originView("manual")).toEqual({ icon: "pen", label: "Written by you" })
  })

  it("builds mastery fractions and an aria label, safe on an empty deck", () => {
    expect(masteryView({ newCount: 4, learningCount: 8, knownCount: 6 })).toEqual({
      known: 6,
      learning: 8,
      fresh: 4,
      total: 18,
      knownPct: (6 / 18) * 100,
      learningPct: (8 / 18) * 100,
      label: "6 known, 8 learning, 4 new",
    })
    expect(masteryView({ newCount: 0, learningCount: 0, knownCount: 0 }).knownPct).toBe(0)
  })

  it("estimates about 18 seconds a card, never zero minutes", () => {
    expect(estimateMinutes(26)).toBe(8)
    expect(estimateMinutes(1)).toBe(1)
  })
})

describe("deckRowView", () => {
  it("shows origin, card count and due", () => {
    const row = deckRowView(deck({ id: "Vectors", origin: "weakness", cardCount: 18, dueCount: 9 }))
    expect(row.originLabel).toBe("From a weakness")
    expect(row.meta).toBe("From a weakness · 18 cards")
    expect(row.due).toBe(9)
    expect(row.statusLine).toBeNull()
  })

  it("replaces the meta line while writing or after a failure", () => {
    expect(
      deckRowView(deck({ id: "W", generationStatus: "writing", requestedCount: 12, cardCount: 0 }))
        .statusLine,
    ).toBe("Writing 12 cards…")
    expect(deckRowView(deck({ id: "F", generationStatus: "failed" })).statusLine).toBe(
      "Couldn't write the cards",
    )
  })
})

describe("comingBackLine", () => {
  it("counts tomorrow's cards first", () => {
    expect(
      comingBackLine(["2026-11-17T08:00:00", "2026-11-17T20:00:00", "2026-11-19T08:00:00"], null, NOW),
    ).toBe("2 cards back tomorrow")
  })
  it("falls back to the next due day, then to an add-cards nudge", () => {
    expect(comingBackLine([], "2026-11-20T08:00:00", NOW)).toBe("Next card Friday")
    expect(comingBackLine([], null, NOW)).toBe("Add cards to start")
  })
})

describe("decksScreenView", () => {
  it("is loading, then error, before anything else", () => {
    expect(decksScreenView(input({ decks: undefined, decksStatus: "pending" })).kind).toBe("loading")
    expect(decksScreenView(input({ decks: undefined, decksStatus: "error" })).kind).toBe("error")
  })

  it("is the empty shelf with a weak-topic hint when there are no decks", () => {
    const weak: WeakTopicDTO[] = [
      { subjectCode: "0580", topic: "E7 Vectors", marksLost: 9, accuracyPct: 41 },
    ]
    expect(decksScreenView(input({ weakTopics: weak }))).toEqual({
      kind: "empty",
      mood: "open",
      weakHint: "Vectors cost you 9 marks",
    })
  })

  it("orders decks due first, groups by subject, and fills the hero", () => {
    const view = decksScreenView(
      input({
        decks: [
          deck({ id: "Algebra", dueCount: 4 }),
          deck({ id: "Vectors", dueCount: 9 }),
          deck({ id: "Waves", subjectCode: "0625", dueCount: 14 }),
          deck({ id: "Functions", subjectCode: "0606", dueCount: 0 }),
        ],
        due: due({ totalDue: 27 }),
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    // Physics (14 due) beats Maths (13 due); Add Maths has none.
    expect(view.groups.map((g) => g.subjectName)).toEqual(["Physics", "Maths", "Add Maths"])
    expect(view.groups[1].decks.map((d) => d.title)).toEqual(["Vectors", "Algebra"])
    expect(view.hero).toEqual({
      mood: "happy",
      headline: "27 cards due",
      sub: "About 8 minutes · 3 decks",
      reviewLabel: "Review 27 cards",
    })
    expect(view.header).toEqual({ title: "Flashcards", sub: "4 decks · 40 cards" })
    expect(view.firstDeckId).toBe("Waves")
    expect(view.sparse).toBeNull()
  })

  it("says nothing is due and when cards come back", () => {
    const view = decksScreenView(
      input({
        decks: [deck({ id: "A" }), deck({ id: "B" })],
        due: due({ upcoming: ["2026-11-17T08:00:00"] }),
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    expect(view.hero).toEqual({
      mood: "happy",
      headline: "Nothing due",
      sub: "1 card back tomorrow",
      reviewLabel: null,
    })
  })

  it("keeps the hero honest while the due check is pending or failed", () => {
    const pending = decksScreenView(input({ decks: [deck({ id: "A" })], due: undefined, dueStatus: "pending" }))
    const failed = decksScreenView(input({ decks: [deck({ id: "A" })], due: undefined, dueStatus: "error" }))
    if (pending.kind !== "ready" || failed.kind !== "ready") throw new Error("not ready")
    expect(pending.hero.sub).toBe("Checking what's due…")
    expect(failed.hero.sub).toBe("Couldn't check what's due")
    expect(failed.hero.reviewLabel).toBeNull()
  })

  it("adds the sparse tip and walkthrough for one small deck", () => {
    const view = decksScreenView(
      input({
        decks: [deck({ id: "Vectors", origin: "weakness", topic: "E7 Vectors", cardCount: 6 })],
        weakTopics: [
          { subjectCode: "0580", topic: "E7 Vectors", marksLost: 9, accuracyPct: 41 },
          { subjectCode: "0625", topic: "3 Waves", marksLost: 6, accuracyPct: 50 },
        ],
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    expect(view.sparse).toEqual({
      tip: { title: "One more deck?", body: "Waves cost you 6 marks.", subjectCode: "0625", topic: "3 Waves" },
    })
  })

  it("narrows to one subject when the route filters", () => {
    const view = decksScreenView(
      input({
        decks: [deck({ id: "Vectors" }), deck({ id: "Waves", subjectCode: "0625" })],
        filterSubject: "0625",
      }),
    )
    if (view.kind !== "ready") throw new Error(view.kind)
    expect(view.groups.map((g) => g.subjectCode)).toEqual(["0625"])
    expect(view.header.sub).toBe("Physics · 1 deck · 10 cards")
  })
})

describe("fix round 1", () => {
  it("scopes the hero to the filtered decks", () => {
    const v = decksScreenView(
      input({
        decks: [
          deck({ id: "m", subjectCode: "0580", dueCount: 3 }),
          deck({ id: "p1", subjectCode: "0625", dueCount: 20 }),
          deck({ id: "p2", subjectCode: "0625", dueCount: 4 }),
        ],
        due: due({ totalDue: 27 }),
        filterSubject: "0580",
      }),
    )
    if (v.kind !== "ready") throw new Error("not ready")
    expect(v.hero.headline).toBe("3 cards due")
    expect(v.hero.sub).toContain("1 deck")
    expect(v.hero.reviewLabel).toBe("Review 3 cards")
  })

  it("shows nothing due when the filtered decks have none, despite global due", () => {
    const v = decksScreenView(
      input({
        decks: [deck({ id: "m", subjectCode: "0580" }), deck({ id: "p", subjectCode: "0625", dueCount: 5 })],
        due: due({ totalDue: 5 }),
        filterSubject: "0580",
      }),
    )
    if (v.kind !== "ready") throw new Error("not ready")
    expect(v.hero.headline).toBe("Nothing due")
    expect(v.hero.reviewLabel).toBeNull()
  })

  it("puts ready decks first, due-first, then writing and failed; firstDeckId skips non-ready", () => {
    const v = decksScreenView(
      input({
        decks: [
          deck({ id: "failed", generationStatus: "failed", cardCount: 0 }),
          deck({ id: "writing", generationStatus: "writing", cardCount: 0, requestedCount: 8 }),
          deck({ id: "calm", dueCount: 0 }),
          deck({ id: "busy", dueCount: 6 }),
        ],
        due: due({ totalDue: 6 }),
      }),
    )
    if (v.kind !== "ready") throw new Error("not ready")
    expect(v.groups[0].decks.map((d) => d.id)).toEqual(["busy", "calm", "failed", "writing"])
    expect(v.firstDeckId).toBe("busy")
  })

  it("has no firstDeckId when no deck is ready", () => {
    const v = decksScreenView(
      input({ decks: [deck({ id: "w", generationStatus: "writing", cardCount: 0 })], due: due() }),
    )
    if (v.kind !== "ready") throw new Error("not ready")
    expect(v.firstDeckId).toBeNull()
  })

  it("uses the singular for one mark", () => {
    const weak: WeakTopicDTO[] = [{ subjectCode: "0580", topic: "4.3 Vectors", marksLost: 1 } as WeakTopicDTO]
    const empty = decksScreenView(input({ decks: [], weakTopics: weak }))
    if (empty.kind !== "empty") throw new Error("not empty")
    expect(empty.weakHint).toBe("Vectors cost you 1 mark")
    const sparse = decksScreenView(
      input({ decks: [deck({ id: "a", topic: "Other", cardCount: 3 })], weakTopics: weak }),
    )
    if (sparse.kind !== "ready") throw new Error("not ready")
    expect(sparse.sparse?.tip?.body).toBe("Vectors cost you 1 mark.")
  })

  it("shows no sparse tip while the only deck is still writing", () => {
    const weak: WeakTopicDTO[] = [{ subjectCode: "0580", topic: "Vectors", marksLost: 5 } as WeakTopicDTO]
    const v = decksScreenView(
      input({ decks: [deck({ id: "w", generationStatus: "writing", cardCount: 0 })], weakTopics: weak }),
    )
    if (v.kind !== "ready") throw new Error("not ready")
    expect(v.sparse).toBeNull()
  })

  it("flags failed rows as retryable", () => {
    expect(deckRowView(deck({ id: "f", generationStatus: "failed" })).canRetry).toBe(true)
    expect(deckRowView(deck({ id: "r" })).canRetry).toBe(false)
    expect(deckRowView(deck({ id: "w", generationStatus: "writing" })).canRetry).toBe(false)
  })
})
