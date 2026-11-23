import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { PracticePreview, PracticeTopics } from "@/lib/practiceTypes"

// The sheet is a thin shell over builderModel. These tests drive it through the
// data hooks (mocked) and a pass-through Sheet (Radix's portal renders nothing on
// the server), one frame per mock state: PS, CB1, CB2, CB3, plus the load states.
type Status = "pending" | "error" | "success"
const api = vi.hoisted(() => ({
  topicsStatus: "success" as Status,
  topics: undefined as unknown,
  previewStatus: "success" as Status,
  preview: undefined as unknown,
  creating: false,
  retry: () => {},
}))

vi.mock("@/components/ui/sheet", async () => {
  const { createElement: h } = await import("react")
  const part = (tag: string) => (p: { children?: ReactNode; nativeHeader?: ReactNode; className?: string }) =>
    h(tag, { className: p.className }, p.nativeHeader, p.children)
  return { Sheet: (p: { children?: ReactNode }) => p.children, SheetContent: part("section"), SheetTitle: part("h2") }
})
vi.mock("@/lib/hooks/usePracticeApi", () => ({
  usePracticeTopics: () => ({ status: api.topicsStatus, data: api.topics, error: null, refetch: api.retry, fetchStatus: "idle" }),
  usePracticePreview: () => ({ status: api.previewStatus, data: api.preview, refetch: api.retry }),
  useCreatePractice: () => ({ isPending: api.creating, mutateAsync: async () => undefined }),
}))
vi.mock("@/lib/hooks/useReferenceApi", () => ({
  useReference: () => ({ data: { difficultyBands: ["easy", "medium", "hard"] } }),
}))
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: () => {} }) }))

const { SetBuilderSheet } = await import("@/portals/student/screens/practice/builder/SetBuilderSheet")
const { CountStepper } = await import("@/portals/student/screens/practice/builder/CountStepper")
const { TopicChips } = await import("@/portals/student/screens/practice/builder/TopicChips")
const { MoreFilters } = await import("@/portals/student/screens/practice/builder/MoreFilters")
const { SubjectChoice } = await import("@/portals/student/screens/practice/builder/SubjectChoice")
const { AvailabilityLine } = await import("@/portals/student/screens/practice/builder/AvailabilityLine")

const SUBJECTS = [
  { code: "0580", name: "Maths" },
  { code: "0625", name: "Physics" },
  { code: "4037", name: "Add Maths" },
]

const TOPICS: PracticeTopics = {
  subjectCode: "0580",
  topics: [
    { topic: "Vectors", availableCount: 14, syllabusGroup: "Vectors", marksLost: 9 },
    { topic: "2.1 Quadratic inequalities", availableCount: 9, syllabusGroup: "2.1 Quadratic inequalities", marksLost: 6 },
    { topic: "Algebra", availableCount: 20, syllabusGroup: "Algebra", marksLost: 0 },
  ],
  weakTopics: ["Vectors", "2.1 Quadratic inequalities"],
  untopicedCount: 0,
}

const preview = (over: Partial<PracticePreview> = {}): PracticePreview => ({
  available: true,
  reason: null,
  requestedCount: 10,
  availableCount: 32,
  topics: [],
  ...over,
})

function render(initialSubject = "0580", focusTopic: string | null = null) {
  const client = new QueryClient()
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(
        MemoryRouter,
        null,
        createElement(SetBuilderSheet, { subjects: SUBJECTS, initialSubject, focusTopic, onClose: () => {} }),
      ),
    ),
  )
}

const count = (haystack: string, needle: string) => haystack.split(needle).length - 1
const text = (html: string) => html.replace(/<[^>]+>/g, "").replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
/** `disabled:` utility classes contain the word, so look for the attribute itself. */
const isDisabled = (tag: string) => / disabled=""/.test(tag)
/** The opening tag of the button whose own content is `label`, or "" when there is none. */
const button = (html: string, label: string) =>
  html.match(new RegExp(`<button[^>]*>(?=(?:(?!</button>)[\\s\\S])*${label})`))?.[0] ?? ""

beforeEach(() => {
  api.topicsStatus = "success"
  api.topics = TOPICS
  api.previewStatus = "success"
  api.preview = preview()
  api.creating = false
})

describe("SetBuilderSheet (PS): the default sheet", () => {
  it("lays out the anatomy top to bottom", () => {
    const out = render()
    const order = [
      "Practice set",
      'role="radiogroup"',
      "Weak topics only",
      'aria-label="Topics"',
      "Questions",
      "Difficulty and source",
      "32 questions match",
      "Start now",
      "Print instead",
    ].map((needle) => out.indexOf(needle))
    expect(order.every((i) => i >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
  })

  it("titles the sheet once", () => {
    const out = render()
    expect(count(out, "<h2")).toBe(1)
    expect(out).toMatch(/<h2[^>]*>Practice set<\/h2>/)
  })

  it("subject choice is a radiogroup with the opened subject checked", () => {
    const out = render()
    expect(out).toMatch(/role="radiogroup" aria-label="Subject"/)
    expect(count(out, 'role="radio"')).toBeGreaterThanOrEqual(3)
    expect(out).toMatch(/aria-checked="true"[^>]*>(?:<i[^>]*><\/i>)?Maths</)
    expect(out).not.toContain('role="tablist"')
  })

  it("weak-only is on, and only the weak topics show, pressed, with Mono counts", () => {
    const out = render()
    expect(out).toMatch(/role="switch"[^>]*aria-checked="true"/)
    expect(count(out, 'aria-pressed="true"')).toBe(2)
    expect(out).toContain("Vectors")
    expect(out).not.toContain("Algebra")
    expect(out).toMatch(/<b class="font-mono[^"]*">14<\/b>/)
    expect(out).toMatch(/<b class="font-mono[^"]*">9<\/b>/)
  })

  it("weak topics carry the weak tone", () => {
    expect(render()).toContain("bg-error-container")
  })

  it("the count starts at 10, set in Mono", () => {
    expect(render()).toMatch(/aria-live="polite" class="[^"]*font-mono[^"]*">10<\/span>/)
  })

  it("the match line is the one live region, and the CTA is live", () => {
    const out = render()
    expect(out.match(/role="(?:alert|status)"/g)).toEqual(['role="status"'])
    expect(text(out)).toContain("32 questions match")
    expect(isDisabled(button(out, "Start now"))).toBe(false)
  })

  it("a focus topic from the deep link is the only one pressed", () => {
    const out = render("0580", "Algebra")
    expect(count(out, 'aria-pressed="true"')).toBe(1)
    expect(out).toMatch(/role="switch"[^>]*aria-checked="false"/)
    expect(out).toContain("Algebra")
  })

  it("an unenrolled subject from a deep link still gets a chip", () => {
    api.topics = { ...TOPICS, subjectCode: "9999" }
    const out = render("9999")
    expect(out).toMatch(/aria-checked="true"[^>]*>(?:<i[^>]*><\/i>)?9999</)
  })

  it("never says '!' and never adds a Binny", () => {
    const out = render()
    expect(text(out)).not.toContain("!")
    expect(out).not.toContain("rd-say")
  })
})

describe("SetBuilderSheet: the other states", () => {
  it("CB1: checking the match, the start button waits and print is not offered", () => {
    api.previewStatus = "pending"
    api.preview = undefined
    const out = render()
    expect(text(out)).toContain("Checking what matches…")
    expect(isDisabled(button(out, "Start now"))).toBe(true)
    expect(out).not.toContain("Print instead")
    expect(out).toMatch(/role="status"/)
  })

  it("CB2: a shortfall says so in plain words and starts with what exists", () => {
    api.preview = preview({ requestedCount: 20, availableCount: 6, reason: "insufficient_pool" })
    const out = render()
    expect(text(out)).toContain("Only 6 questions match. Add a topic or ask for fewer.")
    expect(isDisabled(button(out, "Start with 6"))).toBe(false)
    expect(out).toContain("Print instead")
  })

  it("CB3: a subject with no questions replaces the filters and disables the start", () => {
    api.topics = { subjectCode: "4037", topics: [], weakTopics: [], untopicedCount: 0 }
    const out = render("4037")
    expect(out).toMatch(/<h3[^>]*>No Add Maths questions yet<\/h3>/)
    expect(text(out)).toContain("We're adding them. Try Maths or Physics for now.")
    expect(out).not.toContain('role="switch"')
    expect(out).not.toContain("Difficulty and source")
    expect(out).not.toContain("Questions</span>")
    expect(isDisabled(button(out, "Start now"))).toBe(true)
    expect(out).not.toContain("Print instead")
    expect(out).toContain('role="radiogroup"')
  })

  it("loading topics: a busy skeleton and no controls that depend on them", () => {
    api.topicsStatus = "pending"
    api.topics = undefined
    const out = render()
    expect(out).toContain('aria-busy="true"')
    expect(out).not.toContain('role="switch"')
    expect(isDisabled(button(out, "Start now"))).toBe(true)
  })

  it("topics failed: one retry, in the sheet, with the subjects still switchable", () => {
    api.topicsStatus = "error"
    api.topics = undefined
    const out = render()
    expect(out).toContain("Couldn’t load topics")
    expect(out).toContain("Try again")
    expect(out).toContain('role="radiogroup"')
    expect(out).not.toContain('role="switch"')
    expect(isDisabled(button(out, "Start now"))).toBe(true)
  })

  it("the check failed: the line says so and nothing can start", () => {
    api.previewStatus = "error"
    api.preview = undefined
    const out = render()
    expect(text(out)).toContain("Couldn't check what matches. Change a filter to try again.")
    expect(isDisabled(button(out, "Start now"))).toBe(true)
  })

  it("making the set: the button says so and is off", () => {
    api.creating = true
    const out = render()
    expect(isDisabled(button(out, "Making your set…"))).toBe(true)
    expect(out).not.toContain("Print instead")
  })
})

describe("builder pieces", () => {
  const html = (node: ReturnType<typeof createElement>) => renderToStaticMarkup(node)

  it("the stepper disables Fewer at 5 and More at 30", () => {
    const low = html(createElement(CountStepper, { value: 5, onChange: () => {} }))
    expect(isDisabled(button(low, "−"))).toBe(true)
    expect(isDisabled(button(low, "\\+"))).toBe(false)
    const high = html(createElement(CountStepper, { value: 30, onChange: () => {} }))
    expect(isDisabled(button(high, "\\+"))).toBe(true)
    expect(isDisabled(button(high, "−"))).toBe(false)
  })

  it("stepper buttons are 44px targets with names", () => {
    const out = html(createElement(CountStepper, { value: 10, onChange: () => {} }))
    expect(out).toContain('aria-label="Fewer"')
    expect(out).toContain('aria-label="More"')
    expect(out).toContain("size-11")
  })

  it("topic chips: a non-weak topic is neutral, a pressed one is primary, headings only for several groups", () => {
    const groups = [
      { syllabusGroup: "Algebra", topics: [{ topic: "Algebra", availableCount: 20, syllabusGroup: "Algebra", marksLost: 0 }] },
    ]
    const one = html(createElement(TopicChips, { groups, selected: ["Algebra"], onToggle: () => {} }))
    expect(one).toContain("bg-primary-container")
    expect(one).not.toContain("<h3")
    const two = html(
      createElement(TopicChips, {
        groups: [...groups, { syllabusGroup: "Vectors", topics: [{ topic: "Vectors", availableCount: 3, syllabusGroup: "Vectors", marksLost: 2 }] }],
        selected: [],
        onToggle: () => {},
      }),
    )
    expect(count(two, "<h3")).toBe(2)
    expect(html(createElement(TopicChips, { groups: [], selected: [], onToggle: () => {} }))).toBe("")
  })

  it("more filters: bands come from reference, source is a radiogroup, none-picked is explained", () => {
    const out = html(
      createElement(MoreFilters, {
        bands: ["hard"],
        availableBands: ["easy", "medium", "hard"],
        source: null,
        onToggleBand: () => {},
        onSource: () => {},
      }),
    )
    expect(out).toContain("Difficulty and source")
    expect(out).toContain("None picked means any difficulty.")
    expect(out).toContain('aria-label="Question source"')
    expect(count(out, 'aria-pressed="true"')).toBe(1)
    expect(out).toMatch(/role="radio" aria-checked="true"[^>]*>All sources</)
    expect(out).not.toContain("<details open")
  })

  it("subject choice: every chip is at least 44px tall", () => {
    const out = html(createElement(SubjectChoice, { subjects: SUBJECTS, value: "0580", onChange: () => {} }))
    expect(count(out, "min-h-11")).toBe(3)
  })

  it("availability line: tick when it matches, spinner while waiting, plain error text", () => {
    const ok = html(createElement(AvailabilityLine, { line: { tone: "ok", text: "32 questions match" } }))
    expect(ok).toContain("<svg")
    const wait = html(createElement(AvailabilityLine, { line: { tone: "wait", text: "Checking what matches…" } }))
    expect(wait).toContain("animate-spin")
    expect(wait).toContain("motion-reduce:animate-none")
    const err = html(createElement(AvailabilityLine, { line: { tone: "error", text: "x" } }))
    expect(err).not.toContain("<svg")
  })
})
