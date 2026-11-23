import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement, isValidElement, type ReactElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { FirstRun } from "@/portals/teacher/screens/review/QueueStates"
import { SampleAnswer, SampleAnswerBody } from "@/portals/teacher/screens/review/SampleAnswer"
import { AnswerPanel } from "@/portals/teacher/screens/review/AnswerPanel"
import { initialMarkState, primaryActionLabel, totalOf } from "@/portals/teacher/screens/review/markModel"
import { postReviewDecision } from "@/lib/reviewApi"

/*
 * The runner is `environment: "node"` with no DOM (see vitest.config.ts), so a click cannot be
 * dispatched. Instead the component function is called directly, with `useState` backed by a
 * per-mount slot array, and the element tree it returns is inspected: the real `onClick` is read
 * off the real `<button>` and called, then the component is called again to see what the state
 * change did. Outside a `mount()` call `useState` is React's own, so `renderToStaticMarkup` works.
 */
const harness = vi.hoisted(() => ({ active: null as null | { slots: unknown[]; cursor: number; log: string[] } }))

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>()
  return {
    ...actual,
    useState: (init: unknown) => {
      const h = harness.active
      if (!h) return actual.useState(init as never)
      const i = h.cursor++
      if (!(i in h.slots)) h.slots[i] = typeof init === "function" ? (init as () => unknown)() : init
      const set = (next: unknown) => {
        h.slots[i] = typeof next === "function" ? (next as (prev: unknown) => unknown)(h.slots[i]) : next
        h.log.push(`set:${String(h.slots[i])}`)
      }
      return [h.slots[i], set]
    },
  }
})

// A sample is practice. Any call to the review API from it is a bug, so the module is replaced by spies.
vi.mock("@/lib/reviewApi", () => ({ postReviewDecision: vi.fn() }))

function mount<P>(component: (props: P) => ReactNode, props: P) {
  const state = { slots: [] as unknown[], cursor: 0, log: [] as string[] }
  const render = () => {
    state.cursor = 0
    harness.active = state
    try {
      return component(props) as ReactElement
    } finally {
      harness.active = null
    }
  }
  return { render, log: state.log }
}

function findAll(node: ReactNode, match: (el: ReactElement<Record<string, unknown>>) => boolean): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap((child) => findAll(child, match))
  if (!isValidElement(node)) return []
  const el = node as ReactElement<Record<string, unknown>>
  return [...(match(el) ? [el] : []), ...findAll(el.props.children as ReactNode, match)]
}

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")
const SAMPLE = "See a sample answer"

const linkOf = (tree: ReactElement) => {
  const found = findAll(tree, (el) => el.type === "button" && el.props.children === SAMPLE)
  expect(found).toHaveLength(1)
  return found[0]
}
/** Calls the link's real onClick with a stand-in event whose `focus()` is `onFocus`. */
const click = (tree: ReactElement, onFocus: () => void) =>
  (linkOf(tree).props.onClick as (e: { currentTarget: { focus: () => void } }) => void)({ currentTarget: { focus: onFocus } })
const dialogOf = (tree: ReactElement) => {
  const found = findAll(tree, (el) => el.type === SampleAnswer)
  expect(found).toHaveLength(1)
  return found[0]
}

const firstRun = (phone: boolean) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(FirstRun, { phone, markHref: "/papers" })))

describe("review queue: the sample answer link", () => {
  it("is a real button on first run, on phone and desktop, with a 44px target at every pointer", () => {
    for (const phone of [false, true]) {
      const match = firstRun(phone).match(new RegExp(`<button([^>]*)>${SAMPLE}</button>`))
      expect(match, `phone=${phone}`).not.toBeNull()
      const attrs = match?.[1] ?? ""
      expect(attrs).toMatch(/type="button"/)
      expect(attrs).toMatch(/aria-haspopup="dialog"/)
      // min-h-11 on its own, not only pointer-coarse:min-h-11.
      expect(attrs).toMatch(/(?<![:\w-])min-h-11\b/)
    }
  })

  it("keeps the dialog closed until asked, so first run still has one h1 and no extra announcement", () => {
    for (const phone of [false, true]) {
      const html = firstRun(phone)
      expect(html).not.toMatch(/role="dialog"/)
      expect([...html.matchAll(/<h1\b/g)]).toHaveLength(1)
    }
  })

  it("opens the dialog when the link is clicked and closes it again when the dialog asks to close", () => {
    for (const phone of [false, true]) {
      const view = mount(FirstRun, { phone, markHref: "/papers" })
      expect(dialogOf(view.render()).props.open, `phone=${phone} before click`).toBe(false)

      click(view.render(), () => view.log.push("focus"))
      expect(dialogOf(view.render()).props.open, `phone=${phone} after click`).toBe(true)

      ;(dialogOf(view.render()).props.onClose as () => void)()
      expect(dialogOf(view.render()).props.open, `phone=${phone} after close`).toBe(false)
    }
  })

  it("focuses the link itself before opening, so Safari (no click focus) still returns focus to it", () => {
    const view = mount(FirstRun, { phone: false, markHref: "/papers" })
    click(view.render(), () => view.log.push("focus"))
    // The Modal records what holds focus at the moment it opens, so focus has to come first.
    expect(view.log).toEqual(["focus", "set:true"])
  })
})

describe("review queue: the sample answer content", () => {
  it("is a made-up, open, adjustable answer that reads like a real queue item", async () => {
    const { SAMPLE_VIEW } = await import("@/portals/teacher/screens/review/sampleAnswerView")
    expect(SAMPLE_VIEW.title).toMatch(/^Sample student/)
    expect(SAMPLE_VIEW.studentHref).toBeNull()
    expect(SAMPLE_VIEW.status).toBe("open")
    expect(SAMPLE_VIEW.integrity).toBe(false)
    expect(SAMPLE_VIEW.canAdjust).toBe(true)
    expect(SAMPLE_VIEW.hasScan).toBe(false)
    expect(SAMPLE_VIEW.points.map((p) => p.code)).toEqual(["M1", "A1", "B1", "B1"])
    expect(SAMPLE_VIEW.maximumMarks).toBe(4)
    // Low confidence, so the ring is the warn colour the teacher will see on real rows.
    expect(SAMPLE_VIEW.confidenceScore).toBeGreaterThan(0)
    expect(SAMPLE_VIEW.confidenceScore).toBeLessThan(0.7)
  })

  it("starts on Lemely's mark, and ticking the missing unit changes Accept to Save", async () => {
    const { SAMPLE_VIEW: v } = await import("@/portals/teacher/screens/review/sampleAnswerView")
    const start = initialMarkState(v.points, v.lemelyMarks, v.maximumMarks)
    expect(totalOf(v.points, start, v.maximumMarks)).toBe(2)
    expect(primaryActionLabel(2, v.maximumMarks, v.lemelyMarks)).toBe("Accept 2/4")
    expect(primaryActionLabel(3, v.maximumMarks, v.lemelyMarks)).toBe("Save 3/4")
  })

  it("renders the answer panel with its ticks and Accept, and no live region of its own", async () => {
    const { SampleAnswerBody } = await import("@/portals/teacher/screens/review/SampleAnswer")
    const html = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(SampleAnswerBody, { onDone: () => {} })))
    expect(html).toContain("Sample student")
    expect(html).toContain("Accept 2/4")
    expect([...html.matchAll(/data-testid="marker-verdict-row"/g)]).toHaveLength(4)
    expect([...html.matchAll(/aria-pressed="true"/g)]).toHaveLength(2)
    expect(html).not.toMatch(/role="(?:alert|status)"/)
    expect(html).not.toContain("!")
  })

  it("opens in the shared Modal (focus trap, Escape, history) and adds no live region of its own", () => {
    const src = readFileSync(join(DIR, "SampleAnswer.tsx"), "utf8")
    expect(src).toMatch(/from "@\/components\/ui\/modal"/)
    expect(src).toMatch(/<Modal\b/)
    expect(src).not.toMatch(/aria-live|role="(?:alert|status)"/)
  })
})

describe("review queue: the sample answer saves nothing", () => {
  const fetchSpy = vi.fn(() => Promise.reject(new Error("the sample answer must not use the network")))

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchSpy.mockClear()
    vi.mocked(postReviewDecision).mockClear()
  })

  it("opening it, rendering it and doing everything in it never fetches or posts a decision", () => {
    vi.stubGlobal("fetch", fetchSpy)

    // Open it from first run.
    const first = mount(FirstRun, { phone: true, markHref: "/papers" })
    click(first.render(), () => {})
    expect(dialogOf(first.render()).props.open).toBe(true)

    // Render the answer, then use every control the panel hands back.
    const onDone = vi.fn()
    renderToStaticMarkup(createElement(MemoryRouter, null, createElement(SampleAnswerBody, { onDone })))
    const body = mount(SampleAnswerBody, { onDone })
    const panel = findAll(body.render(), (el) => el.type === AnswerPanel)
    expect(panel).toHaveLength(1)
    const marking = panel[0].props.marking as {
      state: unknown
      onChange: (next: unknown) => void
      onNote: (note: string) => void
      onAccept: () => void
      onDismiss: () => void
    }
    marking.onChange(marking.state)
    marking.onNote("a note")
    expect(onDone).not.toHaveBeenCalled()
    marking.onAccept()
    marking.onDismiss()

    // Accept and Dismiss only close the dialog, and do nothing else.
    expect(onDone).toHaveBeenCalledTimes(2)
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(postReviewDecision).not.toHaveBeenCalled()
  })

  it("has the panel's own scan requests switched off, because the sample has no scan", async () => {
    const { SAMPLE_VIEW } = await import("@/portals/teacher/screens/review/sampleAnswerView")
    const body = mount(SampleAnswerBody, { onDone: () => {} })
    const panel = findAll(body.render(), (el) => el.type === AnswerPanel)[0]
    expect(SAMPLE_VIEW.hasScan).toBe(false)
    expect(panel.props.images).toMatchObject({ cropUrl: null, pageUrl: null, pageRequested: false })
  })
})
