import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

const state = vi.hoisted(() => ({
  topics: {} as object,
  weak: [] as object[],
  subjects: [{ code: "0580", name: "Mathematics" }] as object[],
}))

vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: () => {} }) }))
vi.mock("@/lib/hooks/useStudentApi", () => ({ useOverview: () => ({ data: { subjects: state.subjects } }) }))
vi.mock("@/lib/hooks/usePracticeApi", () => ({
  usePracticeTopics: () => ({
    status: "success", fetchStatus: "idle", error: null, refetch: () => {}, data: { topics: [{ topic: "algebra" }] }, ...state.topics,
  }),
}))
vi.mock("@/lib/hooks/useFlashcardApi", () => {
  const mutation = () => ({ isPending: false, error: null, reset: () => {}, mutate: () => {}, mutateAsync: async () => ({}) })
  return {
    useWeakTopics: () => ({ data: state.weak }),
    useCreateDeck: mutation, useGenerateDeck: mutation, useDeleteDeck: mutation,
    useRetryGeneration: () => ({ mutate: () => {} }),
    useRetryingDeckIds: () => new Set<string>(),
  }
})
vi.mock("@/portals/student/screens/flashcards/parts/FcSheet", async () => {
  const { createElement: el } = await import("react")
  return { FcSheet: ({ open, children }: { open: boolean; children: never }) => open ? el("div", null, children) : null }
})
vi.mock("@/components/redesign", async () => {
  const { createElement: el } = await import("react")
  return { Binny: () => el("span", { "data-binny": true }) }
})

import { NewDeckSheet, type NewDeckSeed } from "@/portals/student/screens/flashcards/NewDeckSheet"
import { WritingState } from "@/portals/student/screens/flashcards/WritingState"

const render = (seed: NewDeckSeed | null) =>
  renderToStaticMarkup(createElement(NewDeckSheet, { seed, onClose: () => {}, onStarted: () => {} }))
const seed: NewDeckSeed = { mode: null, subjectCode: "0580", topic: null }

beforeEach(() => {
  state.topics = {}
  state.weak = []
  state.subjects = [{ code: "0580", name: "Mathematics" }]
})

describe("new deck sheet", () => {
  it("renders nothing while closed", () => {
    expect(render(null)).toBe("")
  })

  it("offers topic mode when there are no weaknesses and hides the subject chooser for one subject", () => {
    const html = render(seed)
    expect(html).toContain("Needs a marked paper first")
    expect(html).toContain('aria-checked="true"')
    expect(html).toContain("<span>algebra</span>")
    expect(html).not.toContain('aria-label="Subject"')
  })

  it("shows the subject chooser for two subjects", () => {
    state.subjects = [{ code: "0580", name: "Mathematics" }, { code: "0625", name: "Physics" }]
    expect(render(seed)).toContain('aria-label="Subject"')
  })

  it("defaults to weakness mode, with the weak topic and its accuracy, when a weakness exists", () => {
    state.weak = [{ subjectCode: "0580", topic: "algebra", marksLost: 9, accuracyPct: 42 }]
    const html = render(seed)
    expect(html).toContain("Cards on what cost you marks")
    expect(html).toContain("42%")
    expect(html).not.toContain("Needs a marked paper first")
  })

  it("shows chip-shaped placeholders while topics load", () => {
    state.topics = { status: "pending", fetchStatus: "fetching", data: undefined }
    const html = render(seed)
    expect(html).toContain('aria-label="Loading topics"')
    expect(html).not.toContain('aria-label="Topic"')
  })

  it("says what failed and offers a retry when topics will not load", () => {
    state.topics = { status: "error", data: undefined, error: new Error("boom") }
    const html = render(seed)
    expect(html).toContain("Couldn’t load topics")
    expect(html).toContain("Try again")
    expect(html).not.toContain("boom")
  })

  it("says there are no topics when the subject has none", () => {
    state.topics = { data: { topics: [] } }
    expect(render(seed)).toContain("No topics for this subject yet.")
  })

  it("writes your own with a title field and no stepper", () => {
    const html = render({ ...seed, mode: "manual" })
    expect(html).toContain("Mathematics deck")
    expect(html).toContain("Make deck")
    expect(html).not.toContain(">Cards<")
  })

  it("reopens a failed deck with the failure text and Try again instead of the form", () => {
    const html = render({ ...seed, failedDeckId: "d1" })
    expect(html).toContain("Nothing was saved")
    expect(html).toContain('role="alert"')
    expect(html).toContain("Try again")
    expect(html).not.toContain('role="radiogroup"')
  })
})

describe("writing state", () => {
  const deck = { topic: "algebra", origin: "topic" as const, requestedCount: 12 }

  it("shows the writing count and leaves Binny out of the panel", () => {
    const page = renderToStaticMarkup(createElement(WritingState, { deck, variant: "page" }))
    const panel = renderToStaticMarkup(createElement(WritingState, { deck, variant: "panel" }))
    expect(page).toContain("Writing 12 cards")
    expect(page).toContain("data-binny")
    expect(panel).not.toContain("data-binny")
  })

  it("is a status region that names the topic and says the student can leave", () => {
    const html = renderToStaticMarkup(createElement(WritingState, { deck, variant: "page" }))
    expect(html).toContain('role="status"')
    expect(html).toContain("On algebra.")
    expect(html).toContain("You can leave.")
  })

  it("writes no number when the server gave no count", () => {
    const html = renderToStaticMarkup(createElement(WritingState, { deck: { ...deck, requestedCount: null }, variant: "page" }))
    expect(html).toContain("Writing your cards")
  })
})
