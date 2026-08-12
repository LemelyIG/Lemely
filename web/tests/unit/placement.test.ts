import { describe, expect, it } from "vitest"
import {
  formatPlacementEstimate,
  placementInviteView,
  placementResultView,
  rankTopics,
  unavailableMessage,
} from "@/portals/student/screens/placement/placementData"
import type {
  PlacementAvailability,
  PlacementResult,
  PlacementTopicBreakdown,
} from "@/lib/placementTypes"

describe("unavailableMessage — a specific message per reason, never generic", () => {
  it("no_questions (0580/0606 today — D4.6 §5) names the real cause: nothing ingested", () => {
    const msg = unavailableMessage("no_questions")
    expect(msg.heading).not.toMatch(/something went wrong/i)
    expect(msg.body.toLowerCase()).toContain("haven't ingested")
  })

  it("every other known reason gets its own distinct message", () => {
    const reasons = [
      "no_eligible_questions",
      "insufficient_topics",
      "insufficient_questions",
      "insufficient_duration",
    ]
    const messages = reasons.map((r) => unavailableMessage(r))
    const headings = new Set(messages.map((m) => m.heading))
    expect(headings.size).toBe(reasons.length)
  })

  it("an unrecognised reason still names the reason rather than hiding it (forward-compat fallback)", () => {
    const msg = unavailableMessage("some_future_reason")
    expect(msg.body).toContain("some_future_reason")
  })

  it("a null reason (shouldn't happen when available=false, but the type allows it) never crashes and never invents a reason string", () => {
    const msg = unavailableMessage(null)
    expect(msg.body).not.toContain("null")
  })
})

describe("formatPlacementEstimate", () => {
  it("pluralises questions and topics correctly", () => {
    expect(formatPlacementEstimate(9, 6, 15.19)).toBe(
      "9 questions across 6 topics — about 15 minutes",
    )
  })

  it("singular question/topic/minute (the inverse of the plural case)", () => {
    expect(formatPlacementEstimate(1, 1, 1)).toBe("1 question across 1 topic — about 1 minute")
  })

  it("rounds estimatedMinutes to a whole minute rather than inventing decimal precision", () => {
    expect(formatPlacementEstimate(10, 6, 17.06)).toBe("10 questions across 6 topics — about 17 minutes")
  })
})

function topic(
  overrides: Partial<PlacementTopicBreakdown> & { topic: string; accuracy: number },
): PlacementTopicBreakdown {
  return { lostMarks: 0, maximumMarks: 10, ...overrides }
}

describe("rankTopics — strongest/weakest, never invented precision", () => {
  it("orders strongest by descending accuracy", () => {
    const topics = [
      topic({ topic: "A", accuracy: 0.5 }),
      topic({ topic: "B", accuracy: 0.9 }),
      topic({ topic: "C", accuracy: 0.2 }),
    ]
    const { strongest } = rankTopics(topics, 2)
    expect(strongest.map((t) => t.topic)).toEqual(["B", "A"])
  })

  it("weakest never repeats a topic already shown as strongest", () => {
    const topics = [
      topic({ topic: "A", accuracy: 0.9 }),
      topic({ topic: "B", accuracy: 0.8 }),
      topic({ topic: "C", accuracy: 0.7 }),
      topic({ topic: "D", accuracy: 0.1 }),
    ]
    const { strongest, weakest } = rankTopics(topics, 3)
    const overlap = strongest.map((t) => t.topic).filter((t) => weakest.map((w) => w.topic).includes(t))
    expect(overlap).toEqual([])
  })

  it("inverse: a small (single-topic) breakdown yields a strongest entry and an empty weakest, not a fabricated duplicate", () => {
    const { strongest, weakest } = rankTopics([topic({ topic: "Only", accuracy: 0.5 })])
    expect(strongest.map((t) => t.topic)).toEqual(["Only"])
    expect(weakest).toEqual([])
  })

  it("an empty breakdown yields empty strongest and weakest, never a placeholder topic", () => {
    const { strongest, weakest } = rankTopics([])
    expect(strongest).toEqual([])
    expect(weakest).toEqual([])
  })
})

function availability(overrides: Partial<PlacementAvailability> = {}): PlacementAvailability {
  return {
    available: true,
    reason: null,
    questionCount: 9,
    topicCount: 6,
    estimatedMinutes: 15,
    ...overrides,
  }
}

describe("placementInviteView — S-03's whole render decision, both directions", () => {
  it("available: false yields the unavailable panel with the real per-reason message", () => {
    const view = placementInviteView(
      availability({ available: false, reason: "no_questions" }),
    )
    expect(view.kind).toBe("unavailable")
    if (view.kind === "unavailable") {
      expect(view.message).toEqual(unavailableMessage("no_questions"))
    }
  })

  it("inverse: available: true yields the invite, never the unavailable panel", () => {
    const view = placementInviteView(availability({ available: true }))
    expect(view.kind).toBe("available")
    if (view.kind === "available") {
      expect(view.estimate).toBe(formatPlacementEstimate(9, 6, 15))
    }
  })
})

function placementResult(overrides: Partial<PlacementResult> = {}): PlacementResult {
  return {
    assignmentId: "a1",
    quizId: "q1",
    subjectCode: "0625",
    marked: true,
    awardedMarks: 7,
    maximumMarks: 10,
    questions: [],
    topicBreakdown: [
      topic({ topic: "A", accuracy: 0.9 }),
      topic({ topic: "B", accuracy: 0.2 }),
    ],
    spansMultipleBands: true,
    ...overrides,
  }
}

describe("placementResultView — marked:false and spansMultipleBands, both directions", () => {
  it("marked: false yields kind 'unmarked', carrying no topic lists at all", () => {
    const view = placementResultView(
      placementResult({ marked: false, awardedMarks: null, maximumMarks: null, topicBreakdown: [] }),
    )
    expect(view).toEqual({ kind: "unmarked" })
    expect("strongest" in view).toBe(false)
    expect("weakest" in view).toBe(false)
  })

  it("inverse: marked: true yields kind 'ranked' with strongest/weakest topics", () => {
    const view = placementResultView(
      placementResult({
        marked: true,
        topicBreakdown: [
          topic({ topic: "A", accuracy: 0.9 }),
          topic({ topic: "B", accuracy: 0.8 }),
          topic({ topic: "C", accuracy: 0.7 }),
          topic({ topic: "D", accuracy: 0.1 }),
        ],
      }),
    )
    expect(view.kind).toBe("ranked")
    if (view.kind === "ranked") {
      expect(view.strongest.map((t) => t.topic)).toEqual(["A", "B", "C"])
      expect(view.weakest.map((t) => t.topic)).toEqual(["D"])
    }
  })

  it("spansMultipleBands: false yields showWorkingLevel: false — no invented working-level precision", () => {
    const view = placementResultView(placementResult({ marked: true, spansMultipleBands: false }))
    expect(view.kind).toBe("ranked")
    if (view.kind === "ranked") expect(view.showWorkingLevel).toBe(false)
  })

  it("inverse: spansMultipleBands: true yields showWorkingLevel: true", () => {
    const view = placementResultView(placementResult({ marked: true, spansMultipleBands: true }))
    expect(view.kind).toBe("ranked")
    if (view.kind === "ranked") expect(view.showWorkingLevel).toBe(true)
  })

  it("an unmarked result with awardedMarks: null never produces a zero anywhere in the view", () => {
    const view = placementResultView(
      placementResult({ marked: false, awardedMarks: null, maximumMarks: null }),
    )
    expect(JSON.stringify(view)).not.toContain("0")
  })
})
