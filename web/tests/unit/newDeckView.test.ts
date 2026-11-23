import { describe, expect, it } from "vitest"
import {
  buildNewDeckRequest,
  clampCount,
  manualDeckRequest,
  newDeckErrorMessage,
  newDeckOptions,
  newDeckOutcome,
  resolveMode,
  selectChip,
  selectKind,
  selectSubject,
  showSubjectChips,
  submitLabel,
  topicChips,
  weaknessChips,
} from "@/portals/student/screens/flashcards/newDeckView"
import type { DeckSummaryDTO, GenerateDeckResponseDTO, WeakTopicDTO } from "@/lib/flashcardTypes"

const weak: WeakTopicDTO[] = [
  { subjectCode: "0580", topic: "E7 Vectors", marksLost: 9, accuracyPct: 41 },
  { subjectCode: "0580", topic: "E2 Algebra", marksLost: 5, accuracyPct: 58 },
  { subjectCode: "0625", topic: "3 Waves", marksLost: 6, accuracyPct: 50 },
]

describe("options and chips", () => {
  it("offers three modes and disables weakness with no recorded weak topics", () => {
    expect(newDeckOptions(weak, "0580").map((o) => [o.mode, o.title, o.sub, o.disabled])).toEqual([
      ["weakness", "From a weakness", "Cards on what cost you marks", false],
      ["topic", "For a topic", "Pick any syllabus topic", false],
      ["manual", "Write my own", "Type your own cards", false],
    ])
    expect(newDeckOptions(weak, "0606")[0]).toMatchObject({ sub: "Needs a marked paper first", disabled: true })
  })

  it("shows one subject's weak topics with accuracy, and plain topic chips", () => {
    expect(weaknessChips(weak, "0580")).toEqual([
      { topic: "E7 Vectors", label: "Vectors", badge: "41%" },
      { topic: "E2 Algebra", label: "Algebra", badge: "58%" },
    ])
    expect(topicChips(["1 Motion", "3 Waves"])).toEqual([
      { topic: "1 Motion", label: "Motion", badge: null },
      { topic: "3 Waves", label: "Waves", badge: null },
    ])
  })

  it("shows subject chips only when there is a choice to make", () => {
    expect([0, 1, 2, 3].map(showSubjectChips)).toEqual([false, false, true, true])
  })
})

describe("count, labels, requests", () => {
  it("clamps the count to 1-50", () => {
    expect([clampCount(0), clampCount(12), clampCount(99)]).toEqual([1, 12, 50])
  })

  it("labels the button for each mode and while pending", () => {
    expect(submitLabel("weakness", 12, false)).toBe("Make 12 cards")
    expect(submitLabel("topic", 1, false)).toBe("Make 1 card")
    expect(submitLabel("manual", 12, false)).toBe("Make deck")
    expect(submitLabel("topic", 12, true)).toBe("Starting…")
  })

  it("builds a generate request for weakness and topic, and needs a topic", () => {
    expect(
      buildNewDeckRequest({ mode: "weakness", subjectCode: "0580", subjectName: "Maths", topic: "E7 Vectors", count: 12, title: "", weakTopics: ["E7 Vectors"] }),
    ).toEqual({
      kind: "generate",
      body: { subjectCode: "0580", origin: "weakness", count: 12, topic: "E7 Vectors", title: null },
    })
    expect(
      buildNewDeckRequest({ mode: "topic", subjectCode: "0580", subjectName: "Maths", topic: null, count: 12, title: "", weakTopics: [] }),
    ).toEqual({ kind: "invalid", reason: "Pick a topic first." })
  })

  it("refuses a weakness topic the student has no record of", () => {
    const base = { mode: "weakness" as const, subjectCode: "0580", subjectName: "Maths", count: 12, title: "" }
    const topics = weaknessChips(weak, "0580").map((c) => c.topic)
    expect(buildNewDeckRequest({ ...base, topic: "E7 Vectors", weakTopics: topics }).kind).toBe("generate")
    expect(buildNewDeckRequest({ ...base, topic: "3 Waves", weakTopics: topics })).toEqual({
      kind: "invalid",
      reason: "Pick one of your weak topics.",
    })
    // A plain topic deck is free to use any syllabus topic.
    expect(
      buildNewDeckRequest({ ...base, mode: "topic", topic: "3 Waves", weakTopics: topics }).kind,
    ).toBe("generate")
  })

  it("refuses a weakness deck when the student has no weak topics", () => {
    expect(
      buildNewDeckRequest({ mode: "weakness", subjectCode: "0580", subjectName: "Maths", topic: "E7 Vectors", count: 12, title: "", weakTopics: [] }),
    ).toEqual({ kind: "invalid", reason: "Pick one of your weak topics." })
  })

  it("keeps a manual deck manual even with a topic (provenance)", () => {
    expect(manualDeckRequest("0580", "Maths", "  ", " E7 Vectors ")).toEqual({
      subjectCode: "0580", title: "Maths deck", description: null, origin: "manual", topic: "E7 Vectors",
    })
    expect(
      buildNewDeckRequest({ mode: "manual", subjectCode: "0580", subjectName: "Maths", topic: null, count: 12, title: "Mine", weakTopics: [] }),
    ).toEqual({ kind: "create", body: manualDeckRequest("0580", "Maths", "Mine", "") })
  })
})

describe("newDeckErrorMessage", () => {
  it("maps each refusal to short, specific copy", () => {
    expect(newDeckErrorMessage({ status: 409, detail: { reason: "no_weaknesses" } })).toBe(
      "No weak topics yet. Mark a paper first.",
    )
    expect(newDeckErrorMessage({ status: 503 })).toBe("Card writing is off right now.")
    expect(newDeckErrorMessage({ status: 422 })).toBe("Pick a topic from the list.")
    expect(newDeckErrorMessage({ status: 500 })).toBe("Couldn't make the deck. Try again.")
    expect(newDeckErrorMessage(null)).toBe("Couldn't make the deck. Try again.")
  })
})

describe("selection", () => {
  const picked = { subject: "0580", chosenMode: "weakness" as const, topic: "E7 Vectors" }

  it("falls back to weakness when one exists, else topic, and keeps the student's own pick", () => {
    expect(resolveMode(null, newDeckOptions(weak, "0580"))).toBe("weakness")
    expect(resolveMode(null, newDeckOptions(weak, "0606"))).toBe("topic")
    expect(resolveMode("manual", newDeckOptions(weak, "0580"))).toBe("manual")
  })

  it("a new subject drops the picked kind and topic, so a weakness pick cannot outlive its subject", () => {
    expect(selectSubject("0606")).toEqual({ subject: "0606", chosenMode: null, topic: null })
    const next = selectSubject("0606")
    expect(resolveMode(next.chosenMode, newDeckOptions(weak, next.subject))).toBe("topic")
  })

  it("a new kind clears the topic, since a topic belongs to one kind", () => {
    expect(selectKind(picked, "topic")).toEqual({ subject: "0580", chosenMode: "topic", topic: null })
  })

  it("picking a chip locks the kind in force, so weaknesses arriving late cannot flip it", () => {
    const open = { subject: "0580", chosenMode: null, topic: null }
    expect(selectChip(open, "topic", "1 Motion")).toEqual({ subject: "0580", chosenMode: "topic", topic: "1 Motion" })
    expect(selectChip(open, "weakness", "E7 Vectors").chosenMode).toBe("weakness")
  })
})

describe("new deck outcome", () => {
  const response = (over: { generationStatus?: DeckSummaryDTO["generationStatus"]; requestedCount?: number; generatedCount?: number }): GenerateDeckResponseDTO => ({
    deck: { id: "d1", generationStatus: over.generationStatus ?? "ready" } as DeckSummaryDTO,
    requestedCount: over.requestedCount ?? 12,
    generatedCount: over.generatedCount ?? 12,
  })

  it("reports the real count when the deck is whole", () => {
    expect(newDeckOutcome(response({}))).toEqual({ variant: "success", title: "12 cards ready" })
  })

  it("names a shortfall instead of the requested count", () => {
    expect(newDeckOutcome(response({ generatedCount: 9 }))).toEqual({ variant: "info", title: "9 of 12 cards written" })
  })

  it("says so when a deck came back with no cards", () => {
    expect(newDeckOutcome(response({ generatedCount: 0 }))).toEqual({ variant: "error", title: "0 of 12 cards written" })
  })

  it("never closes silently on a failed deck", () => {
    expect(newDeckOutcome(response({ generationStatus: "failed", generatedCount: 0 }))).toEqual({
      variant: "error",
      title: "Couldn’t write the cards",
      description: "Nothing was saved.",
    })
  })

  it("leaves a deck that is still writing to its own writing state", () => {
    expect(newDeckOutcome(response({ generationStatus: "writing", generatedCount: 0 }))).toBeNull()
  })
})
