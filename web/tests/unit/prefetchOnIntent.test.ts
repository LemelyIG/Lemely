import { describe, expect, it, vi } from "vitest"

import { prefetchOnIntent } from "@/lib/prefetchOnIntent"

/*
 * Task 11 (B6c) — `prefetchOnIntent` backs the CorrectPaper chunk prefetch
 * wired onto the Header CTA and the BottomNav "Correct" tab
 * (`portals/student/index.tsx`). Both call sites share one
 * `prefetchOnIntent(loadCorrectPaper)` result, so `load` must fire at most
 * once total across every handler and every call to it — not once per
 * handler — or hovering the CTA and then focusing the tab would kick off
 * the dynamic import twice.
 */

describe("prefetchOnIntent", () => {
  it("fires load once when the same handler is called repeatedly", () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const { onPointerEnter } = prefetchOnIntent(load)
    onPointerEnter()
    onPointerEnter()
    onPointerEnter()
    expect(load).toHaveBeenCalledTimes(1)
  })

  it("fires load once across the three different handlers", () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const { onPointerEnter, onTouchStart, onFocus } = prefetchOnIntent(load)
    onPointerEnter()
    onTouchStart()
    onFocus()
    expect(load).toHaveBeenCalledTimes(1)
  })

  it("fires load on the very first call, whichever handler is used", () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const { onTouchStart } = prefetchOnIntent(load)
    onTouchStart()
    expect(load).toHaveBeenCalledTimes(1)
  })

  it("returns three independent handler functions", () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const handlers = prefetchOnIntent(load)
    expect(typeof handlers.onPointerEnter).toBe("function")
    expect(typeof handlers.onTouchStart).toBe("function")
    expect(typeof handlers.onFocus).toBe("function")
  })

  it("a second, independent prefetchOnIntent call gets its own fire-once state", () => {
    const loadA = vi.fn().mockResolvedValue(undefined)
    const loadB = vi.fn().mockResolvedValue(undefined)
    const a = prefetchOnIntent(loadA)
    const b = prefetchOnIntent(loadB)
    a.onFocus()
    expect(loadA).toHaveBeenCalledTimes(1)
    expect(loadB).not.toHaveBeenCalled()
    b.onFocus()
    expect(loadB).toHaveBeenCalledTimes(1)
  })
})
