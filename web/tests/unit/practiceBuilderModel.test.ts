import { describe, expect, it } from "vitest"
import type { PracticePreview, PracticeTopics } from "@/lib/practiceTypes"
import {
  COUNT_DEFAULT,
  COUNT_MAX,
  COUNT_MIN,
  builderView,
  createdToast,
  draftToFilters,
  initialDraft,
  setSource,
  setWeakOnly,
  stepCount,
  toggleBand,
  toggleTopic,
  unavailableText,
  visibleTopicGroups,
  weakServableTopics,
  type BuilderViewInput,
} from "@/portals/student/screens/practice/builder/builderModel"

const TOPICS: PracticeTopics = {
  subjectCode: "0625",
  topics: [
    { topic: "1 Motion, forces and energy", availableCount: 152, syllabusGroup: "1 Motion, forces and energy", marksLost: 4 },
    { topic: "1.2 Motion", availableCount: 6, syllabusGroup: "1 Motion, forces and energy", marksLost: 0 },
    { topic: "3 Waves", availableCount: 20, syllabusGroup: "3 Waves", marksLost: 6 },
  ],
  weakTopics: ["3 Waves", "Electricity", "1 Motion, forces and energy"],
  untopicedCount: 12,
}

const preview = (over: Partial<PracticePreview>): PracticePreview => ({
  available: true,
  reason: null,
  requestedCount: 10,
  availableCount: 32,
  topics: [],
  ...over,
})

const vin = (over: Partial<BuilderViewInput> = {}): BuilderViewInput => ({
  topicsStatus: "success",
  topics: TOPICS,
  previewStatus: "success",
  preview: preview({}),
  race: null,
  creating: false,
  createFailed: false,
  subjectName: "Physics",
  otherSubjectNames: ["Maths"],
  dropped: [],
  ...over,
})

describe("count stepper", () => {
  it("steps by 5 and clamps at 5 and 30", () => {
    expect(stepCount(COUNT_DEFAULT, 1)).toBe(15)
    expect(stepCount(COUNT_MIN, -1)).toBe(COUNT_MIN)
    expect(stepCount(COUNT_MAX, 1)).toBe(COUNT_MAX)
  })
})

describe("initialDraft", () => {
  it("prefills only servable weak topics, turns the switch on, and reports the dropped ones", () => {
    const seed = initialDraft("0625", TOPICS, null)
    expect(seed.draft).toEqual({
      subjectCode: "0625",
      count: 10,
      weakOnly: true,
      selected: ["3 Waves", "1 Motion, forces and energy"],
      bands: [],
      source: null,
    })
    expect(seed.dropped).toEqual(["Electricity"])
  })

  it("a focus topic (win-back row or ?topic=) selects only that topic with the switch off", () => {
    const seed = initialDraft("0625", TOPICS, "1.2 Motion")
    expect(seed.draft.selected).toEqual(["1.2 Motion"])
    expect(seed.draft.weakOnly).toBe(false)
  })

  it("ignores a focus topic with no chip, falling back to the weak prefill", () => {
    expect(initialDraft("0625", TOPICS, "Electricity").draft.selected).toEqual(["3 Waves", "1 Motion, forces and energy"])
  })

  it("no weaknesses: switch off, nothing selected", () => {
    const seed = initialDraft("0625", { ...TOPICS, weakTopics: [] }, null)
    expect(seed.draft.weakOnly).toBe(false)
    expect(seed.draft.selected).toEqual([])
  })
})

describe("draft edits", () => {
  const draft = initialDraft("0625", TOPICS, null).draft

  it("toggles topics and bands without mutating", () => {
    const next = toggleTopic(draft, "3 Waves")
    expect(next.selected).toEqual(["1 Motion, forces and energy"])
    expect(draft.selected).toHaveLength(2)
    expect(toggleBand(toggleBand(draft, "challenge"), "challenge").bands).toEqual([])
  })

  it("turning weak-only on keeps only weak selections", () => {
    const mixed = { ...draft, weakOnly: false, selected: ["1.2 Motion", "3 Waves"] }
    expect(setWeakOnly(mixed, true, weakServableTopics(TOPICS)).selected).toEqual(["3 Waves"])
    expect(setWeakOnly(mixed, false, weakServableTopics(TOPICS)).selected).toEqual(["1.2 Motion", "3 Waves"])
  })

  it("source is single-select, null meaning all sources", () => {
    expect(setSource(draft, "past_paper").source).toBe("past_paper")
    expect(setSource(draft, null).source).toBeNull()
  })
})

describe("draftToFilters", () => {
  const draft = initialDraft("0625", TOPICS, null).draft

  it("sends picked chips as topics, never weakTopicsOnly, when something is picked", () => {
    expect(draftToFilters(draft)).toEqual({
      subjectCode: "0625",
      count: 10,
      topics: ["3 Waves", "1 Motion, forces and energy"],
      weakTopicsOnly: false,
      difficultyBands: [],
      source: null,
    })
  })

  it("weak-only with nothing picked asks the server for the weak set", () => {
    const f = draftToFilters({ ...draft, selected: [] })
    expect(f.weakTopicsOnly).toBe(true)
    expect(f.topics).toEqual([])
  })

  it("switch off with nothing picked means no topic filter at all", () => {
    const f = draftToFilters({ ...draft, weakOnly: false, selected: [] })
    expect(f).toMatchObject({ weakTopicsOnly: false, topics: [] })
  })
})

describe("visibleTopicGroups", () => {
  it("off: every servable topic, parent and child kept as distinct rows in one group", () => {
    const groups = visibleTopicGroups(TOPICS, false)
    expect(groups.map((g) => [g.syllabusGroup, g.topics.map((t) => t.topic)])).toEqual([
      ["1 Motion, forces and energy", ["1 Motion, forces and energy", "1.2 Motion"]],
      ["3 Waves", ["3 Waves"]],
    ])
  })

  it("on: only the servable weak topics", () => {
    expect(visibleTopicGroups(TOPICS, true).flatMap((g) => g.topics.map((t) => t.topic))).toEqual([
      "1 Motion, forces and energy",
      "3 Waves",
    ])
  })
})

describe("builderView", () => {
  it("ready and available: tick line, Start now, print link", () => {
    const v = builderView(vin())
    expect(v.body).toBe("ready")
    expect(v.line).toEqual({ tone: "ok", text: "32 questions match" })
    expect(v.cta).toEqual({ label: "Start now", disabled: false })
    expect(v.showPrint).toBe(true)
    expect(v.startCount).toBe(10)
  })

  it("checking (CB1) while the preview is pending", () => {
    const v = builderView(vin({ previewStatus: "pending", preview: undefined }))
    expect(v.line).toEqual({ tone: "wait", text: "Checking what matches…" })
    expect(v.cta.disabled).toBe(true)
    expect(v.showPrint).toBe(false)
  })

  it("too few match (CB2): honest count, still creatable", () => {
    const v = builderView(vin({ preview: preview({ reason: "insufficient_pool", requestedCount: 20, availableCount: 6 }) }))
    expect(v.line).toEqual({ tone: "short", text: "Only 6 questions match. Add a topic or ask for fewer." })
    expect(v.cta).toEqual({ label: "Start with 6", disabled: false })
    expect(v.startCount).toBe(6)
  })

  it("singular copy for one question", () => {
    expect(builderView(vin({ preview: preview({ requestedCount: 5, availableCount: 1 }) })).line?.text).toBe(
      "Only 1 question matches. Add a topic or ask for fewer.",
    )
  })

  it("no questions for the subject (CB3): disabled, no print link, names the other subjects", () => {
    const v = builderView(vin({ topics: { ...TOPICS, topics: [], weakTopics: [], untopicedCount: 0 } }))
    expect(v.body).toBe("noQuestions")
    expect(v.noQuestions).toEqual({ heading: "No Physics questions yet", body: "We're adding them. Try Maths for now." })
    expect(v.cta).toEqual({ label: "Start now", disabled: true })
    expect(v.showPrint).toBe(false)
  })

  it("untopiced-only subject is not 'no questions'", () => {
    expect(builderView(vin({ topics: { ...TOPICS, topics: [], untopicedCount: 4 } })).body).toBe("ready")
  })

  it("couldn't make the set (CB4): banner and Try again, preview line kept", () => {
    const v = builderView(vin({ createFailed: true }))
    expect(v.errorBanner).toBe("Couldn't make this set. Try again.")
    expect(v.cta).toEqual({ label: "Try again", disabled: false })
    expect(v.line?.tone).toBe("ok")
  })

  it("a 409 race replaces the preview with the refusal, never a generic error", () => {
    const v = builderView(vin({ race: preview({ available: false, reason: "no_questions", availableCount: 0 }), createFailed: false }))
    expect(v.line).toEqual({ tone: "none", text: "Nothing matches. Try other topics or another difficulty." })
    expect(v.cta.disabled).toBe(true)
    expect(v.errorBanner).toBeNull()
  })

  it("no weaknesses refusal tells the student how to get out of it", () => {
    const v = builderView(vin({ preview: preview({ available: false, reason: "no_weaknesses", availableCount: 0 }) }))
    expect(v.line).toEqual({ tone: "none", text: "No weak topics yet. Turn this off to pick any topic." })
  })

  it("preview failure is an inline line, not a page error", () => {
    const v = builderView(vin({ previewStatus: "error", preview: undefined }))
    expect(v.line?.tone).toBe("error")
    expect(v.body).toBe("ready")
  })

  it("creating: disabled CTA with progress copy", () => {
    expect(builderView(vin({ creating: true })).cta).toEqual({ label: "Making your set…", disabled: true })
  })

  it("topics loading and topics error", () => {
    expect(builderView(vin({ topicsStatus: "pending", topics: undefined })).body).toBe("loading")
    expect(builderView(vin({ topicsStatus: "error", topics: undefined })).body).toBe("topicsError")
  })

  it("names dropped weak topics and the untopiced pool", () => {
    expect(builderView(vin({ dropped: ["Electricity"] })).droppedNote).toBe("Electricity isn't in the question bank yet.")
    expect(builderView(vin({ dropped: ["4.1 Electricity", "unknown"] })).droppedNote).toBe(
      "2 weak topics aren't in the question bank yet: Electricity, unknown.",
    )
    expect(builderView(vin()).untopicedNote).toBe("Plus 12 untagged questions, used when no topic is picked.")
  })
})

describe("unavailableText / createdToast", () => {
  it("names an unknown reason instead of hiding it", () => {
    expect(unavailableText("pool_locked")).toBe("Not available right now (pool_locked).")
    expect(unavailableText(null)).toBe("Not available right now.")
  })

  it("only toasts when the made set is shorter than expected", () => {
    const created = { assignmentId: "a", quizId: "q", questionCount: 7, requestedCount: 10, topics: [], reason: "insufficient_pool" }
    expect(createdToast(created, 10)).toBe("Made a set of 7. That's all that matched.")
    expect(createdToast(created, 7)).toBeNull()
  })
})
