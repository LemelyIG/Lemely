import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { HomeSkeleton } from "@/portals/student/home/HomeSkeleton"
import { WeekStrip } from "@/portals/student/home/WeekStrip"

/*
 * The week strip sits in the third Home column, whose width is a share of the Home container minus the
 * grid gaps, the band's start border and its padding. The strip must answer to the width its own column
 * gives it, not to the Home container, or seven 44px targets collide in the 1100 to 1187px band. This
 * runner is node-only (see vitest.config.ts), so the contract is read off the rendered class lists.
 */

const TARGET = 44
const GAP = 2
const SEVEN_ACROSS = 7 * TARGET + 6 * GAP

const days = Array.from({ length: 7 }, (_, i) => ({
  day: String(i),
  letter: "MTWTFSS"[i] ?? "M",
  to: "/",
  ariaLabel: `Day ${i}`,
  isToday: i === 2,
  done: i < 2,
}))

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(createElement(MemoryRouter, null, node))
const strip = () => html(createElement(WeekStrip, { days }))
const skeleton = () => html(createElement(HomeSkeleton))

/* The width, in px, below which the strip drops to four columns, read off its own-column container query. */
function fourColumnCeiling(markup: string, utility = "grid-cols-4"): number {
  const m = new RegExp(`@\\[900px\\]/home:@max-\\[([\\d.]+)px\\]/week:${utility}`).exec(markup)
  expect(m, "wrap rule reads the strip's own column width").not.toBeNull()
  return Number(m?.[1])
}

describe("week strip responds to its own column", () => {
  it("measures its own width through a named container", () => {
    expect(strip()).toContain("@container/week")
  })

  it("never picks seven columns from the Home container width", () => {
    expect(strip()).not.toMatch(/@\[\d+px\]\/home:grid-cols-7/)
  })

  it("keeps seven across until the column is narrower than seven targets plus gaps", () => {
    const ceiling = fourColumnCeiling(strip())
    // Any width below SEVEN_ACROSS must wrap, and SEVEN_ACROSS itself must still fit seven across.
    expect(ceiling).toBeLessThan(SEVEN_ACROSS)
    expect(ceiling).toBeGreaterThan(SEVEN_ACROSS - 1)
  })

  it("leaves the phone and tablet strip at seven across", () => {
    expect(strip()).toContain("grid-cols-7")
    expect(strip()).not.toMatch(/(?<!@\[900px\]\/home:)(?<!\/week:)grid-cols-4/)
  })
})

describe("Home desktop layout switches at one width", () => {
  it("uses the same Home container threshold in the screen, the top row and the skeleton", () => {
    const dir = resolve(__dirname, "../../src/portals/student/home")
    const widths = new Set<string>()
    for (const file of ["HomeScreen.tsx", "HomeTopRow.tsx", "HomeSkeleton.tsx"]) {
      for (const m of readFileSync(resolve(dir, file), "utf8").matchAll(/@\[(\d+)px\]\/home/g)) widths.add(m[1] ?? "")
    }
    // A second threshold leaves a band where the heading and the pills disagree and jump on load.
    expect([...widths]).toEqual(["900"])
  })
})

describe("skeleton keeps the week placeholder in step with the strip", () => {
  it("wraps the placeholder in the same container and the same wrap rule", () => {
    const out = skeleton()
    expect(out).toContain("@container/week")
    expect(fourColumnCeiling(out, "h-\\[\\d+px\\]")).toBe(fourColumnCeiling(strip()))
  })

  it("budgets a taller placeholder for the two-row strip", () => {
    const out = skeleton()
    const cls = /class="([^"]*@\[900px\]\/home:@max-\[[\d.]+px\]\/week:h-\[\d+px\][^"]*)"/.exec(out)?.[1] ?? ""
    const two = /@\[900px\]\/home:@max-\[[\d.]+px\]\/week:h-\[(\d+)px\]/.exec(cls)
    const one = /(?:^| )h-\[(\d+)px\]/.exec(cls)
    expect(two, "two-row height under the same wrap rule").not.toBeNull()
    expect(one, "one-row height").not.toBeNull()
    // The wrapped strip adds a whole second row of 44px-or-taller targets.
    expect(Number(two?.[1]) - Number(one?.[1])).toBeGreaterThanOrEqual(TARGET)
  })
})
