import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { OVERLAY_EXIT_TIMEOUT_MS, overlayPhase, type OverlayState } from "@/lib/overlayPhase"
import { stripComments } from "./support/jsxSource"

const STATES: OverlayState[] = ["closed", "open", "closing"]

const ROOT = join(import.meta.dirname, "..", "..")

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("overlayPhase", () => {
  describe("open — always wins outright, including mid-exit", () => {
    it.each(STATES)("from %s, reducedMotion=false", (state) => {
      expect(overlayPhase(state, "open", false)).toBe("open")
    })
    it.each(STATES)("from %s, reducedMotion=true", (state) => {
      expect(overlayPhase(state, "open", true)).toBe("open")
    })
  })

  describe("close", () => {
    it("from open, reducedMotion=false, starts the exit", () => {
      expect(overlayPhase("open", "close", false)).toBe("closing")
    })

    it("from open, reducedMotion=true, skips straight to closed — nothing to animate", () => {
      expect(overlayPhase("open", "close", true)).toBe("closed")
    })

    it("from closed is a no-op", () => {
      expect(overlayPhase("closed", "close", false)).toBe("closed")
      expect(overlayPhase("closed", "close", true)).toBe("closed")
    })
  })

  describe("animationend", () => {
    it("from closing, finishes the exit", () => {
      expect(overlayPhase("closing", "animationend", false)).toBe("closed")
      expect(overlayPhase("closing", "animationend", true)).toBe("closed")
    })

    it("from open or closed, a stray event changes nothing", () => {
      expect(overlayPhase("open", "animationend", false)).toBe("open")
      expect(overlayPhase("closed", "animationend", false)).toBe("closed")
    })
  })

  it("a full open -> close -> animationend cycle", () => {
    let state: OverlayState = "closed"
    state = overlayPhase(state, "open", false)
    expect(state).toBe("open")
    state = overlayPhase(state, "close", false)
    expect(state).toBe("closing")
    state = overlayPhase(state, "animationend", false)
    expect(state).toBe("closed")
  })
})

/*
 * `closing` was leavable only by a DOM `animationend`. An overlay whose exit
 * animation never reports — the panel is `display: none` by the time the
 * phase flips, the tab is backgrounded mid-exit, `motion-reduce` strips the
 * animation from under it — was stuck there forever, holding the scroll lock
 * (`document.body` pinned at `position: fixed`) with no overlay on screen to
 * explain why the page would not scroll. The timeout is the backstop.
 */
describe("the closing phase has a timeout backstop", () => {
  it("outlasts the CSS exit animation it is backing up", () => {
    const css = sourceOf("src/index.css")
    const durFast = css.match(/--dur-fast:\s*(\d+)ms/)
    expect(durFast).not.toBeNull()

    // Both exit animations (`lm-out`, `lm-slide-out-start`) run at --dur-fast.
    expect(css).toMatch(/\.lm-out\s*\{[^}]*var\(--dur-fast\)/)
    expect(css).toMatch(/\.lm-slide-out-start\s*\{[^}]*var\(--dur-fast\)/)

    expect(OVERLAY_EXIT_TIMEOUT_MS).toBeGreaterThan(Number(durFast![1]))
  })

  it("is short enough that a stuck overlay is not left on screen", () => {
    expect(OVERLAY_EXIT_TIMEOUT_MS).toBeLessThanOrEqual(1000)
  })

  it("useOverlayPhase arms the timer on the closing phase and clears it again", () => {
    const source = sourceOf("src/lib/overlayPhase.ts")
    expect(source).toContain("setTimeout")
    expect(source).toContain("clearTimeout")
    expect(source).toContain("OVERLAY_EXIT_TIMEOUT_MS")
  })
})

/*
 * `onAnimationEnd` is a React synthetic handler, so it hears animations that
 * bubble from *descendants* too. A spinner, a skeleton shimmer or a celebration
 * finishing anywhere inside a closing panel would end the exit phase early and
 * yank the panel off the page mid-slide.
 */
describe("only the panel's own animation ends the exit", () => {
  it.each(["src/components/ui/modal.tsx", "src/components/ui/nav-drawer.tsx"])(
    "%s guards onAnimationEnd on the event target",
    (relativePath) => {
      const source = sourceOf(relativePath)
      expect(source).toMatch(/event\.target\s*===\s*event\.currentTarget/)
    },
  )
})
