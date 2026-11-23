import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

const state = vi.hoisted(() => ({
  topics: {} as object,
  weak: [] as object[],
  subjects: [{ code: "0580", name: "Mathematics" }] as object[],
  overview: {} as object,
  generated: {} as object,
  toasts: [] as object[],
  sheet: null as unknown,
  setters: [] as { initial: unknown; next: unknown }[],
}))

// Every state setter reports what it was given and the value it was given it for, so a test can
// read what a tap asked the sheet to become. The server render ignores real setters.
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>()
  return {
    ...actual,
    useState: (init: unknown) => {
      const [value] = actual.useState(init)
      return [value, (next: unknown) => { state.setters.push({ initial: value, next }) }]
    },
  }
})
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: (o: object) => state.toasts.push(o) }) }))
vi.mock("@/lib/hooks/useStudentApi", () => ({
  useOverview: () => ({ data: { subjects: state.subjects }, ...state.overview }),
}))
vi.mock("@/lib/hooks/usePracticeApi", () => ({
  usePracticeTopics: () => ({
    status: "success", fetchStatus: "idle", error: null, refetch: () => {}, data: { topics: [{ topic: "algebra" }] }, ...state.topics,
  }),
}))
vi.mock("@/lib/hooks/useFlashcardApi", () => {
  const mutation = () => ({ isPending: false, error: null, reset: () => {}, mutate: () => {}, mutateAsync: async () => state.generated })
  return {
    useWeakTopics: () => ({ data: state.weak }),
    useCreateDeck: mutation, useGenerateDeck: mutation, useDeleteDeck: mutation,
    useRetryGeneration: () => ({ mutate: () => {} }),
    useRetryingDeckIds: () => new Set<string>(),
  }
})
vi.mock("@/portals/student/screens/flashcards/parts/FcSheet", async () => {
  const { createElement: el } = await import("react")
  return {
    FcSheet: ({ open, children }: { open: boolean; children: never }) => {
      state.sheet = children
      return open ? el("div", null, children) : null
    },
  }
})
vi.mock("@/components/redesign", async () => {
  const { createElement: el } = await import("react")
  return { Binny: () => el("span", { "data-binny": true }) }
})

import { NewDeckSheet, type NewDeckSeed } from "@/portals/student/screens/flashcards/NewDeckSheet"
import { WritingState } from "@/portals/student/screens/flashcards/WritingState"

const render = (seed: NewDeckSeed | null, onStarted: (deckId: string) => void = () => {}) =>
  renderToStaticMarkup(createElement(NewDeckSheet, { seed, onClose: () => {}, onStarted }))

type El = { type: unknown; props: Record<string, unknown> }
/** Every element under the rendered sheet that matches, found without a DOM. */
function findAll(node: unknown, match: (el: El) => boolean, found: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => findAll(n, match, found))
  else if (node && typeof node === "object" && "props" in node) {
    const el = node as El
    if (match(el)) found.push(el)
    findAll(el.props.children, match, found)
  }
  return found
}
const button = (label: string) => findAll(state.sheet, (el) => el.type === "button" && el.props.children === label)[0]
const press = (label: string) => (button(label).props.onClick as () => void)()
const seed: NewDeckSeed = { mode: null, subjectCode: "0580", topic: null }

beforeEach(() => {
  state.topics = {}
  state.weak = []
  state.subjects = [{ code: "0580", name: "Mathematics" }]
  state.overview = {}
  state.generated = {}
  state.toasts = []
  state.sheet = null
  state.setters = []
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

  it("shows subject placeholders, not a form, while the subjects load", () => {
    state.subjects = []
    state.overview = { status: "pending", fetchStatus: "fetching", data: undefined }
    state.topics = { status: "pending", fetchStatus: "idle", data: undefined }
    const html = render({ ...seed, subjectCode: "" })
    expect(html).toContain('aria-label="Loading subjects"')
    expect(html).not.toContain('role="radiogroup"')
    expect(html).not.toContain("Pick a subject first")
  })

  it("says what failed, and offers a retry, when the subjects will not load", () => {
    state.subjects = []
    state.overview = { status: "error", data: undefined, error: new Error("boom") }
    const html = render({ ...seed, subjectCode: "" })
    expect(html).toContain("Couldn’t load your subjects")
    expect(html).toContain("Try again")
    expect(html).not.toContain("boom")
    expect(html).not.toContain('role="radiogroup"')
  })

  it("says so when there are no subjects yet", () => {
    state.subjects = []
    state.overview = { status: "success", data: { subjects: [] } }
    const html = render({ ...seed, subjectCode: "" })
    expect(html).toContain("No subjects yet.")
    expect(html).not.toContain('role="radiogroup"')
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

describe("subject chips", () => {
  const two = [{ code: "0580", name: "Mathematics" }, { code: "0625", name: "Physics" }]
  const picked: NewDeckSeed = { mode: "manual", subjectCode: "0580", topic: "algebra" }
  /** What the tap asked the selection to become, given the selection it was made on. */
  const tapped = (label: string) => {
    state.setters = []
    press(label)
    const { initial, next } = state.setters[0]
    return { initial, result: typeof next === "function" ? next(initial) : next }
  }

  it("tapping another subject drops the picked kind and topic", () => {
    state.subjects = two
    render(picked)
    expect(tapped("Physics").result).toEqual({ subject: "0625", chosenMode: null, topic: null })
  })

  it("tapping the subject already selected keeps the kind and topic", () => {
    state.subjects = two
    render(picked)
    const { initial, result } = tapped("Mathematics")
    expect(result).toBe(initial)
    expect(result).toEqual({ subject: "0580", chosenMode: "manual", topic: "algebra" })
  })
})

describe("starting a generated deck", () => {
  const started = { mode: "topic" as const, subjectCode: "0580", topic: "algebra" }
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

  it("says how it went, then opens the deck", async () => {
    state.generated = { deck: { id: "d9", generationStatus: "ready" }, requestedCount: 12, generatedCount: 9 }
    const opened: string[] = []
    render(started, (id) => opened.push(id))
    press("Make 12 cards")
    await settle()
    expect(state.toasts).toEqual([{ variant: "info", title: "9 of 12 cards written" }])
    expect(opened).toEqual(["d9"])
  })

  it("opens a deck that is still writing without a toast", async () => {
    state.generated = { deck: { id: "d9", generationStatus: "writing" }, requestedCount: 12, generatedCount: 0 }
    const opened: string[] = []
    render(started, (id) => opened.push(id))
    press("Make 12 cards")
    await settle()
    expect(state.toasts).toEqual([])
    expect(opened).toEqual(["d9"])
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
