import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { FirstRun } from "@/portals/teacher/screens/review/QueueStates"
import { initialMarkState, primaryActionLabel, totalOf } from "@/portals/teacher/screens/review/markModel"

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")
const SAMPLE = "See a sample answer"

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

  it("focuses the link itself before opening, so Safari (no click focus) still returns focus to it", () => {
    const src = readFileSync(join(DIR, "QueueStates.tsx"), "utf8")
    expect(src).toMatch(/currentTarget\.focus\(\)/)
    expect(src).toMatch(/<SampleAnswer\b/)
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

  it("opens in the shared Modal (focus trap, Escape, history) and needs no backend", () => {
    const src = readFileSync(join(DIR, "SampleAnswer.tsx"), "utf8")
    expect(src).toMatch(/from "@\/components\/ui\/modal"/)
    expect(src).toMatch(/<Modal\b/)
    expect(src).not.toMatch(/useTeacherApi|fetch\(|apiClient|useQuery|useMutation/)
    // Nothing the teacher does in the sample is saved: Accept and Dismiss only close it.
    expect(src).toMatch(/onAccept: onDone/)
    expect(src).not.toMatch(/aria-live|role="(?:alert|status)"/)
  })
})
