import { createElement, type ComponentType } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import type { PaperBreakdown, Subject } from "@/lib/studentTypes"
import { GhostSteps, SubjectSteps } from "@/portals/student/screens/subject/SubjectSteps"
import { PathSection, nextPaperIndex } from "@/portals/student/screens/subject/PathSection"
import { buildSubjectView, type SubjectView } from "@/portals/student/screens/subject/subjectModel"
import { MATHS, MATHS_ONE, NOW } from "@/portals/student/screens/subject/fixtures"

const html = <P extends object>(node: ComponentType<P>, props: P) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(node, props)))

/** `buildSubjectView` is null only for the first-run screen, which these fixtures never are. */
function build(data: Subject, mode: "full" | "sparse", requestedPaper: string | null = null): SubjectView {
  const view = buildSubjectView({ data, catalogue: undefined, decks: [], examDate: null, now: NOW, requestedPaper, mode })
  if (!view) throw new Error("fixture produced no path")
  return view
}

/** The same subject with every paper's goal line replaced (null = no boundary resolved). */
const withGoal = (data: Subject, goal: (paper: PaperBreakdown) => PaperBreakdown["goal"]): Subject => ({
  ...data,
  papersBreakdown: data.papersBreakdown.map((paper) => ({ ...paper, goal: goal(paper) })),
})

const full = build(MATHS, "full")
const sparse = build(MATHS_ONE, "sparse")
const noGoal = build(withGoal(MATHS, () => null), "full")
const noGoalSparse = build(withGoal(MATHS_ONE, () => null), "sparse")
const gradeA = build(
  withGoal(MATHS, (paper) => ({
    grade: "A",
    marks: Math.round(paper.outOf * 0.85), // Paper 4: 68/80, so the 61 on the latest bar is 7 short
    outOf: paper.outOf,
    source: "global_default",
    sourceLabel: "Estimated boundary",
  })),
  "full",
)
const reached = build(
  withGoal(MATHS, (paper) => ({ grade: "A*", marks: 55, outOf: paper.outOf, source: "exact", sourceLabel: "May/Jun 2024 boundary" })),
  "full",
)

describe("SubjectSteps", () => {
  it("draws one linked bar per attempt with its grade, height and colour", () => {
    const out = html(SubjectSteps, { steps: full.path.steps })
    expect(out.match(/class="sj-stp"/g)).toHaveLength(4)
    expect(out).toContain('href="/student/result/6"')
    expect(out).toContain("--h:81%")
    expect(out).toContain("--c:var(--grade-a)")
    expect(out).toContain('data-current="true"')
    expect(out).toContain('aria-label="A, 61 out of 80, Apr. Open this paper"')
  })
  it("draws the goal block with the gap and its label row", () => {
    const out = html(SubjectSteps, { steps: full.path.steps })
    expect(out).toContain("sj-stp--goal")
    expect(out).toContain("7 to go")
    expect(out).toContain("A* line")
    expect(out).toContain('aria-expanded="false"')
  })
  it("names the whole path as one group for screen readers", () => {
    expect(html(SubjectSteps, { steps: full.path.steps })).toContain('role="group" aria-label="Paper 4 marks so far:')
  })
  it("adds ghost slots labelled next on the sparse path", () => {
    const out = html(SubjectSteps, { steps: sparse.path.steps })
    expect(out.match(/sj-stp--ghost/g)).toHaveLength(3)
    expect(out.match(/>next</g)).toHaveLength(3)
  })
  it("draws a hidden ghost path for the first run", () => {
    const out = html(GhostSteps, {})
    expect(out).toContain('aria-hidden="true"')
    expect(out.match(/sj-stp--ghost/g)).toHaveLength(4)
    expect(out).toContain("sj-stp--goal")
    expect(out.match(/--n:5/g)).toHaveLength(2)
    expect(out).not.toContain("sj-goal-label")
    expect(out).not.toMatch(/<b>.*?<\/b>/)
    expect(out).not.toContain(" line")
  })
  it("sizes the track to the bars, ghosts and goal it actually draws", () => {
    expect(html(SubjectSteps, { steps: full.path.steps }).match(/--n:5/g)).toHaveLength(2)
    expect(html(SubjectSteps, { steps: sparse.path.steps }).match(/--n:5/g)).toHaveLength(2)
    expect(html(SubjectSteps, { steps: noGoal.path.steps }).match(/--n:4/g)).toHaveLength(2)
    expect(html(SubjectSteps, { steps: noGoalSparse.path.steps }).match(/--n:4/g)).toHaveLength(2)
  })
  it("draws no goal block, goal label or disclosure when the paper has no goal", () => {
    const out = html(SubjectSteps, { steps: noGoal.path.steps })
    expect(out.match(/class="sj-stp"/g)).toHaveLength(4)
    expect(out).not.toContain("sj-stp--goal")
    expect(out).not.toContain("sj-goal-label")
    expect(out).not.toContain("aria-expanded")
    expect(out).not.toContain("aria-controls")
    expect(out).not.toContain("to go")
    expect(out).not.toContain(" line")
  })
  it("scales no-goal bars against the paper's full marks and keeps them linked", () => {
    const out = html(SubjectSteps, { steps: noGoal.path.steps })
    expect(out).toContain('href="/student/result/6"')
    expect(out).toContain('role="group" aria-label="Paper 4 marks so far:')
    expect(out).not.toContain("line is")
  })
  it("keeps the ghost slots on a sparse path that has no goal", () => {
    const out = html(SubjectSteps, { steps: noGoalSparse.path.steps })
    expect(out.match(/sj-stp--ghost/g)).toHaveLength(3)
    expect(out).not.toContain("sj-stp--goal")
  })
  it("labels a non-A* goal block with its own grade, marks and gap", () => {
    const out = html(SubjectSteps, { steps: gradeA.path.steps })
    expect(out).toContain("sj-stp--goal")
    expect(out).toContain("A line")
    expect(out).toContain("68<small>/80</small>")
    expect(out).toContain("7 to go")
    expect(out).toContain('aria-label="A line, 68 out of 80. 7 marks to go"')
    expect(out).not.toContain("A*")
  })
  it("says Reached, not a negative gap, once the latest paper is on or above the line", () => {
    const out = html(SubjectSteps, { steps: reached.path.steps })
    expect(out).toContain("Reached")
    expect(out).not.toContain("to go")
    expect(out).not.toMatch(/-\d+ marks?/)
  })
  it("draws the first-run ghost for an explicit A* goal", () => {
    const out = html(GhostSteps, { goalGrade: "A*" })
    expect(out).toContain("<b>A*</b>")
    expect(out).toContain("A* line")
  })
  it("draws the first-run ghost for another goal grade without naming A*", () => {
    const out = html(GhostSteps, { goalGrade: "B" })
    expect(out).toContain("B line")
    expect(out).not.toContain("A*")
  })
})

describe("PathSection", () => {
  it("titles the section with the goal and offers a tab per paper", () => {
    const out = html(PathSection, { path: full.path, onSelect: () => {} })
    expect(out).toContain("Your path to A*")
    expect(out).toContain('role="tablist"')
    expect(out.match(/role="tab"/g)).toHaveLength(2)
    expect(out).toMatch(/aria-selected="true"[^>]*>Paper 4</)
    expect(out).toContain('role="tabpanel"')
  })
  it("prints the trend line with the forecast grade", () => {
    const out = html(PathSection, { path: full.path, onSelect: () => {} })
    expect(out).toContain("Heading for")
    expect(out).toContain("up 16 marks since Oct")
  })
  it("hides the switch when there is one paper and prints the sparse line", () => {
    const out = html(PathSection, { path: sparse.path, onSelect: () => {} })
    expect(out).not.toContain('role="tablist"')
    expect(out).not.toContain('role="tabpanel"')
    expect(out).toContain("One step so far. Two more papers show your trend.")
  })
  it("uses a neutral heading, never A*, when the paper has no goal", () => {
    for (const view of [noGoal, noGoalSparse]) {
      const out = html(PathSection, { path: view.path, onSelect: () => {} })
      expect(out).toContain(">Your path<")
      expect(out).not.toContain("A*")
      expect(out).not.toContain("Your path to")
      expect(out).not.toContain("sj-goal-note")
    }
  })
  it("keeps the switch, trend and bars on a no-goal paper", () => {
    const out = html(PathSection, { path: noGoal.path, onSelect: () => {} })
    expect(out).toContain('role="tablist"')
    expect(out).toContain("up 16 marks since Oct")
    expect(out.match(/class="sj-stp"/g)).toHaveLength(4)
  })
  it("titles the section with a non-A* goal and keeps the goal note in step", () => {
    const out = html(PathSection, { path: gradeA.path, onSelect: () => {} })
    expect(out).toContain("Your path to A<")
    expect(out).not.toContain("A*")
    expect(out).toContain('id="sj-goal-note"')
    expect(out).toContain("A line from the estimated boundary.")
  })
  it("words the goal note from the boundary source, collapsed until the goal block is tapped", () => {
    const exact = html(PathSection, { path: full.path, onSelect: () => {} })
    expect(exact).toMatch(/<p id="sj-goal-note"[^>]*hidden=""[^>]*>A\* line from the May\/Jun 2024 boundary\.</)
    const average = build(MATHS, "full", "2")
    expect(html(PathSection, { path: average.path, onSelect: () => {} })).toContain(
      "A* line from the average of past boundaries.",
    )
  })
  it("selects the requested paper and gives only that tab a tab stop", () => {
    const out = html(PathSection, { path: build(MATHS, "full", "2").path, onSelect: () => {} })
    expect(out).toMatch(/id="sj-tab-2" aria-selected="true" aria-controls="sj-path-panel" tabindex="0"/)
    expect(out).toMatch(/id="sj-tab-4" aria-selected="false" aria-controls="sj-path-panel" tabindex="-1"/)
    expect(out).toContain('aria-labelledby="sj-tab-2"')
    expect(out).toContain('href="/student/result/5"')
  })
})

describe("nextPaperIndex", () => {
  it("moves right with ArrowRight and left with ArrowLeft, wrapping at both ends", () => {
    expect(nextPaperIndex(0, "ArrowRight", 2, false)).toBe(1)
    expect(nextPaperIndex(1, "ArrowRight", 2, false)).toBe(0)
    expect(nextPaperIndex(1, "ArrowLeft", 2, false)).toBe(0)
    expect(nextPaperIndex(0, "ArrowLeft", 2, false)).toBe(1)
    expect(nextPaperIndex(1, "ArrowRight", 3, false)).toBe(2)
    expect(nextPaperIndex(0, "ArrowLeft", 3, false)).toBe(2)
  })
  it("mirrors the arrows under dir=rtl so ArrowLeft still moves visually forward", () => {
    expect(nextPaperIndex(0, "ArrowLeft", 3, true)).toBe(1)
    expect(nextPaperIndex(1, "ArrowRight", 3, true)).toBe(0)
    expect(nextPaperIndex(0, "ArrowRight", 3, true)).toBe(2)
  })
  it("ignores every other key", () => {
    for (const key of ["ArrowUp", "ArrowDown", "Enter", " ", "Tab", "Home", "End"]) {
      expect(nextPaperIndex(0, key, 2, false)).toBeNull()
    }
  })
})
