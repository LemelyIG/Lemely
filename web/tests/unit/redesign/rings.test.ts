import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { GoldRing, KeyRing } from "@/components/redesign"
import { clamp01, goldRingDone, goldRingGeometry, keyRingGeometry } from "@/components/redesign/rings"

describe("ring geometry", () => {
  it("matches the mock ring4 at 32px (r 13, stroke 4.5, 23-unit segments)", () => {
    const g = goldRingGeometry(32)
    expect(g.r).toBe(13)
    expect(g.stroke).toBe(4.5)
    expect(g.dash).toBeCloseTo(23.1, 0)
  })
  it("matches the mock level ring at 92px (r 42, stroke 6)", () => {
    expect(keyRingGeometry(92)).toMatchObject({ r: 42, stroke: 6 })
  })
  it("clamps to 0..1 and treats NaN as 0", () => {
    expect([clamp01(-1), clamp01(0.4), clamp01(3), clamp01(Number.NaN)]).toEqual([0, 0.4, 1, 0])
  })
  it("counts only complete parts as done", () => {
    expect(goldRingDone([1, 0.99, 0])).toBe(1)
  })
})

describe("GoldRing", () => {
  it("is gold only for a complete part", () => {
    const out = renderToStaticMarkup(createElement(GoldRing, { parts: [1, 0.5, 0] }))
    expect(out.match(/rd-ring-gold/g)).toHaveLength(1)
    expect(out.match(/rd-ring-partial/g)).toHaveLength(1)
    expect(out).toMatch(/aria-label="1 of 3 done"/)
  })
  it("renders a centre and a custom label", () => {
    const out = renderToStaticMarkup(createElement(GoldRing, { parts: [1, 1, 1], size: 60, label: "Today: 3 of 3", center: "3/3" }))
    expect(out).toMatch(/aria-label="Today: 3 of 3"/)
    expect(out).toMatch(/<span class="rd-ring-center" aria-hidden="true">3\/3<\/span>/)
  })
})

describe("KeyRing", () => {
  it("draws the value arc in its tone with the label as the name", () => {
    const out = renderToStaticMarkup(createElement(KeyRing, { value: 0.48, tone: "gold", center: "7", label: "Level 7, 48% to level 8" }))
    expect(out).toMatch(/role="img" aria-label="Level 7, 48% to level 8"/)
    expect(out).toContain("rd-ring-tone-gold")
    expect(out).toMatch(/stroke-dasharray="126\.7 263\.9"/)
  })
  it("warn is the error red; neutral draws no arc and mutes the centre", () => {
    const warn = renderToStaticMarkup(createElement(KeyRing, { value: 0.62, tone: "warn", center: "62%", label: "Confidence 62%" }))
    expect(warn).toContain("rd-ring-tone-warn")
    const none = renderToStaticMarkup(createElement(KeyRing, { value: 0, tone: "neutral", center: "–", label: "No score yet" }))
    expect(none).toMatch(/data-tone="neutral"/)
    expect(none).not.toContain("stroke-dasharray")
  })
})
