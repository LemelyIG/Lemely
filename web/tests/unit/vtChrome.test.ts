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

  it("two hops committing back to back: the first transition's end does not clear the flag the second still carries", async () => {
    const finishers: Array<() => void> = []
    let listener: (s: { location: { key: string }; matches: ReturnType<typeof page> }) => void = () => {}
    const router = {
      state: { location: { key: "a" }, matches: page() },
      subscribe(l: typeof listener) {
        listener = l
        return () => {}
      },
    }
    const root = { dataset: {} as Record<string, string | undefined> } as unknown as HTMLElement
    const host = {
      startViewTransition: () => ({ finished: new Promise<void>((res) => finishers.push(res)) }),
    }
    installVtChrome(router, root, host)
    noteRenderedMatches(page())
    // Both hops commit before either transition starts: the router's own transition starts run after.
    listener({ location: { key: "b" }, matches: page(true) })
    listener({ location: { key: "c" }, matches: page(true) })
    expect(root.dataset.vtChrome).toBe("page")
    host.startViewTransition() // the interrupted first one
    host.startViewTransition() // the one that carries the latest hop
    finishers[0]()
    await Promise.resolve()
    await Promise.resolve()
    expect(root.dataset.vtChrome).toBe("page")
    finishers[1]()
    await Promise.resolve()
    await Promise.resolve()
    expect(root.dataset.vtChrome).toBeUndefined()
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

describe("a hop that keeps the pathname plays no transition (final review I1)", () => {
  const setup = (native: boolean) => {
    type Loc = { key: string; pathname: string }
    let listener: (s: { location: Loc; matches: ReturnType<typeof page> }) => void = () => {}
    const router = {
      state: { location: { key: "a", pathname: "/p" } as Loc, matches: page() },
      subscribe(l: typeof listener) {
        listener = l
        return () => {}
      },
    }
    const root = { dataset: {} as Record<string, string | undefined> } as unknown as HTMLElement
    const skipped = vi.fn()
    const host = { startViewTransition: () => ({ finished: new Promise<void>(() => {}), skipTransition: skipped }) }
    installVtChrome(router, root, host, () => native)
    return { emit: (key: string, pathname: string) => listener({ location: { key, pathname }, matches: page() }), host, skipped }
  }

  it("skips the transition of a same-path hop (a dialog closing is a same-URL POP)", () => {
    const h = setup(true)
    h.emit("b", "/p")
    h.host.startViewTransition()
    expect(h.skipped).toHaveBeenCalledTimes(1)
  })

  it("lets a hop to another path play", () => {
    const h = setup(true)
    h.emit("b", "/q")
    h.host.startViewTransition()
    expect(h.skipped).not.toHaveBeenCalled()
  })

  it("leaves desktop and tablet alone", () => {
    const h = setup(false)
    h.emit("b", "/p")
    h.host.startViewTransition()
    expect(h.skipped).not.toHaveBeenCalled()
  })
})
