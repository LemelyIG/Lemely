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
    for (const sel of ["[data-swiping]", "[data-swipe-settling", "::view-transition-old(root)"]) {
      expect(section.split(sel).length, sel).toBe(gated.split(sel).length)
    }
  })

  it("the swipe rules also require an iOS or Android platform", () => {
    const rules = gated.match(/html[^{}]*\[data-swiping\][^{}]*\{/g) ?? []
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

describe("a committed swipe continues the gesture (fix round 2, I-1)", () => {
  const component = read("components/edge-swipe-back.tsx")
  const hook = read("lib/gestures/useDragGesture.ts")
  const css = read("index.css")

  it("the hook can leave the transform at the release offset and hands over the velocity", () => {
    expect(hook).toContain("keepTransformOnCommit")
    expect(hook).toMatch(/onCommit\(dx, dy, velocity\)/)
  })

  it("the component opts in, so release never clears the column before the slide off", () => {
    expect(component).toContain("keepTransformOnCommit: true")
  })

  it("the column goes to the far edge on the iOS curve over a velocity-scaled, token-clamped time", () => {
    expect(component).toContain("swipeSettleMs")
    expect(component).toContain('"--dur-fast"')
    expect(component).toContain('"--dur-sheet-ios"')
    expect(component).toContain("translateX(${dir * 100}%)")
    expect(component).toContain("var(--ease-ios-spring)")
  })

  it("reduced motion skips the slide (zero duration) and the in-frame commit never navigates with a view transition", () => {
    expect(component).toContain("prefers-reduced-motion: reduce")
    expect(component).toContain("viewTransition: !inFrame")
  })

  it("the column comes back only once the new location is committed", () => {
    expect(component).toMatch(/useLayoutEffect\([\s\S]*?committingRef\.current\) resetColumn\(\)[\s\S]*?\[location\.key\]/)
  })

  it("the dim and shadow are registered numbers that transition on the column's duration and curve", () => {
    expect(css).toContain("@property --lm-swipe-progress")
    expect(css).toContain("@property --lm-swipe-shadow")
    expect(css).toMatch(/\[data-swipe-settling\][^{]*\{\s*transition:[^}]*--lm-swipe-progress var\(--lm-swipe-dur, var\(--dur-base\)\) var\(--ease-ios-spring\)/)
    expect(css).toMatch(/\[data-swipe-settling="cancel"\][^{]*\{\s*--lm-swipe-shadow: 0/)
  })
})

describe("swipe cancel (fix round 2, M-3 and M-5)", () => {
  const component = read("components/edge-swipe-back.tsx")
  const hook = read("lib/gestures/useDragGesture.ts")

  it("spring-back takes a per-caller easing; the default keeps the drawer, quiz and flashcards on the overshoot", () => {
    expect(hook).toContain("springEasing")
    expect(hook).toContain('?? "var(--ease-spring)"')
    for (const rel of ["components/ui/nav-drawer.tsx", "components/quiz/QuizTaker.tsx", "portals/student/screens/flashcards/FlashcardReview.tsx"])
      expect(read(rel), rel).not.toContain("springEasing")
  })

  it("swipe-back springs on the iOS curve, with no overshoot", () => {
    expect(component).toContain('springEasing: "var(--ease-ios-spring)"')
  })

  it("the swipe state clears when the spring-back finishes, not when it starts", () => {
    expect(hook).toContain("onSettled")
    expect(component).toMatch(/onSettled: \(\) => \{[\s\S]*?clearSwipeState\(\)/)
    const cancel = component.slice(component.indexOf("onCancel:"), component.indexOf("onSettled:"))
    expect(cancel).not.toContain("clearSwipeState")
  })
})

describe("outside the native frame a swipe plays the back slide (fix round 2, M-4)", () => {
  const css = read("index.css")
  it("maps data-direction=swipe to the back keyframes, ungated", () => {
    expect(css).toMatch(/html\[data-direction="swipe"\]::view-transition-old\(root\) \{\s*animation-name: lm-vt-old-back/)
    expect(css).toMatch(/html\[data-direction="swipe"\]::view-transition-new\(root\) \{\s*animation-name: lm-vt-new-back/)
  })
})

describe("one animation per committed hop (fix round 3)", () => {
  const css = read("index.css")
  const gated = mediaBlockAfter(css, "/* ── Native frame: swipe-back")

  it("inside the native frame, direction=swipe silences both view-transition snapshots", () => {
    expect(gated).toMatch(
      /\[data-direction="swipe"\]::view-transition-group\(root\),\s*html:is\(\[data-platform="ios"\], \[data-platform="android"\]\)\[data-direction="swipe"\]::view-transition-old\(root\),\s*html:is\(\[data-platform="ios"\], \[data-platform="android"\]\)\[data-direction="swipe"\]::view-transition-new\(root\) \{\s*animation: none/,
    )
    expect(gated).toContain('html:is([data-platform="ios"], [data-platform="android"])[data-direction="swipe"]')
  })

  it("the back mapping stays ungated, for outside the frame", () => {
    const ungated = css.replace(gated, "")
    expect(ungated).toMatch(/html\[data-direction="swipe"\]::view-transition-old\(root\) \{\s*animation-name: lm-vt-old-back/)
  })
})

describe("a committed swipe is cancellable and locks input (fix round 3)", () => {
  const component = read("components/edge-swipe-back.tsx")
  const css = read("index.css")

  it("keeps the navigation timer in a ref, clears it on reset and unmount, and skips a stale go", () => {
    expect(component).toContain("goTimerRef")
    const reset = component.slice(component.indexOf("function resetColumn"), component.indexOf("function releaseDim"))
    expect(reset).toContain("clearTimeout(goTimerRef.current)")
    expect(component).toContain("useEffect(() => resetColumn, [])")
    expect(component).toMatch(/const go = \(\) => \{[\s\S]*?if \(!committingRef\.current\) return/)
  })

  it("go() also stands down for a navigation that has started but not committed, read from the router synchronously", () => {
    expect(component).toContain("UNSAFE_DataRouterContext")
    expect(component).toMatch(/router\.state\.navigation\.state !== "idle" \|\| router\.state\.location\.key !== startKey/)
  })

  it("navigates when the front-loaded curve is nearly done, not after the full duration", () => {
    expect(component).toContain("NAVIGATE_AT_FRACTION = 0.65")
    expect(component).toContain("setTimeout(go, ms * NAVIGATE_AT_FRACTION)")
  })

  it("locks pointer input on the body while the commit settles", () => {
    expect(css).toMatch(/\[data-swipe-settling="commit"\] body \{\s*pointer-events: none/)
    expect(component).toContain('root.setAttribute("data-swipe-settling", "commit")')
  })

  it("slow releases run on the iOS sheet duration; flings keep the fast floor", () => {
    expect(component).toContain('"--dur-sheet-ios"')
    expect(component).toContain('minMs: durationToken("--dur-fast", 150)')
  })

  it("the guard drops the dim but never hands the old page back at x=0", () => {
    const release = component.slice(component.indexOf("function releaseDim"), component.indexOf("// The new page is in the DOM"))
    expect(release).toContain("clearSwipeState()")
    expect(release).not.toContain("transform")
    expect(component).toContain("setTimeout(releaseDim, COMMIT_GUARD_MS)")
  })
})
