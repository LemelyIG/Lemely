import { describe, expect, it } from "vitest"
import { hopCrossesImmersive, installVtChrome, isImmersive } from "@/lib/nav/vtChrome"

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
