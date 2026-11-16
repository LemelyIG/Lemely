import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { StepsPath } from "@/components/redesign"
import { gradeColorVar, stepHeight, stepsSummary } from "@/components/redesign/grades"

const PAPERS = [
  { id: "p1", label: "Oct", grade: "C", pct: 56, caption: "45/80" },
  { id: "p2", label: "Jan", grade: "B", pct: 60, marks: { got: 48, max: 80 } },
  { id: "p3", label: "Apr", grade: "A", pct: 76, caption: "61/80" },
]
const html = (p: Parameters<typeof StepsPath>[0]) => renderToStaticMarkup(createElement(StepsPath, p))

describe("grades helpers", () => {
  it("maps grades to the token ramp", () => {
    expect(gradeColorVar("A*")).toBe("var(--grade-a-star)")
    expect(gradeColorVar("b")).toBe("var(--grade-b)")
    expect(gradeColorVar("?")).toBe("var(--md-outline)")
  })
  it("scales bars from 40% of the marks up to the goal line (sjf.js hOf)", () => {
    expect(stepHeight(56, 85)).toBe(36)
    expect(stepHeight(85, 85)).toBe(100)
    expect(stepHeight(30, 85)).toBe(0)
    expect(stepHeight(120, 85)).toBe(100)
    expect(stepHeight(70, 30)).toBe(100)
  })
  it("summarises the path in words", () => {
    expect(stepsSummary(PAPERS.slice(0, 2), "A*", "7 to go")).toBe("Marks so far: C, 45/80 in Oct; B, 48 out of 80 in Jan. Goal A*, 7 to go.")
    expect(stepsSummary([], undefined)).toBe("No papers yet.")
  })
})

describe("StepsPath", () => {
  it("one bar per paper, the latest solid, then the goal block and its caption", () => {
    const out = html({ papers: PAPERS, goal: "A*", goalPct: 85, goalCaption: "68/80 · A* line", goalNote: "7 to go" })
    expect(out.match(/class="rd-step"/g)).toHaveLength(4)
    expect(out.match(/data-current=""/g)).toHaveLength(2) // the bar and its label
    expect(out).toMatch(/data-goal=""[^>]*><b>A\*<\/b><span>7 to go<\/span>/)
    expect(out).toContain('<span data-goal="">68/80 · A* line</span>')
    expect(out).toContain("<b>48/80</b>Jan") // marks become the Mono line when there is no caption
    expect(out).toMatch(/--n:4/)
  })
  it("the goal caption defaults to the grade's line", () => {
    expect(html({ papers: PAPERS, goal: "A" })).toContain('<span data-goal="">A line</span>')
  })
  it("bars are buttons named by grade, marks and date when selectable", () => {
    const out = html({ papers: PAPERS, onSelect: () => {} })
    expect(out).toMatch(/<button type="button" class="rd-step"[^>]*aria-label="B, 48 out of 80, Jan"/)
    expect(out).toMatch(/aria-label="C, 45\/80, Oct"/)
  })
  it("sparse: ghosts after the papers are labelled next", () => {
    const out = html({ papers: PAPERS.slice(2), goal: "A*", ghosts: 3 })
    expect(out.match(/data-ghost=""/g)).toHaveLength(6)
    expect(out.match(/>next</g)).toHaveLength(3)
  })
  it("first run: no papers draws four fixed-height ghosts and the goal", () => {
    const out = html({ papers: [], goal: "A*", ghosts: 4 })
    expect(out).toMatch(/--h:30%/)
    expect(out).toMatch(/--h:70%/)
    expect(out).not.toContain(">next<")
  })
  it("first run marks the path empty so the goal block stays static (mock .ghostp .stp.goal)", () => {
    expect(html({ papers: [], goal: "A*", ghosts: 4 })).toMatch(/class="rd-steps"[^>]*data-empty=""/)
    expect(html({ papers: PAPERS, goal: "A*" })).not.toContain("data-empty")
  })
  it("the css switches the goal grow off for an empty path, inside the motion block", () => {
    const css = readFileSync(join(__dirname, "../../../src/components/redesign/redesign.css"), "utf8")
    expect(css).toMatch(/@media \(prefers-reduced-motion: no-preference\)[\s\S]*\.rd-steps\[data-empty\] \.rd-step\[data-goal\] \{ animation: none; \}/)
  })
})
