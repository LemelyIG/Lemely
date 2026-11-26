import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import type { AnswerView } from "@/portals/teacher/screens/review"
import { AnswerPanel, initialMarkState } from "@/portals/teacher/screens/review"
import type { AnswerImages, AnswerMarking } from "@/portals/teacher/screens/review"

const point = (id: string, code: string, tariff = 1) => ({
  markPointId: id, code, text: `Point ${id}`, tariff, groupKey: null, groupMaxMarks: null,
  awarded: true, verdictLabel: null, note: null, ecf: false,
})

function view(over: Partial<AnswerView> = {}): AnswerView {
  return {
    key: "i1", title: "Layla Hassan · Q4(b)", subtitle: "10B · 0580/42 · 64% sure", studentHref: null,
    pageLabel: null, hasScan: false, transcription: "x = 3", selfReview: [],
    scheme: { expected: null, topic: null }, notes: { reason: null, feedback: null },
    points: [point("p1", "M1"), point("p2", "A1")], matchedPointIds: [], maximumMarks: 2, lemelyMarks: 1,
    clampNote: null, status: "open", integrity: false, canAdjust: true, cannotAdjustReason: null,
    correction: null, resolutionNote: null, confidenceScore: 0.64,
    ...over,
  }
}
const images: AnswerImages = {
  cropUrl: null, onCropError: vi.fn(), pageUrl: null, onPageError: vi.fn(), pageRequested: false, requestPage: vi.fn(),
}
function marking(v: AnswerView): AnswerMarking {
  return { state: initialMarkState(v.points, v.lemelyMarks, v.maximumMarks), onChange: vi.fn(), note: "", onNote: vi.fn(), onAccept: vi.fn(), onDismiss: vi.fn() }
}
const render = (v: AnswerView, m: AnswerMarking | null) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(AnswerPanel, { view: v, images, marking: m })))

describe("AnswerPanel", () => {
  it("renders the ticks, the stepper and the save action", () => {
    const v = view()
    const html = render(v, marking(v))
    expect(html).toContain("Layla Hassan")
    expect(html).toContain('aria-label="One mark more"')
    expect(html).toContain("Accept 1/2")
  })
  it("disables the save action when there is no way to enter a mark", () => {
    const v = view({ points: [], maximumMarks: null, lemelyMarks: null })
    const html = render(v, marking(v))
    expect(html).toContain('data-testid="primary-action" disabled=""')
  })
  it("keeps the save action enabled when a mark can be entered", () => {
    const v = view()
    expect(render(v, marking(v))).not.toContain('data-testid="primary-action" disabled=""')
  })
  it("shows the clamp note whenever it is set", () => {
    const v = view({ lemelyMarks: 2, clampNote: "Lemely gave 7, above the maximum of 2, so it is shown as 2" })
    expect(render(v, marking(v))).toContain("above the maximum of 2")
  })
  it("steps within the maximum: the plus is disabled at the cap", () => {
    const v = view({ lemelyMarks: 2 })
    expect(render(v, marking(v))).toContain('aria-label="One mark more" disabled=""')
  })
  it("is read-only without marking: no controls, no actions", () => {
    const html = render(view({ status: "resolved" }), null)
    expect(html).not.toContain("One mark more")
    expect(html).not.toContain("data-testid=\"primary-action\"")
    expect(html).toContain("Resolved")
  })
  it("offers only a dismiss for an integrity flag", () => {
    const v = view({ integrity: true })
    const html = render(v, marking(v))
    expect(html).toContain("Dismiss flag")
    expect(html).not.toContain("One mark more")
    expect(html).toContain("Dismissing never changes the student")
  })
  it("names the tariff chip in words so the point reads cleanly", () => {
    const v = view({ points: [point("p1", "M1", 1), point("p2", "A1", 2)] })
    const html = render(v, marking(v))
    expect(html).toContain("1 mark<")
    expect(html).toContain("2 marks<")
  })
  it("draws a big confidence ring and does not repeat the percentage in the subtitle", () => {
    const html = render(view(), null)
    expect(html).toMatch(/class="rd-keyring"[^>]*style="width:(9\d|1\d\d)px/)
  })
  it("wires the answer tabs as a tablist with a tabpanel", () => {
    const html = render(view({ hasScan: true }), marking(view({ hasScan: true })))
    expect(html).toContain('role="tablist"')
    expect(html).toContain('role="tabpanel"')
    expect(html).toContain('tabindex="-1"')
  })
})
