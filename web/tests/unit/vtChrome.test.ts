import { describe, expect, it } from "vitest"
import { afterEach, vi } from "vitest"
import { hopCrossesImmersive, installVtChrome, isImmersive, noteRenderedMatches } from "@/lib/nav/vtChrome"

const page = (immersive?: boolean) => [{ route: { handle: immersive ? { immersive: true } : {} } }, { route: {} }]

describe("vtChrome", () => {
  it("finds an immersive route anywhere in the match chain", () => {
    expect(isImmersive(page(true))).toBe(true)
    expect(isImmersive(page())).toBe(false)
  })

  it("flags only a hop that enters or leaves one", () => {
    expect(hopCrossesImmersive(page(), page(true))).toBe(true)
    expect(hopCrossesImmersive(page(true), page())).toBe(true)
    expect(hopCrossesImmersive(page(), page())).toBe(false)
    expect(hopCrossesImmersive(page(true), page(true))).toBe(false)
  })

  it("sets the root attribute on a location change, clears it on the next, and ignores re-publishes", () => {
    let listener: (s: { location: { key: string }; matches: ReturnType<typeof page> }) => void = () => {}
    const router = {
      state: { location: { key: "a" }, matches: page() },
      subscribe(l: typeof listener) {
        listener = l
        return () => {}
      },
    }
    const root = { dataset: {} as Record<string, string | undefined> } as unknown as HTMLElement
    installVtChrome(router, root)
    listener({ location: { key: "b" }, matches: page(true) })
    expect(root.dataset.vtChrome).toBe("page")
    // A loading or fetcher update on the same location must not clear it mid-transition.
    listener({ location: { key: "b" }, matches: page(true) })
    expect(root.dataset.vtChrome).toBe("page")
    // A POP back out of the immersive route is a hop too.
    listener({ location: { key: "a" }, matches: page() })
    expect(root.dataset.vtChrome).toBe("page")
    listener({ location: { key: "c" }, matches: page() })
    expect(root.dataset.vtChrome).toBeUndefined()
  })
})

describe("vtChrome lifetime and the interrupted hop (polish B, item 17)", () => {
  afterEach(() => vi.useRealTimers())

  const harness = () => {
    let listener: (s: { location: { key: string }; matches: ReturnType<typeof page> }) => void = () => {}
    const router = {
      state: { location: { key: "a" }, matches: page() },
      subscribe(l: typeof listener) {
        listener = l
        return () => {}
      },
    }
    const root = { dataset: {} as Record<string, string | undefined> } as unknown as HTMLElement
    let finish: () => void = () => {}
    const finished = new Promise<void>((res) => (finish = res))
    const host = { startViewTransition: () => ({ finished }) }
    const wrapperless = host.startViewTransition
    installVtChrome(router, root, host)
    return { router, root, host, emit: (key: string, matches: ReturnType<typeof page>) => listener({ location: { key }, matches }), finish, wrapperless }
  }

  it("clears the attribute when the view transition it was set for finishes", async () => {
    const h = harness()
    noteRenderedMatches(page())
    h.emit("b", page(true))
    expect(h.root.dataset.vtChrome).toBe("page")
    h.host.startViewTransition()
    expect(h.root.dataset.vtChrome).toBe("page")
    h.finish()
    await Promise.resolve()
    await Promise.resolve()
    expect(h.root.dataset.vtChrome).toBeUndefined()
  })

  it("an old transition ending does not clear the attribute a newer hop set", async () => {
    const h = harness()
    noteRenderedMatches(page())
    h.emit("b", page(true))
    h.host.startViewTransition()
    noteRenderedMatches(page(true))
    h.emit("c", page())
    expect(h.root.dataset.vtChrome).toBe("page")
    h.finish()
    await Promise.resolve()
    await Promise.resolve()
    expect(h.root.dataset.vtChrome).toBe("page")
  })

  it("clears on its own when no view transition ever claims it", () => {
    vi.useFakeTimers()
    const h = harness()
    noteRenderedMatches(page())
    h.emit("b", page(true))
    vi.advanceTimersByTime(3100)
    expect(h.root.dataset.vtChrome).toBeUndefined()
  })

  it("compares a hop against what is rendered, not the last committed state", () => {
    const h = harness()
    // The DOM still shows a plain page; hop B (immersive) was committed but not painted, then hop C
    // (plain again) interrupts it. Against the painted page, C crosses nothing.
    noteRenderedMatches(page())
    h.emit("b", page(true))
    expect(h.root.dataset.vtChrome).toBe("page")
    h.emit("c", page())
    expect(h.root.dataset.vtChrome).toBeUndefined()
  })
})
