import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { MASTERY, TopicChip, TopicChips, topicState } from "@/components/redesign"
import { visibleTopics } from "@/components/redesign/topics"

const TOPICS = [
  { topic: "Vectors", state: "work" as const, pct: 41 },
  { topic: "Algebra", state: "getting" as const, pct: 62 },
  { topic: "Number", state: "secure" as const, pct: 82 },
  { topic: "Probability", state: "secure" as const, pct: 88 },
]

describe("topicState", () => {
  it("uses the mock thresholds", () => {
    expect([topicState(59), topicState(60), topicState(74), topicState(75)]).toEqual(["work", "getting", "getting", "secure"])
  })
  it("reads its thresholds from MASTERY, the one shared source", () => {
    expect(MASTERY).toEqual({ getting: 0.6, secure: 0.75 })
    expect(topicState(MASTERY.secure * 100)).toBe("secure")
    expect(topicState(MASTERY.getting * 100 - 0.01)).toBe("work")
  })
})

describe("TopicChip", () => {
  it("names its state for screen readers and shows the percentage in Mono", () => {
    const out = renderToStaticMarkup(createElement(TopicChip, { topic: "Vectors", state: "work", pct: 41 }))
    expect(out).toMatch(/^<span class="rd-chip" data-state="work">/)
    expect(out).toContain('<span class="sr-only">, Work on</span>')
    expect(out).toContain("<b>41%</b>")
  })
  it("is a button when it opens something", () => {
    const out = renderToStaticMarkup(createElement(TopicChip, { topic: "Vectors", state: "work", onClick: () => {} }))
    expect(out).toMatch(/^<button type="button" class="rd-chip" data-state="work">/)
  })
})

describe("TopicChips", () => {
  it("folds secure topics into one chip that names the count", () => {
    const out = renderToStaticMarkup(createElement(TopicChips, { topics: TOPICS, foldSecure: true }))
    expect(out).not.toContain(">Number<")
    expect(out).toMatch(/class="rd-chip rd-chip-more"[^>]*aria-expanded="false"/)
    expect(out).toContain(">2 secure<")
  })
  it("shows everything unfolded, with the legend", () => {
    const out = renderToStaticMarkup(createElement(TopicChips, { topics: TOPICS }))
    expect(out).toContain(">Number<")
    expect(out).not.toContain("rd-chip-more")
    expect(out).toMatch(/<p class="rd-chip-legend" aria-hidden="true">.*Work on.*Getting there.*Secure/)
  })
})

describe("topic chip css", () => {
  const css = readFileSync(join(fileURLToPath(new URL("../../../", import.meta.url)), "src/components/redesign/redesign.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "")
  const at = (needle: string) => css.indexOf(needle)
  it("lets the fold chip rule follow the state rules it overrides", () => {
    expect(at(".rd-chip.rd-chip-more")).toBeGreaterThan(at('.rd-chip[data-state="secure"]'))
  })
  it("keeps the hover lift inside the motion query and off the colour rules", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: no-preference\)\s*\{\s*button\.rd-chip:hover\s*\{\s*translate: 0 -2px/)
  })
  it("never sets a state colour with an inverse token", () => {
    expect(css.match(/\.rd-chip[^{]*\{[^}]*--md-inverse/)).toBeNull()
  })
})

describe("visibleTopics", () => {
  it("hides secure topics while folded", () => {
    expect(visibleTopics(TOPICS, true, false).map((t) => t.topic)).toEqual(["Vectors", "Algebra"])
  })
  it("shows every topic once opened, order kept", () => {
    expect(visibleTopics(TOPICS, true, true).map((t) => t.topic)).toEqual(["Vectors", "Algebra", "Number", "Probability"])
  })
  it("shows every topic when folding is off", () => {
    expect(visibleTopics(TOPICS, false, false)).toHaveLength(4)
  })
  it("has nothing to fold when no topic is secure", () => {
    expect(visibleTopics(TOPICS.slice(0, 2), true, false)).toHaveLength(2)
  })
  it("folds to an empty list when every topic is secure", () => {
    expect(visibleTopics(TOPICS.slice(2), true, false)).toEqual([])
    expect(visibleTopics(TOPICS.slice(2), true, true)).toHaveLength(2)
  })
})
