import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { consumeSwipeNav, edgeSwipeDecision, markSwipeNav } from "@/lib/nav/edgeSwipeBack"

/*
 * Packet B3 (Task 4) · edge-swipe-back is standalone-only (a browser tab
 * keeps the URL bar's own back gesture) and only commits from the
 * inline-start 24px edge, so a drag starting mid-screen (e.g. dismissing a
 * drawer, paging a quiz) is never mistaken for it.
 */

const BASE = { startX: 12, dx: 40, dy: 0, viewportWidth: 375, standalone: true, dir: 1 as const }

describe("edgeSwipeDecision", () => {
  it("is none in a browser tab even from the edge with a committing drag", () => {
    expect(edgeSwipeDecision({ ...BASE, standalone: false })).toBe("none")
  })

  it("is back for a standalone drag committing from the inline-start edge", () => {
    expect(edgeSwipeDecision(BASE)).toBe("back")
  })

  it("is none when the drag starts past the 24px edge zone", () => {
    expect(edgeSwipeDecision({ ...BASE, startX: 30 })).toBe("none")
  })

  it("is back for an RTL drag from the inline-start edge (viewport's right side)", () => {
    expect(
      edgeSwipeDecision({
        startX: 365,
        dx: -40,
        dy: 0,
        viewportWidth: 375,
        standalone: true,
        dir: -1,
      }),
    ).toBe("back")
  })

  it("is none when the drag moves toward the edge instead of away from it", () => {
    expect(edgeSwipeDecision({ ...BASE, dx: -40 })).toBe("none")
  })

  it("is none when the drag doesn't move away from the edge at all (dx: 0)", () => {
    expect(edgeSwipeDecision({ ...BASE, dx: 0 })).toBe("none")
  })

  it("is none exactly at the 24px edge boundary's far side", () => {
    expect(edgeSwipeDecision({ ...BASE, startX: 25 })).toBe("none")
  })
})

describe("the swipe navigation flag is one-shot (Task 12)", () => {
  it("consumes once, then reads false", () => {
    expect(consumeSwipeNav()).toBe(false)
    markSwipeNav()
    expect(consumeSwipeNav()).toBe(true)
    expect(consumeSwipeNav()).toBe(false)
  })
})

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (rel: string): string => readFileSync(join(SRC, rel), "utf8")

/** The text of the first `@media (max-width: 720px) { ... }` block after `marker` (brace-matched). */
function mediaBlockAfter(css: string, marker: string): string {
  const from = css.indexOf(marker)
  const open = css.indexOf("@media (max-width: 720px) {", from)
  let depth = 0
  for (let i = css.indexOf("{", open); i < css.length; i++) {
    if (css[i] === "{") depth++
    if (css[i] === "}" && --depth === 0) return css.slice(open, i + 1)
  }
  return ""
}

describe("swipe-back CSS stays inside the native frame (fix round 1)", () => {
  const css = read("index.css")
  const start = css.indexOf("/* ── Native frame: swipe-back")
  const end = css.indexOf("/* Exit phase for a dismissible overlay")
  const section = css.slice(start, end)
  const gated = mediaBlockAfter(css, "/* ── Native frame: swipe-back")

  it("every swipe rule is wrapped in the phone media query", () => {
    expect(gated).not.toBe("")
    for (const sel of ["[data-swiping]", '[data-direction="swipe"]', "::view-transition-old(root)"]) {
      expect(section.split(sel).length, sel).toBe(gated.split(sel).length)
    }
  })

  it("the swipe rules also require an iOS or Android platform", () => {
    const rules = gated.match(/html[^{}]*\[data-(?:swiping|direction="swipe")\][^{}]*\{/g) ?? []
    expect(rules.length).toBeGreaterThan(0)
    for (const rule of rules) expect(rule).toContain('[data-platform="ios"], [data-platform="android"]')
  })

  it("has no dead `[dir=rtl] html` selector", () => {
    expect(section).not.toMatch(/\[dir="rtl"\]\s+html/)
  })
})

describe("swipe-back release lives in the drag hook (fix round 1)", () => {
  const component = read("components/edge-swipe-back.tsx")
  const hook = read("lib/gestures/useDragGesture.ts")

  it("the component keeps no private spring-back or velocity sampling", () => {
    expect(component).not.toContain("springColumnBack")
    expect(component).not.toContain("samplesRef")
    expect(component).toContain("release:")
  })

  it("the hook measures velocity with sheetMath's windowed helper", () => {
    expect(hook).toContain("releaseVelocity")
    expect(hook).toContain("trimSamples")
  })

  it("keeps pinch-zoom while claiming the horizontal axis", () => {
    expect(component).toContain('touchAction: "pan-y pinch-zoom"')
  })

  it("the hook only reacts to its own target's transitionend", () => {
    expect(hook).toContain("event.target === event.currentTarget")
  })

  it("the root outlet re-reads the swipe flag on every navigation", () => {
    const outlet = read("components/root-outlet.tsx")
    expect(outlet).toContain("useLocation")
    expect(outlet).toMatch(/\[navigationType, key\]/)
  })
})
