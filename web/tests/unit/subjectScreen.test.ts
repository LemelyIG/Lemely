import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement, isValidElement, useState, type ComponentProps, type ComponentType, type ElementType, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import { TopicChips } from "@/components/redesign"
import type { PaperBreakdown, Subject } from "@/lib/studentTypes"
import { GhostSteps, SubjectSteps } from "@/portals/student/screens/subject/SubjectSteps"
import { PathSection, nextPaperIndex } from "@/portals/student/screens/subject/PathSection"
import { TipSection } from "@/portals/student/screens/subject/TipSection"
import { WinList } from "@/portals/student/screens/subject/WinList"
import { TopicsSection } from "@/portals/student/screens/subject/TopicsSection"
import { PapersList, focusRowAfterExpand } from "@/portals/student/screens/subject/PapersList"
import { SubjectHeader } from "@/portals/student/screens/subject/SubjectHeader"
import { SubjectBody } from "@/portals/student/screens/subject/SubjectBody"
import { SubjectFirstRun } from "@/portals/student/screens/subject/SubjectFirstRun"
import { SubjectLoading } from "@/portals/student/screens/subject/SubjectLoading"
import { SubjectError } from "@/portals/student/screens/subject/SubjectError"
import { SubjectRefreshNotice } from "@/portals/student/screens/subject/SubjectRefreshNotice"
import { GHOST_CHIPS, buildSubjectView, firstRunTip, winRows, type SubjectView, type TopicChipView } from "@/portals/student/screens/subject/subjectModel"
import { MATHS, MATHS_ONE, MATHS_TOPICS, NOW } from "@/portals/student/screens/subject/fixtures"

/*
 * SubjectBody holds two hooks, so its element tree can only be read by calling it. `useNavigate` needs
 * a router context, so it is replaced by one spy. `useState` keeps the real hook everywhere except the
 * single call a test queues with `mockImplementationOnce`.
 */
const navigate = vi.hoisted(() => vi.fn())
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}))
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>()
  return { ...actual, useState: vi.fn(actual.useState) }
})

const html = <P extends object>(node: ComponentType<P>, props: P) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(node, props)))

/** Every element of `type` in a tree a hookless component returned (or SubjectBody, called by hand), as its props. */
function propsOf<T extends ElementType>(root: ReactNode, type: T): ComponentProps<T>[] {
  const found: ComponentProps<T>[] = []
  const walk = (node: ReactNode): void => {
    if (Array.isArray(node)) return node.forEach(walk)
    if (!isValidElement<{ children?: ReactNode }>(node)) return
    if (node.type === type) found.push(node.props as unknown as ComponentProps<T>)
    walk(node.props.children)
  }
  walk(root)
  return found
}

function only<T extends ElementType>(root: ReactNode, type: T): ComponentProps<T> {
  const found = propsOf(root, type)
  if (found.length !== 1) throw new Error(`expected one ${String(typeof type === "string" ? type : (type as { name?: string }).name)}, found ${found.length}`)
  return found[0]
}

/**
 * What TopicsSection hands the kit's chips. The section holds no hooks, so calling it returns its
 * element tree; the kit reports a click as the text it drew, which is `topic` on each item.
 */
function kitChips(props: ComponentProps<typeof TopicsSection>): ComponentProps<typeof TopicChips> {
  let found: ComponentProps<typeof TopicChips> | null = null
  const walk = (node: ReactNode): void => {
    if (Array.isArray(node)) return node.forEach(walk)
    if (!isValidElement<{ children?: ReactNode }>(node)) return
    if (node.type === TopicChips) found = node.props as unknown as ComponentProps<typeof TopicChips>
    walk(node.props.children)
  }
  walk(TopicsSection(props))
  if (!found) throw new Error("TopicsSection drew no TopicChips")
  return found
}

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

describe("TipSection", () => {
  it("shows Binny's line and a button naming the action and its marks", () => {
    const out = html(TipSection, { tip: full.tip, size: 60 })
    expect(out).toContain("7 marks to A*")
    expect(out).toContain('href="/student/practice/0580?topic=C7%20Vectors"')
    expect(out).toContain("Practise Vectors")
    expect(out).toContain("· +9 marks")
  })
  it("adds the secondary link on the first run", () => {
    const out = html(TipSection, { tip: firstRunTip("0580", "Mathematics"), size: 60 })
    expect(out).toContain("Upload a PDF instead")
    expect(out).toContain('href="/student/correct?subject=0580&amp;source=file"')
  })
  it("has no secondary link once the student has papers", () => {
    expect(html(TipSection, { tip: full.tip, size: 60 })).not.toContain("Upload a PDF instead")
  })
  it("never names A* when the paper has no goal", () => {
    const out = html(TipSection, { tip: noGoal.tip, size: 60 })
    expect(out).toContain("Next paper?")
    expect(out).not.toContain("A*")
  })
})

/* ── Contrast of the Tip button's detail text, measured from the real tokens ───────────────────── */

const WEB_ROOT = join(import.meta.dirname, "..", "..")
const subjectCss = readFileSync(join(WEB_ROOT, "src/portals/student/screens/subject/subject.css"), "utf8")
const tokenCss = readFileSync(join(WEB_ROOT, "src/index.css"), "utf8")

type Rgb = [number, number, number]

/** The body of the first `header {` block in the token file, so each theme reads its own values. */
function themeBlock(header: string): string {
  const start = tokenCss.indexOf(`${header} {`)
  if (start < 0) throw new Error(`no ${header} block in index.css`)
  return tokenCss.slice(start, tokenCss.indexOf("\n}", start))
}

function hexToken(block: string, name: string): Rgb {
  const m = new RegExp(`${name}:\\s*#([0-9a-fA-F]{6})`).exec(block)
  if (!m) throw new Error(`${name} is not a hex colour in this block`)
  return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)) as Rgb
}

const toLinear = (c: number) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const luminance = ([r, g, b]: Rgb) => 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

function toOklab(rgb: Rgb): Rgb {
  const [r, g, b] = rgb.map(toLinear)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function fromOklab([L, a, b]: Rgb): Rgb {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  const encode = (x: number) => {
    const v = Math.min(1, Math.max(0, x))
    return 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)
  }
  return [
    encode(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    encode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    encode(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

/** Resolves `var(--tok)` or `color-mix(in oklab, var(--a) N%, var(--b))` against one theme's tokens. */
function resolveColor(value: string, block: string): Rgb {
  const plain = /^var\((--[\w-]+)\)$/.exec(value.trim())
  if (plain) return hexToken(block, plain[1])
  const mix = /^color-mix\(in oklab,\s*var\((--[\w-]+)\)\s+(\d+)%,\s*var\((--[\w-]+)\)\)$/.exec(value.trim())
  if (!mix) throw new Error(`cannot resolve colour "${value}": use a token or a token mix in oklab`)
  const [from, to] = [toOklab(hexToken(block, mix[1])), toOklab(hexToken(block, mix[3]))]
  const p = Number(mix[2]) / 100
  return fromOklab(from.map((v, i) => v * p + to[i] * (1 - p)) as Rgb)
}

describe("TipSection detail text", () => {
  const rule = /\.sj-go span\s*\{([^}]*)\}/.exec(subjectCss)?.[1] ?? ""
  it("does not dim the detail with opacity, which lets the button fill bleed into the text", () => {
    expect(rule).not.toBe("")
    expect(rule).not.toMatch(/opacity/)
  })
  it("takes its colour from the on-primary token", () => {
    const color = /(?:^|[;\s])color:\s*([^;]+)/.exec(rule)?.[1]
    expect(color).toBeDefined()
    expect(color).toContain("var(--md-on-primary)")
  })
  for (const [theme, header] of [
    ["light", ":root"],
    ["dark", ':root[data-theme="dark"]'],
  ] as const) {
    it(`clears 4.5:1 on the primary fill, resting and hovered, in ${theme} mode`, () => {
      const color = /(?:^|[;\s])color:\s*([^;]+)/.exec(rule)?.[1]
      if (!color) throw new Error(".sj-go span sets no colour")
      const block = themeBlock(header)
      const text = resolveColor(color, block)
      for (const fill of ["--md-primary", "--md-primary-hover"]) {
        expect(contrast(text, hexToken(block, fill))).toBeGreaterThanOrEqual(4.5)
      }
    })
  }
})

describe("WinList", () => {
  const win = winRows("0580", MATHS_TOPICS, [{ id: "alg", subjectCode: "0580", topic: "C2 Algebra", title: "", description: null, origin: "topic", cardCount: 1, dueCount: 0, createdAt: "" }], "full")
  it("lists each topic with its marks and a practice link, heading linked to practice", () => {
    const out = html(WinList, { win, allTo: "/student/practice/0580" })
    expect(out).toContain("More marks to win")
    expect(out).toContain('href="/student/practice/0580"')
    expect(out).toContain('href="/student/practice/0580?topic=C2%20Algebra"')
    expect(out).toContain("+7")
    expect(out.match(/<li/g)).toHaveLength(3)
  })
  it("offers flashcards only where a deck exists for the topic", () => {
    const out = html(WinList, { win, allTo: "/student/practice/0580" })
    expect(out).toContain('href="/student/flashcards/0580?deck=alg"')
    expect(out).toContain('aria-label="Algebra flashcards"')
    expect(out.match(/sj-fcx/g)).toHaveLength(2)
  })
  it("draws nothing when no topic has marks left to win", () => {
    expect(html(WinList, { win: { heading: "Marks to win", rows: [] }, allTo: "/student/practice/0580" })).toBe("")
  })
})

describe("TopicsSection", () => {
  it("renders the chips, the legend and no hint on the full screen", () => {
    const out = html(TopicsSection, { chips: full.chips, foldSecure: true, hint: null, onSelect: () => {} })
    expect(out).toContain("Topics")
    expect(out).toContain("Vectors")
    expect(out).toContain("Work on")
    expect(out).toContain("Getting there")
    expect(out).toContain("Secure")
  })
  it("prints the legend once, from the kit", () => {
    const out = html(TopicsSection, { chips: full.chips, foldSecure: false, hint: null, onSelect: () => {} })
    expect(out.match(/rd-chip-legend/g)).toHaveLength(1)
    // Each getting-state chip also says ", Getting there" to screen readers; only the legend says it bare.
    expect(out.match(/(?<!, )Getting there/g)).toHaveLength(1)
  })
  it("sends each chip's own topic to onSelect, with the short name on screen", () => {
    const clicked: string[] = []
    const kit = kitChips({ chips: full.chips, foldSecure: false, hint: null, onSelect: (t) => clicked.push(t) })
    expect(kit.topics.map((t) => t.topic)).toEqual(full.chips.map((c) => c.label))
    for (const item of kit.topics) kit.onSelect?.(item.topic)
    expect(clicked).toEqual(full.chips.map((c) => c.topic))
    expect(clicked).toContain("C7 Vectors")
  })
  it("routes two topics that share a short name to their own topic, and tells them apart on screen", () => {
    const chip = (topic: string, label: string, pct: number): TopicChipView => ({ topic, label, state: "work", pct })
    const chips = [chip("C1 Number", "Number", 40), chip("E1 Number", "Number", 45), chip("C2 Algebra", "Algebra", 50)]
    const clicked: string[] = []
    const props = { chips, foldSecure: false, hint: null, onSelect: (t: string) => clicked.push(t) }
    const kit = kitChips(props)
    for (const item of kit.topics) kit.onSelect?.(item.topic)
    expect(clicked).toEqual(["C1 Number", "E1 Number", "C2 Algebra"])
    // The two Number chips show their full names; the unique one keeps its short name.
    expect(kit.topics.map((t) => t.topic)).toEqual(["C1 Number", "E1 Number", "Algebra"])
    const out = html(TopicsSection, props)
    expect(out).toContain("C1 Number")
    expect(out).toContain("E1 Number")
    expect(out).not.toContain(">Number<")
  })
  it("prints the sparse hint", () => {
    const out = html(TopicsSection, { chips: sparse.chips, foldSecure: false, hint: "4 of 10 topics so far. Each paper fills in more.", onSelect: () => {} })
    expect(out).toContain("4 of 10 topics so far. Each paper fills in more.")
  })
  it("prints only the hint, with no chips or legend, when no topic has lost a mark yet", () => {
    const out = html(TopicsSection, { chips: [], foldSecure: false, hint: "Topics show up once a paper loses a mark.", onSelect: () => {} })
    expect(out).toContain("Topics show up once a paper loses a mark.")
    expect(out).not.toContain("rd-chip")
  })
})

describe("PapersList", () => {
  it("draws nothing, not an empty heading, when there are no papers", () => {
    expect(html(PapersList, { rows: [], visible: 4, onShowAll: () => {} })).toBe("")
  })
  it("shows the visible rows and an All N papers control", () => {
    const out = html(PapersList, { rows: full.papers, visible: 4, onShowAll: () => {} })
    expect(out).toContain("Papers")
    expect(out.match(/href="\/student\/result\//g)).toHaveLength(4)
    expect(out).toContain("All 7 papers")
    expect(out).toContain("0580/42 · May/Jun 2024")
    expect(out).toContain("61/80 · Apr")
  })
  it("drops the control once everything is visible", () => {
    const out = html(PapersList, { rows: full.papers, visible: 7, onShowAll: () => {} })
    expect(out).not.toContain("All 7 papers")
  })
})

describe("focusRowAfterExpand", () => {
  // The All N papers button unmounts when pressed, so keyboard focus has to land somewhere real.
  it("lands on the first row the press revealed", () => {
    expect(focusRowAfterExpand(4, 7)).toBe(4)
    expect(focusRowAfterExpand(1, 2)).toBe(1)
  })
  it("never points past the last row", () => {
    expect(focusRowAfterExpand(9, 7)).toBe(6)
  })
  it("has no target when there are no rows", () => {
    expect(focusRowAfterExpand(0, 0)).toBeNull()
  })
  it("is what PapersList calls once the button has gone", () => {
    const source = readFileSync(join(WEB_ROOT, "src/portals/student/screens/subject/PapersList.tsx"), "utf8")
    expect(source).toContain("focusRowAfterExpand(")
    expect(source).toMatch(/\.focus\(\)/)
  })
})

describe("SubjectHeader", () => {
  it("names the page in an h1 with the subtitle (K3, K6)", () => {
    const out = html(SubjectHeader, { title: "Mathematics", subtitle: "IGCSE · 0580 · Extended", examDate: null, planTo: "/student/plan/0580", now: NOW })
    expect(out).toMatch(/<h1[^>]*>Mathematics<\/h1>/)
    expect(out).toContain("IGCSE · 0580 · Extended")
    expect(out).not.toContain('href="/student/plan/0580"')
  })
  it("links the countdown pill to the study plan when an exam is dated", () => {
    const out = html(SubjectHeader, { title: "Mathematics", subtitle: "", examDate: "2025-05-27", planTo: "/student/plan/0580", now: NOW })
    expect(out).toContain('href="/student/plan/0580"')
    expect(out).toContain("rd-pill")
  })
  it("draws no pill once the exam has passed", () => {
    const out = html(SubjectHeader, { title: "Mathematics", subtitle: "", examDate: "2024-01-05", planTo: "/student/plan/0580", now: NOW })
    expect(out).not.toContain("rd-pill")
  })
})

describe("SubjectBody", () => {
  it("renders every full-screen section in phone order", () => {
    const out = html(SubjectBody, { view: full, code: "0580", wide: false, twoCol: false, onSelectPaper: () => {} })
    const order = ["Your path to A*", "7 marks to A*", "More marks to win", "Topics", "Papers"].map((s) => out.indexOf(s))
    expect(order.every((i) => i >= 0)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
    expect(out.match(/class="sj-col"/g)).toHaveLength(2)
  })
  it("hides the win section when there is nothing to win", () => {
    const empty = { ...full, win: { heading: "More marks to win", rows: [] } }
    expect(html(SubjectBody, { view: empty, code: "0580", wide: false, twoCol: false, onSelectPaper: () => {} })).not.toContain("More marks to win")
  })
  it("draws the sparse screen with its own heading", () => {
    const out = html(SubjectBody, { view: sparse, code: "0580", wide: false, twoCol: false, onSelectPaper: () => {} })
    expect(out).toContain("Your path to A*")
    expect(out.match(/class="sj-col"/g)).toHaveLength(2)
  })
})

describe("SubjectBody wiring", () => {
  type BodyProps = ComponentProps<typeof SubjectBody>
  const baseProps = (over: Partial<BodyProps> = {}): BodyProps => ({ view: full, code: "0580", wide: false, twoCol: false, onSelectPaper: () => {}, ...over })
  /** One call of the component with the papers list collapsed (`expanded` false) unless told otherwise. */
  const draw = (over: Partial<BodyProps> = {}, expanded = false) => {
    const setExpanded = vi.fn()
    vi.mocked(useState).mockImplementationOnce((() => [expanded, setExpanded]) as unknown as typeof useState)
    return { tree: SubjectBody(baseProps(over)), setExpanded }
  }
  const sections = (tree: ReactNode) => ({
    path: only(tree, PathSection),
    tip: only(tree, TipSection),
    topics: only(tree, TopicsSection),
    papers: only(tree, PapersList),
  })

  it("hands each section its own slice of the view", () => {
    const { tree } = draw()
    const { path, tip, topics, papers } = sections(tree)
    expect(path.path).toBe(full.path)
    expect(tip.tip).toBe(full.tip)
    expect(topics.chips).toBe(full.chips)
    expect(topics.hint).toBe(full.topicsHint)
    expect(papers.rows).toBe(full.papers)
    expect(only(tree, WinList).win).toBe(full.win)
  })
  it("hands the topics section the sparse hint, which the full view leaves null", () => {
    expect(sparse.topicsHint).not.toBeNull()
    expect(sections(draw({ view: sparse }).tree).topics.hint).toBe(sparse.topicsHint)
  })
  it("puts path, tip and win on the left and topics and papers on the right", () => {
    const { tree } = draw()
    const root = tree as { props: { children: ReactNode } }
    const columns = (root.props.children as ReactNode[]).filter(isValidElement)
    expect(columns).toHaveLength(2)
    const typesIn = (col: ReactNode) =>
      ((col as { props: { children: ReactNode } }).props.children as ReactNode[]).filter(isValidElement).map((e) => e.type)
    expect(typesIn(columns[0])).toEqual([PathSection, TipSection, WinList])
    expect(typesIn(columns[1])).toEqual([TopicsSection, PapersList])
  })
  it("sends a tab press on the path to onSelectPaper", () => {
    const onSelectPaper = vi.fn()
    const { path } = sections(draw({ onSelectPaper }).tree)
    path.onSelect(2)
    expect(onSelectPaper).toHaveBeenCalledTimes(1)
    expect(onSelectPaper).toHaveBeenCalledWith(2)
  })
  it("sends a topic chip press to that topic's practice page for this subject", () => {
    navigate.mockClear()
    const { topics } = sections(draw({ code: "0625" }).tree)
    topics.onSelect("C7 Vectors")
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith("/student/practice/0625?topic=C7%20Vectors")
  })
  it("links the win heading to this subject's practice page", () => {
    expect(only(draw({ code: "0625" }).tree, WinList).allTo).toBe("/student/practice/0625")
  })
  it("draws no win list when no topic has marks left to win", () => {
    const view = { ...full, win: { heading: "More marks to win", rows: [] } }
    expect(propsOf(draw({ view }).tree, WinList)).toHaveLength(0)
  })
  it("sizes Binny 60 on a phone, 64 in two columns and 72 when wide", () => {
    const size = (wide: boolean, twoCol: boolean) => sections(draw({ wide, twoCol }).tree).tip.size
    expect(size(false, false)).toBe(60)
    expect(size(false, true)).toBe(64)
    expect(size(true, false)).toBe(72)
    expect(size(true, true)).toBe(72)
  })
  it("shows four papers on a phone and five when wide", () => {
    expect(sections(draw({ wide: false }).tree).papers.visible).toBe(4)
    expect(sections(draw({ wide: true }).tree).papers.visible).toBe(5)
  })
  it("shows every paper once All N papers has been pressed, and presses it through state", () => {
    const first = draw()
    expect(sections(first.tree).papers.visible).toBe(4)
    sections(first.tree).papers.onShowAll()
    expect(first.setExpanded).toHaveBeenCalledTimes(1)
    expect(first.setExpanded).toHaveBeenCalledWith(true)
    expect(sections(draw({}, true).tree).papers.visible).toBe(full.papers.length)
    expect(sections(draw({ wide: true }, true).tree).papers.visible).toBe(full.papers.length)
  })
  it("folds the secure chips only on the full screen and only on a phone", () => {
    const fold = (view: SubjectView, wide: boolean) => sections(draw({ view, wide }).tree).topics.foldSecure
    expect(fold(full, false)).toBe(true)
    expect(fold(full, true)).toBe(false)
    expect(fold(sparse, false)).toBe(false)
    expect(fold(sparse, true)).toBe(false)
  })
})

describe("first run, loading and error", () => {
  const firstRun = () => html(SubjectFirstRun, { code: "0580", name: "Mathematics", wide: false, twoCol: false })
  it("walks a new student through the first scan (K2)", () => {
    const out = firstRun()
    expect(out).toContain("Your path to A*")
    expect(out).toContain("Find your first step")
    expect(out).toContain("Scan a Mathematics paper")
    expect(out).toContain("Upload a PDF instead")
    expect(out).toContain("Lemely marks it")
    expect(out).toContain("Every Mathematics paper you mark lands here, newest first.")
  })
  it("draws the ghost path with the A* goal labelled, hidden from screen readers", () => {
    const out = firstRun()
    expect(out).toContain('<div class="sj-steps sj-steps--ghost" aria-hidden="true">')
    expect(out).toContain("<b>A*</b>")
    expect(out).toContain("A* line")
    expect(only(SubjectFirstRun({ code: "0580", name: "Mathematics", wide: false, twoCol: false }), GhostSteps).goalGrade).toBe("A*")
  })
  it("hides the ghost topic chips from screen readers and draws all of them", () => {
    const out = firstRun()
    expect(out).toContain('<div class="sj-ghostchips" aria-hidden="true">')
    expect(out.match(/class="sj-ghostchip"/g)).toHaveLength(GHOST_CHIPS.length)
  })
  it("marks the right column as the first-run aside", () => {
    const out = firstRun()
    expect(out).toContain('<div class="sj-col sj-col--aside-first-run">')
    expect(out.match(/class="sj-col"/g)).toHaveLength(1)
  })
  it("announces the load as one named status region, left live (K4)", () => {
    const out = html(SubjectLoading, { name: "Mathematics" })
    expect(out).toContain('role="status"')
    expect(out).toContain('aria-label="Loading Mathematics"')
    // aria-busy="true" would mute the live region the status role exists to announce through.
    expect(out).not.toContain("aria-busy")
  })
  it("offers a retry and a way home on error (K5)", () => {
    const out = html(SubjectError, { name: "Mathematics", onRetry: () => {} })
    expect(out).toContain("We couldn’t load Mathematics")
    expect(out).toContain("Check your connection, then try again. Your papers are safe.")
    expect(out).toContain("Try again")
    expect(out).toContain('href="/student"')
    expect(out).toContain('role="alert"')
  })
  it("calls onRetry once when Try again is pressed", () => {
    const onRetry = vi.fn()
    const buttons = propsOf(SubjectError({ name: "Mathematics", onRetry }), "button")
    expect(buttons).toHaveLength(1)
    expect(buttons[0].children).toBe("Try again")
    expect(buttons[0].type).toBe("button")
    buttons[0].onClick?.({} as never)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})

describe("SubjectRefreshNotice", () => {
  it("says the refresh failed and that the last loaded view is still showing, in a quiet status region", () => {
    const out = html(SubjectRefreshNotice, { name: "Mathematics", onRetry: () => {}, pending: false })
    expect(out).toContain('role="status"')
    expect(out).not.toContain('role="alert"')
    expect(out).toContain("Couldn’t refresh Mathematics.")
    expect(out).toContain("Showing what loaded before.")
    expect(out).toContain("Try again")
    expect(out).not.toContain("!")
  })
  it("calls onRetry once when Try again is pressed", () => {
    const onRetry = vi.fn()
    const buttons = propsOf(SubjectRefreshNotice({ name: "Mathematics", onRetry, pending: false }), "button")
    expect(buttons).toHaveLength(1)
    buttons[0].onClick?.({} as never)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
  it("disables the button while the retry is running", () => {
    const [button] = propsOf(SubjectRefreshNotice({ name: "Mathematics", onRetry: () => {}, pending: true }), "button")
    expect(button.disabled).toBe(true)
    const [idle] = propsOf(SubjectRefreshNotice({ name: "Mathematics", onRetry: () => {}, pending: false }), "button")
    expect(idle.disabled).toBe(false)
  })
})
