import { describe, expect, it } from "vitest"
import {
  confidenceBandTier,
  groupTopicsBySyllabusGroup,
  practiceAvailabilityView,
  practiceMarkState,
  practiceResultView,
  practiceUnavailableMessage,
} from "@/portals/student/screens/practice/practiceData"
import type { PracticePreview, PracticeResult, PracticeTopicCount } from "@/lib/practiceTypes"

function topicCount(overrides: Partial<PracticeTopicCount> & { topic: string }): PracticeTopicCount {
  return { availableCount: 10, syllabusGroup: overrides.topic, ...overrides }
}

describe("groupTopicsBySyllabusGroup — nesting keeps parent and child distinct rows", () => {
  it("a broad parent group and a narrower child topic under it stay as two distinct rows, not merged", () => {
    const topics = [
      topicCount({ topic: "1 Motion, forces and energy", availableCount: 152, syllabusGroup: "1 Motion, forces and energy" }),
      topicCount({ topic: "1.2 Motion", availableCount: 6, syllabusGroup: "1 Motion, forces and energy" }),
    ]
    const groups = groupTopicsBySyllabusGroup(topics)
    expect(groups).toHaveLength(1)
    expect(groups[0].syllabusGroup).toBe("1 Motion, forces and energy")
    // Both rows survive, individually, with their own real counts — the
    // parent's count is never inflated by or merged with the child's.
    expect(groups[0].topics.map((t) => t.topic)).toEqual(["1 Motion, forces and energy", "1.2 Motion"])
    expect(groups[0].topics.find((t) => t.topic === "1.2 Motion")?.availableCount).toBe(6)
    expect(groups[0].topics.find((t) => t.topic === "1 Motion, forces and energy")?.availableCount).toBe(152)
  })

  it("inverse: two topics in different groups yield two separate groups, never combined into one", () => {
    const topics = [
      topicCount({ topic: "1.2 Motion", syllabusGroup: "1 Motion, forces and energy" }),
      topicCount({ topic: "2.1 Density", syllabusGroup: "2 Thermal physics" }),
    ]
    const groups = groupTopicsBySyllabusGroup(topics)
    expect(groups.map((g) => g.syllabusGroup)).toEqual(["1 Motion, forces and energy", "2 Thermal physics"])
  })

  it("an empty topic list yields no groups, never a placeholder group", () => {
    expect(groupTopicsBySyllabusGroup([])).toEqual([])
  })
})

function preview(overrides: Partial<PracticePreview> = {}): PracticePreview {
  return { available: true, reason: null, requestedCount: 10, availableCount: 10, topics: [], ...overrides }
}

describe("practiceAvailabilityView — the tri-state honesty rule, all three states distinguishable", () => {
  it("available: false yields 'unavailable', a real refusal, never presented as success", () => {
    const view = practiceAvailabilityView(preview({ available: false, reason: "no_questions" }))
    expect(view.kind).toBe("unavailable")
    if (view.kind === "unavailable") expect(view.reason).toBe("no_questions")
  })

  it("available: true with availableCount < requestedCount yields 'shortfall' — still creatable, never padded or silently shortened", () => {
    const view = practiceAvailabilityView(preview({ available: true, reason: "insufficient_pool", availableCount: 6, requestedCount: 10 }))
    expect(view.kind).toBe("shortfall")
    if (view.kind === "shortfall") {
      expect(view.availableCount).toBe(6)
      expect(view.requestedCount).toBe(10)
    }
  })

  it("inverse: available: true with availableCount === requestedCount yields plain 'available', not 'shortfall'", () => {
    const view = practiceAvailabilityView(preview({ available: true, availableCount: 10, requestedCount: 10 }))
    expect(view.kind).toBe("available")
  })

  it("availableCount can exceed requestedCount without ever reading as a shortfall", () => {
    const view = practiceAvailabilityView(preview({ available: true, availableCount: 50, requestedCount: 10 }))
    expect(view.kind).toBe("available")
  })
})

describe("practiceUnavailableMessage — a specific message per reason, never generic", () => {
  it("no_questions and no_weaknesses get distinct, non-generic messages", () => {
    const noQuestions = practiceUnavailableMessage("no_questions")
    const noWeaknesses = practiceUnavailableMessage("no_weaknesses")
    expect(noQuestions.heading).not.toBe(noWeaknesses.heading)
    expect(noQuestions.body).not.toMatch(/something went wrong/i)
    expect(noWeaknesses.body).not.toMatch(/something went wrong/i)
  })

  it("inverse: an unrecognised reason still names the reason rather than hiding it", () => {
    const msg = practiceUnavailableMessage("some_future_reason")
    expect(msg.body).toContain("some_future_reason")
  })

  it("a null reason never crashes and never invents a reason string", () => {
    const msg = practiceUnavailableMessage(null)
    expect(msg.body).not.toContain("null")
  })
})

function practiceResult(overrides: Partial<PracticeResult> = {}): PracticeResult {
  return {
    assignmentId: "a1",
    quizId: "q1",
    subjectCode: "0625",
    marked: false,
    submissionStatus: "not_started",
    awardedMarks: null,
    maximumMarks: null,
    questions: [],
    ...overrides,
  }
}

describe("practiceResultView — not submitted / marking / marked, never a fabricated zero", () => {
  it("submissionStatus not_started (or in_progress) with marked:false yields 'not_submitted'", () => {
    const view = practiceResultView(practiceResult({ submissionStatus: "in_progress" }))
    expect(view.kind).toBe("not_submitted")
    expect("awardedMarks" in view).toBe(false)
  })

  it("submissionStatus submitted with marked:false yields 'marking', still carrying no marks field", () => {
    const view = practiceResultView(practiceResult({ submissionStatus: "submitted" }))
    expect(view.kind).toBe("marking")
    expect("awardedMarks" in view).toBe(false)
  })

  it("inverse: marked:true with real mark fields yields 'marked' carrying the real numbers", () => {
    const view = practiceResultView(
      practiceResult({ marked: true, submissionStatus: "submitted", awardedMarks: 7, maximumMarks: 10 }),
    )
    expect(view.kind).toBe("marked")
    if (view.kind === "marked") {
      expect(view.awardedMarks).toBe(7)
      expect(view.maximumMarks).toBe(10)
    }
  })

  it("a defensive case — marked:true but a null mark field — still falls back to 'marking' rather than inventing a number", () => {
    const view = practiceResultView(
      practiceResult({ marked: true, submissionStatus: "submitted", awardedMarks: null, maximumMarks: null }),
    )
    expect(view.kind).toBe("marking")
  })

  it("an unmarked result never has a zero anywhere in its view", () => {
    const view = practiceResultView(practiceResult())
    expect(JSON.stringify(view)).not.toContain("0")
  })
})

describe("practiceMarkState — correct/partial/wrong, both directions", () => {
  it("awarded === total is correct", () => {
    expect(practiceMarkState(4, 4)).toBe("correct")
  })
  it("awarded <= 0 is wrong", () => {
    expect(practiceMarkState(0, 4)).toBe("wrong")
  })
  it("inverse: a partial award between 0 and total is partial, neither correct nor wrong", () => {
    expect(practiceMarkState(2, 4)).toBe("partial")
  })
})

describe("confidenceBandTier — maps the wire ConfidenceBand onto the shared C-4 ladder", () => {
  it("high -> confident, low -> needs-review", () => {
    expect(confidenceBandTier("high")).toBe("confident")
    expect(confidenceBandTier("low")).toBe("needs-review")
  })
  it("medium -> uncertain", () => {
    expect(confidenceBandTier("medium")).toBe("uncertain")
  })
  it("inverse: an unrecognised band reads as uncertain, never silently as confident", () => {
    expect(confidenceBandTier("some_future_band")).toBe("uncertain")
  })
})
