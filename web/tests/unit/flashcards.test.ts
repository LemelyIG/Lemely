import { describe, expect, it } from "vitest"
import {
  cardSourceLabel,
  dueStateView,
  flashcardUnavailableMessage,
  generateDeckSummary,
  gradeForKey,
  groupDecksByTopic,
  intervalChangeLabel,
  isRevealKey,
  manualDeckRequest,
  nextDueMessage,
  sessionProgress,
  summarizeSession,
} from "@/portals/student/screens/flashcards/flashcardData"
import type {
  CardDTO,
  DeckSummaryDTO,
  DueSessionDTO,
  GenerateDeckResponseDTO,
  ReviewResultDTO,
} from "@/lib/flashcardTypes"

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

function deck(overrides: Partial<DeckSummaryDTO> & { id: string }): DeckSummaryDTO {
  return {
    subjectCode: "0625",
    topic: null,
    title: "Deck",
    description: null,
    origin: "manual",
    cardCount: 0,
    dueCount: 0,
    createdAt: "2026-08-09T00:00:00Z",
    ...overrides,
  }
}

// ── Honesty rule 3: DueSessionDTO.totalDue is the whole backlog regardless
// of `limit` — "nothing due today" says *when*, never renders a void ──────

describe("dueStateView — totalDue is the whole backlog, never cards.length; 'none' carries nextDueAt", () => {
  it("a non-empty cards list yields 'due', carrying the real totalDue even when limit capped the returned cards", () => {
    const session: DueSessionDTO = {
      cards: [card({ id: "c1" })],
      totalDue: 40, // the backlog is 40; `cards` was capped by `limit` to 1
      nextDueAt: null,
    }
    const view = dueStateView(session)
    expect(view.kind).toBe("due")
    if (view.kind === "due") {
      expect(view.totalDue).toBe(40)
      expect(view.cards).toHaveLength(1)
    }
  })

  it("inverse: an empty cards list yields 'none', carrying nextDueAt rather than a bare void", () => {
    const session: DueSessionDTO = { cards: [], totalDue: 0, nextDueAt: "2026-08-10T08:00:00Z" }
    const view = dueStateView(session)
    expect(view.kind).toBe("none")
    if (view.kind === "none") expect(view.nextDueAt).toBe("2026-08-10T08:00:00Z")
  })
})

describe("nextDueMessage — says *when*, never a generic empty message", () => {
  it("a real nextDueAt formats into a concrete 'due <time>' message", () => {
    const msg = nextDueMessage("2026-08-10T08:00:00Z")
    expect(msg).toMatch(/due/i)
    expect(msg).not.toMatch(/no cards scheduled/i)
  })

  it("inverse: a null nextDueAt (no cards scheduled at all) gets distinct copy, never a formatted 'null' date", () => {
    const msg = nextDueMessage(null)
    expect(msg).not.toContain("null")
    expect(msg).toMatch(/no cards scheduled/i)
  })
})

// ── S-22 grouping ─────────────────────────────────────────────────────────

describe("groupDecksByTopic — groups by topic, first-seen order, untopiced kept distinct", () => {
  it("two decks sharing a topic land in one group", () => {
    const decks = [
      deck({ id: "d1", topic: "1.2 Motion" }),
      deck({ id: "d2", topic: "1.2 Motion" }),
    ]
    const groups = groupDecksByTopic(decks)
    expect(groups).toHaveLength(1)
    expect(groups[0].decks.map((d) => d.id)).toEqual(["d1", "d2"])
  })

  it("inverse: decks with different topics land in separate groups, never merged", () => {
    const decks = [deck({ id: "d1", topic: "1.2 Motion" }), deck({ id: "d2", topic: "2 Thermal" })]
    const groups = groupDecksByTopic(decks)
    expect(groups.map((g) => g.topic)).toEqual(["1.2 Motion", "2 Thermal"])
  })

  it("a deck with no topic groups under null (Untopiced), not silently dropped or merged into another group", () => {
    const decks = [deck({ id: "d1", topic: null }), deck({ id: "d2", topic: "1.2 Motion" })]
    const groups = groupDecksByTopic(decks)
    expect(groups.find((g) => g.topic === null)?.decks.map((d) => d.id)).toEqual(["d1"])
  })
})

// ── Honesty rule 4: origin="weakness" refuses with 409 {"reason":
// "no_weaknesses"} — a specific message, never a generic failure ─────────

describe("flashcardUnavailableMessage — a specific message per reason, never generic, never a fallback to an untargeted deck", () => {
  it("no_weaknesses gets its own specific, non-generic message", () => {
    const msg = flashcardUnavailableMessage("no_weaknesses")
    expect(msg.body).not.toMatch(/something went wrong/i)
    expect(msg.heading.toLowerCase()).toContain("weak")
  })

  it("inverse: an unrecognised reason still names the reason rather than hiding it", () => {
    const msg = flashcardUnavailableMessage("some_future_reason")
    expect(msg.body).toContain("some_future_reason")
  })

  it("a null reason never crashes and never invents a reason string", () => {
    const msg = flashcardUnavailableMessage(null)
    expect(msg.body).not.toContain("null")
  })
})

// ── Honesty rule 2: generatedCount, never requestedCount, is what the
// screen reports; a shortfall is stated plainly, never padded ────────────

function generated(overrides: Partial<GenerateDeckResponseDTO> = {}): GenerateDeckResponseDTO {
  return {
    deck: deck({ id: "d1" }),
    requestedCount: 10,
    generatedCount: 10,
    ...overrides,
  }
}

describe("generateDeckSummary — reports generatedCount, never requestedCount, and states a shortfall plainly", () => {
  it("generatedCount < requestedCount is flagged as a shortfall and the headline shows the real count first", () => {
    const summary = generateDeckSummary(generated({ generatedCount: 6, requestedCount: 10 }))
    expect(summary.shortfall).toBe(true)
    expect(summary.headline).toContain("6 cards generated")
    expect(summary.headline).toContain("10 requested")
  })

  it("inverse: generatedCount === requestedCount is not a shortfall, and the headline never mentions 'requested'", () => {
    const summary = generateDeckSummary(generated({ generatedCount: 10, requestedCount: 10 }))
    expect(summary.shortfall).toBe(false)
    expect(summary.headline).not.toContain("requested")
  })

  it("the headline never reports requestedCount as if it were the generated total", () => {
    const summary = generateDeckSummary(generated({ generatedCount: 3, requestedCount: 20 }))
    expect(summary.headline.startsWith("3 card")).toBe(true)
  })
})

// ── Honesty rule 1: CardDTO.source stays visible for the card's whole
// life — the label must differ per source and never be blank ────────────

describe("cardSourceLabel — distinguishes manual from AI, never blank, never the same label for both", () => {
  it("manual and ai get distinct, non-empty labels", () => {
    const manual = cardSourceLabel("manual")
    const ai = cardSourceLabel("ai")
    expect(manual).not.toBe(ai)
    expect(manual.length).toBeGreaterThan(0)
    expect(ai.length).toBeGreaterThan(0)
  })

  it("inverse: calling it twice with the same source is stable (not randomised or session-dependent)", () => {
    expect(cardSourceLabel("ai")).toBe(cardSourceLabel("ai"))
  })
})

// ── Honesty rule 7: S-23 keyboard operability — reveal and grade both
// have real key affordances ───────────────────────────────────────────────

describe("isRevealKey / gradeForKey — real keyboard affordances for reveal and grading", () => {
  it("Space and Enter both reveal", () => {
    expect(isRevealKey(" ")).toBe(true)
    expect(isRevealKey("Enter")).toBe(true)
  })

  it("inverse: an unrelated key does not reveal", () => {
    expect(isRevealKey("a")).toBe(false)
  })

  it("1-4 map onto again/hard/good/easy in that order", () => {
    expect(gradeForKey("1")).toBe("again")
    expect(gradeForKey("2")).toBe("hard")
    expect(gradeForKey("3")).toBe("good")
    expect(gradeForKey("4")).toBe("easy")
  })

  it("inverse: an unrecognised key yields null, never a guessed grade", () => {
    expect(gradeForKey("5")).toBeNull()
    expect(gradeForKey("a")).toBeNull()
  })
})

// ── Session progress ──────────────────────────────────────────────────────

describe("sessionProgress — current never exceeds total, remaining never negative", () => {
  it("a mid-session position reports the real remaining count", () => {
    expect(sessionProgress(3, 10)).toEqual({ current: 3, total: 10, remaining: 7 })
  })

  it("inverse: current beyond total is clamped, remaining floors at 0 rather than going negative", () => {
    expect(sessionProgress(12, 10)).toEqual({ current: 10, total: 10, remaining: 0 })
  })
})

// ── Honesty rule 5: end-of-session summary is real session facts only —
// cards reviewed, the grade distribution, and the real interval change.
// NO XP ANYWHERE. ─────────────────────────────────────────────────────────

function reviewResult(overrides: Partial<ReviewResultDTO> & { card: CardDTO }): ReviewResultDTO {
  return {
    reviewId: "r1",
    grade: "good",
    intervalBeforeDays: 0,
    intervalAfterDays: 1,
    ...overrides,
  }
}

describe("summarizeSession — real facts only, no XP field anywhere in the shape", () => {
  it("aggregates reviewed count and the grade distribution correctly", () => {
    const results: ReviewResultDTO[] = [
      reviewResult({ card: card({ id: "c1" }), grade: "again", intervalBeforeDays: 3, intervalAfterDays: 0 }),
      reviewResult({ card: card({ id: "c2" }), grade: "good", intervalBeforeDays: 1, intervalAfterDays: 3 }),
      reviewResult({ card: card({ id: "c3" }), grade: "good", intervalBeforeDays: 3, intervalAfterDays: 7 }),
    ]
    const summary = summarizeSession(results)
    expect(summary.reviewed).toBe(3)
    expect(summary.gradeCounts).toEqual({ again: 1, hard: 0, good: 2, easy: 0 })
    expect(summary.intervalChanges).toEqual([
      { cardId: "c1", beforeDays: 3, afterDays: 0 },
      { cardId: "c2", beforeDays: 1, afterDays: 3 },
      { cardId: "c3", beforeDays: 3, afterDays: 7 },
    ])
  })

  it("inverse: no reviews yields a zeroed summary, never crashing on an empty session", () => {
    const summary = summarizeSession([])
    expect(summary.reviewed).toBe(0)
    expect(summary.gradeCounts).toEqual({ again: 0, hard: 0, good: 0, easy: 0 })
    expect(summary.intervalChanges).toEqual([])
  })

  it("the summary shape carries no xp/points/streak key at all — the seam is left, not filled with an invented number", () => {
    const summary = summarizeSession([reviewResult({ card: card({ id: "c1" }) })])
    expect(Object.keys(summary)).toEqual(["reviewed", "gradeCounts", "intervalChanges"])
    expect("xp" in summary).toBe(false)
    expect("points" in summary).toBe(false)
    expect("streak" in summary).toBe(false)
  })
})

describe("intervalChangeLabel — surfaces the scheduler's real before/after effect", () => {
  it("a first review (interval 0 before) reads as 'New', not '0d'", () => {
    const label = intervalChangeLabel({ cardId: "c1", beforeDays: 0, afterDays: 1 })
    expect(label).toBe("New -> 1d")
  })

  it("inverse: a repeat review shows the real numeric before/after, not 'New'", () => {
    const label = intervalChangeLabel({ cardId: "c1", beforeDays: 3, afterDays: 7 })
    expect(label).toBe("3d -> 7d")
  })
})

describe("manualDeckRequest — a hand-made deck's provenance survives having a topic", () => {
  it("a deck the student wrote themselves stays origin 'manual' even when they typed a topic", () => {
    const body = manualDeckRequest("0625", "Physics", "My circuits deck", "4.3 Electric circuits")
    // The topic is carried (the backend accepts one freely on the manual
    // origin) but the provenance is NOT promoted to "topic", which renders
    // as "Topic-generated" and would claim a model wrote this deck.
    expect(body.origin).toBe("manual")
    expect(body.topic).toBe("4.3 Electric circuits")
  })

  it("inverse: with no topic typed it is still 'manual', so the topic is not what decides the origin", () => {
    const body = manualDeckRequest("0625", "Physics", "My deck", "")
    expect(body.origin).toBe("manual")
    // A blank topic is null, never "" — an empty string would read back as a
    // topic the student chose.
    expect(body.topic).toBeNull()
  })

  it("origin is 'manual' for every topic input, never 'topic' or 'weakness'", () => {
    for (const topic of ["", "   ", "1.2 Motion", "anything at all"]) {
      expect(manualDeckRequest("0625", "Physics", "t", topic).origin).toBe("manual")
    }
  })

  it("a blank title falls back to a subject-named default rather than being sent empty", () => {
    expect(manualDeckRequest("0625", "Physics", "   ", "").title).toBe("Physics deck")
    // Inverse: a real title is preserved verbatim (trimmed), not overwritten.
    expect(manualDeckRequest("0625", "Physics", "  Waves  ", "").title).toBe("Waves")
  })
})
