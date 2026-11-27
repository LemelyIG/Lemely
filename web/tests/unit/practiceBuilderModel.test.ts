import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { practiceHubKeys } from "@/lib/practiceHubKeys"
import type { PracticePreview, PracticeTopics } from "@/lib/practiceTypes"
import { runCreate, type CreateIo } from "@/portals/student/screens/practice/builder/runCreate"
import {
  COUNT_DEFAULT,
  COUNT_MAX,
  COUNT_MIN,
  applyCreateOutcome,
  beginCreate,
  builderView,
  createOutcome,
  createdToast,
  editSession,
  newSession,
  radioStep,
  seedSession,
  switchSubject,
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
  previewFetching: false,
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
    // A failed check offers its own retry rather than telling the student to fiddle with a filter.
    expect(v.line).toEqual({ tone: "error", text: "Couldn't check what matches.", retry: true })
    expect(builderView(vin()).line?.retry).toBeUndefined()
    expect(v.body).toBe("ready")
  })

  it("a failed background refetch keeps the count the student already has", () => {
    const v = builderView(vin({ previewStatus: "error" }))
    expect(v.line).toEqual({ tone: "ok", text: "32 questions match" })
    expect(v.cta).toEqual({ label: "Start now", disabled: false })
    expect(v.showPrint).toBe(true)
  })

  it("while that refetch retries the line reads Checking, from the fetch status", () => {
    const v = builderView(vin({ previewStatus: "error", previewFetching: true }))
    expect(v.line).toEqual({ tone: "wait", text: "Checking what matches…" })
    expect(v.cta.disabled).toBe(true)
    expect(v.showPrint).toBe(false)
    // A refetch that has not failed is silent: the count stays put, no flicker.
    expect(builderView(vin({ previewFetching: true })).line).toEqual({ tone: "ok", text: "32 questions match" })
  })

  it("a failed check with no count still offers its retry, and Checking while it runs", () => {
    expect(builderView(vin({ previewStatus: "error", preview: undefined })).line?.retry).toBe(true)
    expect(builderView(vin({ previewStatus: "error", preview: undefined, previewFetching: true })).line).toEqual({
      tone: "wait",
      text: "Checking what matches…",
    })
  })

  it("creating: disabled CTA with progress copy", () => {
    expect(builderView(vin({ creating: true })).cta).toEqual({ label: "Making your set…", disabled: true })
  })

  it("topics loading and topics error", () => {
    expect(builderView(vin({ topicsStatus: "pending", topics: undefined })).body).toBe("loading")
    expect(builderView(vin({ topicsStatus: "error", topics: undefined })).body).toBe("topicsError")
  })

  it("names dropped weak topics and the untopiced pool", () => {
    expect(builderView(vin({ dropped: ["Electricity"] })).droppedNote).toBe("Electricity has no questions yet.")
    expect(builderView(vin({ dropped: ["4.1 Electricity", "unknown"] })).droppedNote).toBe(
      "2 weak topics have no questions yet: Electricity, unknown.",
    )
    expect(builderView(vin()).untopicedNote).toBe("Plus 12 general questions, used when no topic is picked.")
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

const MATHS: PracticeTopics = {
  subjectCode: "0580",
  topics: [{ topic: "Vectors", availableCount: 14, syllabusGroup: "Vectors", marksLost: 9 }],
  weakTopics: ["Vectors"],
  untopicedCount: 0,
}

describe("builder session", () => {
  it("seeds once per subject and a later refetch never reverts a choice", () => {
    const seeded = seedSession(newSession("0625"), TOPICS, "0625", null)
    expect(seeded.seededFor).toBe("0625")
    expect(seeded.draft?.subjectCode).toBe("0625")
    const edited = editSession(seeded, { ...seeded.draft!, count: 25 })
    expect(seedSession(edited, TOPICS, "0625", null)).toBe(edited)
  })

  it("waits for topics before seeding", () => {
    const s = newSession("0625")
    expect(seedSession(s, undefined, "0625", null)).toBe(s)
  })

  it("A to B to A seeds A again: a return trip is not a stale blank draft", () => {
    const a = seedSession(newSession("0625"), TOPICS, "0625", null)
    const b = switchSubject(a, "0580")
    expect(b).toMatchObject({ subjectCode: "0580", draft: null, dropped: [], seededFor: null })
    const bSeeded = seedSession(b, MATHS, "0625", null)
    expect(bSeeded.draft?.subjectCode).toBe("0580")
    const back = switchSubject(bSeeded, "0625")
    expect(back.draft).toBeNull()
    const again = seedSession(back, TOPICS, "0625", null)
    expect(again.draft?.subjectCode).toBe("0625")
    expect(again.draft?.selected).toEqual(weakServableTopics(TOPICS))
  })

  it("A to B and back before B's topics arrive still seeds A: the old seed mark must not survive the switch", () => {
    const a = seedSession(newSession("0625"), TOPICS, "0625", null)
    const back = switchSubject(switchSubject(a, "0580"), "0625")
    expect(back.seededFor).toBeNull()
    expect(seedSession(back, TOPICS, "0625", null).draft?.subjectCode).toBe("0625")
  })

  it("a deep-link focus topic only applies to the subject the sheet opened on", () => {
    const opened = seedSession(newSession("0625"), TOPICS, "0625", "3 Waves")
    expect(opened.draft?.selected).toEqual(["3 Waves"])
    const other = seedSession(switchSubject(opened, "0580"), MATHS, "0625", "Vectors")
    expect(other.draft?.weakOnly).toBe(true)
  })

  it("switching subject retires a refusal and a failure banner; the same subject is a no-op", () => {
    const stale = { ...newSession("0625"), race: preview({ available: false }), createFailed: true }
    expect(switchSubject(stale, "0625")).toBe(stale)
    expect(switchSubject(stale, "0580")).toMatchObject({ race: null, createFailed: false })
  })

  it("editing a filter retires a refusal and a failure banner", () => {
    const seeded = seedSession(newSession("0625"), TOPICS, "0625", null)
    const stale = { ...seeded, race: preview({ available: false }), createFailed: true }
    expect(editSession(stale, { ...seeded.draft!, count: 5 })).toMatchObject({ race: null, createFailed: false })
  })
})

describe("create outcome", () => {
  const created = { assignmentId: "a-1", quizId: "q", questionCount: 10, requestedCount: 10, topics: [], reason: null }

  it("success opens the set, refreshes the runs list, and stays quiet when nothing was cut", () => {
    expect(createOutcome({ ok: true, created }, "set", 10)).toEqual({
      kind: "created",
      invalidate: practiceHubKeys.runsAll,
      toast: null,
      to: "/student/practice/set/a-1",
    })
  })

  it("Print instead lands on the print view of the same set", () => {
    const out = createOutcome({ ok: true, created }, "print", 10)
    expect(out).toMatchObject({ kind: "created", to: "/student/practice/print/a-1" })
  })

  it("a short set carries the toast that says why", () => {
    const out = createOutcome({ ok: true, created: { ...created, questionCount: 6 } }, "set", 10)
    expect(out).toMatchObject({ kind: "created", toast: "Made a set of 6. That's all that matched." })
  })

  it("a 409 with a payload is the refusal, not a failure", () => {
    const race = preview({ available: false, reason: "no_questions", availableCount: 0 })
    expect(createOutcome({ ok: false, error: new ApiError(409, "conflict", race) }, "set", 10)).toEqual({ kind: "refused", race })
  })

  it("a 409 without a payload, another status, or a non-API error is the CB4 failure and re-checks the preview", () => {
    const failed = { kind: "failed", refetchPreview: true }
    expect(createOutcome({ ok: false, error: new ApiError(409, "conflict") }, "set", 10)).toEqual(failed)
    expect(createOutcome({ ok: false, error: new ApiError(500, "boom", preview({})) }, "set", 10)).toEqual(failed)
    expect(createOutcome({ ok: false, error: new Error("offline") }, "set", 10)).toEqual(failed)
  })

  it("a refusal reaches the view as the refusal line with a disabled start", () => {
    const race = preview({ available: false, reason: "no_questions", availableCount: 0 })
    const s = applyCreateOutcome(newSession("0625"), { kind: "refused", race })
    const v = builderView(vin({ race: s.race, createFailed: s.createFailed }))
    expect(v.line?.tone).toBe("none")
    expect(v.cta.disabled).toBe(true)
    expect(v.errorBanner).toBeNull()
  })

  it("a failure reaches the view as the banner with Try again, and a new attempt clears it", () => {
    const s = applyCreateOutcome(newSession("0625"), { kind: "failed", refetchPreview: true })
    expect(builderView(vin({ race: s.race, createFailed: s.createFailed })).errorBanner).toBe("Couldn't make this set. Try again.")
    const next = beginCreate(s)
    expect(next).toMatchObject({ race: null, createFailed: false })
    expect(builderView(vin({ race: next.race, createFailed: next.createFailed })).errorBanner).toBeNull()
  })

  it("success leaves the session alone: the sheet is about to navigate away", () => {
    const s = newSession("0625")
    const out = createOutcome({ ok: true, created }, "set", 10)
    expect(applyCreateOutcome(s, out)).toBe(s)
  })
})

describe("radioStep", () => {
  it("moves forward and back with wrap, in reading order", () => {
    expect(radioStep("ArrowRight", 0, 3, false)).toBe(1)
    expect(radioStep("ArrowRight", 2, 3, false)).toBe(0)
    expect(radioStep("ArrowLeft", 0, 3, false)).toBe(2)
    expect(radioStep("ArrowLeft", 2, 3, false)).toBe(1)
  })

  it("Down and Up follow Right and Left; Home and End jump", () => {
    expect(radioStep("ArrowDown", 0, 3, false)).toBe(1)
    expect(radioStep("ArrowUp", 0, 3, false)).toBe(2)
    expect(radioStep("Home", 2, 3, false)).toBe(0)
    expect(radioStep("End", 0, 3, false)).toBe(2)
  })

  it("an RTL row swaps the horizontal arrows only", () => {
    expect(radioStep("ArrowLeft", 0, 3, true)).toBe(1)
    expect(radioStep("ArrowRight", 0, 3, true)).toBe(2)
    expect(radioStep("ArrowDown", 0, 3, true)).toBe(1)
  })

  it("leaves other keys and an empty group alone", () => {
    expect(radioStep("Tab", 0, 3, false)).toBeNull()
    expect(radioStep("Enter", 0, 3, false)).toBeNull()
    expect(radioStep("ArrowRight", 0, 0, false)).toBeNull()
  })
})

describe("runCreate: the steps around the outcome", () => {
  const created = { assignmentId: "a-9", quizId: "q", questionCount: 10, requestedCount: 10, topics: [], reason: null }
  const draft = seedSession(newSession("0625"), TOPICS, "0625", null).draft!

  function harness(mutate: CreateIo["mutate"], start = newSession("0625")) {
    const calls: string[] = []
    let session = start
    const seen: BuilderSessionSnapshot[] = []
    const io: CreateIo = {
      mutate: (f) => {
        calls.push(`mutate:${f.subjectCode}:${f.count}`)
        return mutate(f)
      },
      update: (change) => {
        session = change(session)
        seen.push({ race: session.race, createFailed: session.createFailed })
      },
      invalidate: (key) => calls.push(`invalidate:${key.join("/")}`),
      toast: (title) => calls.push(`toast:${title}`),
      navigate: (to) => calls.push(`navigate:${to}`),
      refetchPreview: () => calls.push("refetch"),
    }
    return { io, calls, seen, session: () => session }
  }
  type BuilderSessionSnapshot = { race: PracticePreview | null; createFailed: boolean }

  it("success: sends the draft's filters, refreshes runs, then navigates to the set", async () => {
    const h = harness(async () => created)
    await runCreate(h.io, draft, "set", 10)
    expect(h.calls).toEqual(["mutate:0625:10", "invalidate:practice/runs", "navigate:/student/practice/set/a-9"])
  })

  it("print: the same steps end on the print view", async () => {
    const h = harness(async () => created)
    await runCreate(h.io, draft, "print", 10)
    expect(h.calls.at(-1)).toBe("navigate:/student/practice/print/a-9")
  })

  it("a short set toasts before it navigates", async () => {
    const h = harness(async () => ({ ...created, questionCount: 4 }))
    await runCreate(h.io, draft, "set", 10)
    expect(h.calls.slice(1)).toEqual([
      "invalidate:practice/runs",
      "toast:Made a set of 4. That's all that matched.",
      "navigate:/student/practice/set/a-9",
    ])
  })

  it("409: the refusal lands in the session, and nothing navigates, refetches or invalidates", async () => {
    const race = preview({ available: false, reason: "no_questions", availableCount: 0 })
    const h = harness(async () => {
      throw new ApiError(409, "conflict", race)
    })
    const out = await runCreate(h.io, draft, "set", 10)
    expect(out.kind).toBe("refused")
    expect(h.calls).toEqual(["mutate:0625:10"])
    expect(h.session()).toMatchObject({ race, createFailed: false })
  })

  it("failure: CB4 lands in the session and the preview is re-checked, with no navigation", async () => {
    const h = harness(async () => {
      throw new Error("offline")
    })
    await runCreate(h.io, draft, "set", 10)
    expect(h.calls).toEqual(["mutate:0625:10", "refetch"])
    expect(h.session()).toMatchObject({ race: null, createFailed: true })
  })

  it("clears the last attempt's refusal or banner before it runs", async () => {
    const stale = { ...newSession("0625"), race: preview({ available: false }), createFailed: true }
    const h = harness(async () => created, stale)
    await runCreate(h.io, draft, "set", 10)
    expect(h.seen[0]).toEqual({ race: null, createFailed: false })
  })
})
