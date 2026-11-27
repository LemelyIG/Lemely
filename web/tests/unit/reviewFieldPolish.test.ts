import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import { EMPTY_FILTERS } from "@/lib/reviewQueueQuery"
import type { AnswerView } from "@/portals/teacher/screens/review"
import { AnswerPanel, initialMarkState } from "@/portals/teacher/screens/review"
import type { AnswerImages, AnswerMarking } from "@/portals/teacher/screens/review"
import { FilterBar } from "@/portals/teacher/screens/review/FilterBar"

/*
 * The review queue's two kit fields (the search pill and the answer note box) sit on `Input` and
 * `Textarea`. The kit's `.text-field` rule is unlayered, so it beats every layered Tailwind utility
 * that sets the same property: the note box silently rendered 600 weight instead of the approved
 * mock's `400 / 1.45`. A `!` utility would fix it but puts a `!` in the rendered class list, which
 * the copy gate (reviewQueueSample) reads as an exclamation mark, so review.css carries a plain
 * `textarea.rq-note` rule instead. These tests pin that rule, the class that hooks it, and the field
 * names. The computed-style proof (that the rule really wins in a browser) is a browser check,
 * recorded in the lane report; a node-environment runner cannot cascade.
 */

const point = (id: string, code: string) => ({
  markPointId: id, code, text: `Point ${id}`, tariff: 1, groupKey: null, groupMaxMarks: null,
  awarded: true, verdictLabel: null, note: null, ecf: false,
})
function view(over: Partial<AnswerView> = {}): AnswerView {
  return {
    key: "i1", title: "Sample Student · Q4(b)", subtitle: "10B · 0580/42 · 64% sure", studentHref: null,
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
  cropFailed: false, pageFailed: false,
}
function marking(v: AnswerView): AnswerMarking {
  return { state: initialMarkState(v.points, v.lemelyMarks, v.maximumMarks), onChange: vi.fn(), note: "", onNote: vi.fn(), onAccept: vi.fn(), onDismiss: vi.fn() }
}
const panel = (v: AnswerView) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(AnswerPanel, { view: v, images, marking: marking(v) })))

const tag = (html: string, name: string) => {
  const m = html.match(new RegExp(`<${name}\\b[^>]*>`))
  if (!m) throw new Error(`no <${name}> in markup`)
  return m[0]
}
const attr = (open: string, name: string) => open.match(new RegExp(`\\s${name}="([^"]*)"`))?.[1] ?? ""
const labelFor = (html: string, id: string) =>
  html.match(new RegExp(`<label[^>]*\\sfor="${id.replace(/[$()*+.?[\\\]^{|}]/g, "\\$&")}"[^>]*>([^<]*)</label>`))?.[1]

describe("answer note box type", () => {
  it("restores the mock's weight 400 and 1.45 line height over the unlayered kit rule", () => {
    const cls = attr(tag(panel(view()), "textarea"), "class")
    expect(cls).toContain("rq-note")
    const css = readFileSync(join(import.meta.dirname, "../../src/portals/teacher/screens/review/review.css"), "utf8")
    const body = css.match(/(?:^|\n)textarea\.rq-note\s*\{([^}]*)\}/)?.[1] ?? ""
    expect(body).toMatch(/font-weight:\s*400\b/)
    expect(body).toMatch(/line-height:\s*1\.45\b/)
  })
  it("keeps a `!` out of the rendered panel: the copy gate reads one in a class list as punctuation", () => {
    expect(panel(view())).not.toContain("!")
  })
  it("keeps the 16px field floor: no size override on the note box", () => {
    const cls = attr(tag(panel(view()), "textarea"), "class")
    expect(cls).toContain("text-field")
    expect(cls).not.toMatch(/(^|\s)!?text-(xs|sm|base|dense|\[)/)
  })
  it("keeps its accessible name, on both the marking and the integrity-flag note", () => {
    for (const [v, name] of [
      [view(), "Add a note for the student (optional)"],
      [view({ integrity: true }), "Note for your records"],
    ] as const) {
      const html = panel(v)
      const area = tag(html, "textarea")
      const text = labelFor(html, attr(area, "id"))
      expect(text, name).toBeTruthy()
      if (v.integrity) expect(text).toBe(name)
    }
  })
})

describe("search field", () => {
  const props = {
    filters: EMPTY_FILTERS,
    options: { classes: [], subjects: [], subjectName: (c: string) => c },
    shownLine: null,
    onSearch: vi.fn(),
    onSort: vi.fn(),
    onToggle: vi.fn(),
    onRemove: vi.fn(),
    searchRef: { current: null },
  }
  const bar = () => renderToStaticMarkup(createElement(FilterBar, props))

  it("keeps its accessible name", () => {
    const html = bar()
    const input = tag(html, "input")
    expect(labelFor(html, attr(input, "id"))).toBe("Search students, papers or questions")
    expect(attr(input, "type")).toBe("search")
  })
  it("drops the trailing padding on coarse pointers, where the slash hint is hidden", () => {
    const html = bar()
    const cls = attr(tag(html, "input"), "class")
    expect(html).toMatch(/pointer-coarse:hidden[^>]*>\/</)
    expect(cls).toContain("pe-9")
    expect(cls).toContain("pointer-coarse:pe-3")
  })
  it("carries no redundant weight class: the kit field already sets 600", () => {
    expect(attr(tag(bar(), "input"), "class")).not.toContain("font-semibold")
  })
})
