import { describe, expect, it, vi } from "vitest"
import { lockScroll, type ScrollLockTarget } from "@/lib/scrollLock"

/*
 * Packet B2a · `lockScroll` replaces `document.body.style.overflow = "hidden"`
 * in `modal.tsx`/`nav-drawer.tsx` — that approach lets the page underneath
 * jump to the top on iOS Safari once background scroll is (imperfectly)
 * blocked. `lockScroll` pins the body at its current scroll offset instead,
 * and restores it exactly on release.
 *
 * Reference-counted: a drawer opened underneath a modal (or vice versa) must
 * not have the second overlay's release call unlock scrolling for the first
 * one still open — see the "ref-count 2" test below.
 *
 * Run against an injected target rather than the real `window`/`document` so
 * this pure logic runs under vitest's Node environment (D3.20, no jsdom).
 */

function fakeTarget(scrollY = 120): ScrollLockTarget & { scrollTo: ReturnType<typeof vi.fn> } {
  const scrollTo = vi.fn<(x: number, y: number) => void>()
  return {
    body: { style: { position: "", top: "", insetInline: "", width: "" } },
    scrollY,
    scrollTo,
  }
}

describe("lockScroll", () => {
  it("pins the body at the current scroll offset", () => {
    const target = fakeTarget(250)
    const release = lockScroll(target)

    expect(target.body.style.position).toBe("fixed")
    expect(target.body.style.top).toBe("-250px")
    expect(target.body.style.insetInline).toBe("0")
    expect(target.body.style.width).toBe("100%")

    release()
  })

  it("restores the previous style and scrolls back to the saved offset on release", () => {
    const target = fakeTarget(80)
    target.body.style.position = "static"
    const release = lockScroll(target)

    release()

    expect(target.body.style.position).toBe("static")
    expect(target.scrollTo).toHaveBeenCalledWith(0, 80)
  })

  it("ref-counts: releasing one of two overlapping locks keeps the lock active", () => {
    const target = fakeTarget(60)
    const releaseA = lockScroll(target)
    const releaseB = lockScroll(target)

    releaseA()
    expect(target.body.style.position).toBe("fixed")
    expect(target.scrollTo).not.toHaveBeenCalled()

    releaseB()
    expect(target.scrollTo).toHaveBeenCalledWith(0, 60)
  })

  it("releasing the same release function twice restores only once", () => {
    const target = fakeTarget(10)
    const release = lockScroll(target)

    release()
    release()

    expect(target.scrollTo).toHaveBeenCalledTimes(1)
  })
})
