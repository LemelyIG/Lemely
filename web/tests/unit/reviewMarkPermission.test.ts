import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import { ActingTeacherContext, NOT_ACTING, type ActingTeacherValue } from "@/components/acting/acting-state"
import { teamPermissionDeniedMessage } from "@/lib/actingTeacher"
import type { AnswerImages, AnswerMarking, AnswerView } from "@/portals/teacher/screens/review"
import { AnswerPanel, initialMarkState } from "@/portals/teacher/screens/review"

/*
 * An assistant whose role lacks `mark` may open the review queue (`view_results`) but every route that
 * decides an answer answers 403 for them. The redesigned screen must therefore not offer a live control,
 * a bulk approve or the "A" shortcut to that role. The panel is rendered for real; the queue's wiring is
 * a source check because the queue needs a data router and a query client to mount.
 */

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")
const source = (f: string) => readFileSync(join(DIR, f), "utf8")

const point = (id: string, code: string) => ({
  markPointId: id, code, text: `Point ${id}`, tariff: 1, groupKey: null, groupMaxMarks: null,
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
  cropFailed: false, pageFailed: false,
}
const marking = (v: AnswerView): AnswerMarking => ({
  state: initialMarkState(v.points, v.lemelyMarks, v.maximumMarks), onChange: vi.fn(), note: "", onNote: vi.fn(), onAccept: vi.fn(), onDismiss: vi.fn(),
})
const viewer = { ...NOT_ACTING, acting: true, can: (p) => p !== "mark" } as ActingTeacherValue
const withRole = (role: ActingTeacherValue, v: AnswerView) =>
  renderToStaticMarkup(
    createElement(ActingTeacherContext.Provider, { value: role },
      createElement(MemoryRouter, null, createElement(AnswerPanel, { view: v, images, marking: marking(v) }))),
  )

describe("AnswerPanel for a role without mark", () => {
  // Static markup escapes the apostrophe the sentence carries.
  const denied = teamPermissionDeniedMessage(null).replace(/'/g, "&#x27;")

  it("disables the accept action, the mark controls and the note, and says why once", () => {
    const html = withRole(viewer, view())
    expect(html).toContain('data-testid="primary-action" disabled=""')
    expect(html).toContain('<fieldset disabled=""')
    expect(html).toMatch(/<textarea[^>]*\sdisabled=""/)
    expect(html.split(denied).length - 1).toBe(1)
  })

  it("disables the dismiss action on an integrity flag", () => {
    const html = withRole(viewer, view({ integrity: true }))
    expect(html).toContain('data-testid="primary-action" disabled=""')
    expect(html).toMatch(/<textarea[^>]*\sdisabled=""/)
  })

  it("leaves everything live for a role that may mark", () => {
    const html = withRole(NOT_ACTING, view())
    expect(html).not.toContain('data-testid="primary-action" disabled=""')
    expect(html).not.toContain('<fieldset disabled=""')
    expect(html).not.toMatch(/<textarea[^>]*\sdisabled=""/)
    expect(html).not.toContain(denied)
  })
})

describe("review queue wiring for the mark permission", () => {
  const queue = source("ReviewQueue.tsx")

  it("reads the role once", () => {
    expect(queue).toMatch(/const canMark = useCan\("mark"\)/)
  })

  it("refuses to decide, bulk approve or accept by keyboard without it", () => {
    expect(queue).toMatch(/function decideFocused\([^)]*\) \{\n\s+if \(!canMark \|\|/)
    expect(queue).toMatch(/function runBulk\(\) \{\n\s+if \(!canMark\) return/)
    expect(queue).toMatch(/e\.key === "A"\) && canMark && view/)
  })

  it("hides the shortcut hint from a role that cannot use it", () => {
    expect(queue).toMatch(/showShortcuts: canMark/)
  })

  it("gates the select and bulk approve toolbar on the same permission", () => {
    expect(source("QueueColumn.tsx")).toMatch(/<PermissionGate permission="mark">[\s\S]*?onToggleSelect[\s\S]*?onBulk[\s\S]*?<\/PermissionGate>/)
  })
})
