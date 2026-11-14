import { describe, expect, it } from "vitest"
import { installNavigateMiddleware, type NavigateMiddleware } from "@/lib/nav/navigateMiddleware"

function fakeRouter() {
  const calls: unknown[][] = []
  return { calls, router: { navigate: ((to: unknown, options?: unknown): unknown => (calls.push([to, options]), "done")) } }
}
const tag =
  (name: string, log: string[]): NavigateMiddleware =>
  (to, options, next) => {
    log.push(name)
    return next(to, options)
  }

describe("installNavigateMiddleware", () => {
  it("runs one install's list in order, then the router's own navigate", () => {
    const log: string[] = []
    const { router, calls } = fakeRouter()
    installNavigateMiddleware(router, [tag("a", log), tag("b", log)])
    expect(router.navigate("/x", { replace: true })).toBe("done")
    expect(log).toEqual(["a", "b"])
    expect(calls).toEqual([["/x", { replace: true }]])
  })
  it("a later install wraps outside an earlier one, so it runs first", () => {
    const log: string[] = []
    const { router } = fakeRouter()
    installNavigateMiddleware(router, [tag("capture", log)])
    installNavigateMiddleware(router, [tag("push-default", log)])
    router.navigate("/x")
    expect(log).toEqual(["push-default", "capture"])
  })
  it("wraps the current navigate, not a saved original: a wrapper added in between stays in the chain", () => {
    const log: string[] = []
    const { router } = fakeRouter()
    installNavigateMiddleware(router, [tag("first", log)])
    const current = router.navigate as (to: unknown, o?: unknown) => unknown
    router.navigate = (to: unknown, o?: unknown) => (log.push("foreign"), current(to, o))
    installNavigateMiddleware(router, [tag("last", log)])
    router.navigate("/x")
    expect(log).toEqual(["last", "foreign", "first"])
  })
  it("lets an earlier middleware adjust the options a later one sees", () => {
    const seen: unknown[] = []
    const { router } = fakeRouter()
    const addVt: NavigateMiddleware = (to, o, next) => next(to, { ...o, viewTransition: true })
    const spy: NavigateMiddleware = (to, o, next) => (seen.push(o), next(to, o))
    installNavigateMiddleware(router, [addVt, spy])
    router.navigate("/x", { replace: false })
    expect(seen).toEqual([{ replace: false, viewTransition: true }])
  })
  it("installing the same middleware twice is a no-op", () => {
    const log: string[] = []
    const { router } = fakeRouter()
    const mw = tag("a", log)
    installNavigateMiddleware(router, [mw])
    installNavigateMiddleware(router, [mw])
    router.navigate("/x")
    expect(log).toEqual(["a"])
  })
})
