import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { RouteObject } from "react-router-dom"
import {
  createNativePushDefault,
  routeOptsOutOfTransitions,
  shouldDefaultToPush,
  targetPathname,
  type PushDecisionInput,
} from "@/lib/nav/nativePushDefault"
import { installNavigateMiddleware } from "@/lib/nav/navigateMiddleware"
import { exposeRouterForChecks } from "@/lib/nav/exposeRouter"
import { CAPTURE_MEASURE, dropSnapshotsFrom, isRememberedOversized, snapshotCaptureMiddleware } from "@/lib/nav/pageSnapshotCapture"

const base: PushDecisionInput = {
  to: "/student/subject/0580",
  options: undefined,
  currentPathname: "/student",
  currentState: null,
  nativeFrame: true,
  destinationOptsOut: () => false,
}
const decide = (patch: Partial<PushDecisionInput>) => shouldDefaultToPush({ ...base, ...patch })

describe("shouldDefaultToPush", () => {
  it("pushes a plain drill-down on the native frame", () => {
    expect(decide({})).toBe(true)
    expect(decide({ to: { pathname: "/student/classes", search: "?a=1" } })).toBe(true)
    expect(decide({ options: { state: { from: "x" } } })).toBe(true)
  })
  it("leaves desktop, tablet and other platforms alone", () => {
    expect(decide({ nativeFrame: false })).toBe(false)
  })
  it("never overrides an explicit choice, either way", () => {
    expect(decide({ options: { viewTransition: false } })).toBe(false)
    expect(decide({ options: { viewTransition: true } })).toBe(false)
  })
  it("skips a numeric delta and a replace", () => {
    expect(decide({ to: -1 })).toBe(false)
    expect(decide({ options: { replace: true } })).toBe(false)
  })
  it("skips a navigation that keeps the pathname", () => {
    expect(decide({ to: "?filter=open" })).toBe(false)
    expect(decide({ to: "#top" })).toBe(false)
    expect(decide({ to: "/student?x=1" })).toBe(false)
    expect(decide({ to: "/student/" })).toBe(false)
    expect(decide({ to: { search: "?x=1" } })).toBe(false)
  })
  it("skips a navigation made from inside a dialog or sheet, and the push that opens one", () => {
    expect(decide({ currentState: { lemelyDialog: true } })).toBe(false)
    expect(decide({ options: { state: { lemelyDialog: true } } })).toBe(false)
  })
  it("skips a route-backed overlay", () => {
    expect(decide({ options: { state: { backgroundLocation: { pathname: "/student" } } } })).toBe(false)
  })
  it("skips a destination whose route opts out, and checks the pathname alone", () => {
    const seen: string[] = []
    expect(decide({ to: "/x/y?q=1#h", destinationOptsOut: (p) => (seen.push(p), true) })).toBe(false)
    expect(seen).toEqual(["/x/y"])
  })
  it("treats a relative path as a change it cannot check", () => {
    expect(targetPathname("../classes", "/student/subject/1")).toBeNull()
    expect(decide({ to: "../classes" })).toBe(true)
  })
})

describe("routeOptsOutOfTransitions", () => {
  const routes: RouteObject[] = [
    { path: "/a", handle: { title: "A" } },
    { path: "/b/:id", handle: { title: "B", viewTransition: false } },
    { path: "/c", children: [{ path: "d", handle: { viewTransition: false } }] },
  ]
  it("reads handle.viewTransition from the matched leaf route", () => {
    expect(routeOptsOutOfTransitions(routes, "/a")).toBe(false)
    expect(routeOptsOutOfTransitions(routes, "/b/7")).toBe(true)
    expect(routeOptsOutOfTransitions(routes, "/c/d")).toBe(true)
    expect(routeOptsOutOfTransitions(routes, "/c")).toBe(false)
    expect(routeOptsOutOfTransitions(routes, "/nowhere")).toBe(false)
  })
})

function stubBrowser(over: { phone?: boolean; platform?: string; standalone?: boolean; state?: unknown; pathname?: string } = {}) {
  const { phone = true, platform = "ios", standalone = true, state = null, pathname = "/student" } = over
  const win = {
    location: { pathname },
    history: { state: { usr: state, idx: 3 } },
    matchMedia: (q: string) => ({ matches: q.includes("display-mode") ? standalone : phone }),
    navigator: { standalone },
    scrollY: 0,
  }
  vi.stubGlobal("window", win)
  vi.stubGlobal("document", {
    documentElement: { dataset: { platform } },
    querySelector: () => null,
  })
  return win
}
afterEach(() => vi.unstubAllGlobals())

describe("createNativePushDefault", () => {
  const router = { routes: [{ path: "/student/result/:id", handle: { viewTransition: false } }] as RouteObject[] }
  const run = (to: unknown, options?: Record<string, unknown>) => {
    const seen: unknown[] = []
    createNativePushDefault(router)(to, options, (_t, o) => void seen.push(o))
    return seen[0]
  }
  it("sets viewTransition: true for a native drill-down and keeps the other options", () => {
    stubBrowser()
    expect(run("/student/classes", { state: { a: 1 } })).toEqual({ state: { a: 1 }, viewTransition: true })
  })
  it("passes the options through untouched off the native frame", () => {
    stubBrowser({ phone: false })
    expect(run("/student/classes")).toBeUndefined()
    stubBrowser({ platform: "other" })
    expect(run("/student/classes")).toBeUndefined()
  })
  it("honours a route's opt-out and a dialog entry", () => {
    stubBrowser()
    expect(run("/student/result/9")).toBeUndefined()
    stubBrowser({ state: { lemelyDialog: true } })
    expect(run("/student/classes")).toBeUndefined()
  })
  it("still navigates when the decision throws", () => {
    vi.stubGlobal("window", undefined)
    expect(() => run("/student/classes")).not.toThrow()
  })
})

describe("the capture middleware cannot stop a navigation", () => {
  it("runs next() even when copying the page throws", () => {
    stubBrowser()
    const boom = {
      localName: "div",
      cloneNode() {
        throw new Error("copy failed")
      },
    }
    vi.stubGlobal("document", { documentElement: { dataset: { platform: "ios" } }, querySelector: () => boom })
    vi.stubGlobal("performance", { now: () => 0, getEntriesByName: () => [], measure: () => {}, clearMeasures: () => {} })
    const next = vi.fn(() => "went")
    expect(snapshotCaptureMiddleware("/x", undefined, next)).toBe("went")
    expect(next).toHaveBeenCalledWith("/x", undefined)
  })
  it("remembers a page over the cap, so the walk is not repeated, and forgets it when the index is overwritten", () => {
    stubBrowser()
    const wide = {
      localName: "div",
      childNodes: Array.from({ length: 3100 }, () => ({ nodeType: 1, localName: "p", childNodes: [], cloneNode: () => ({ removeAttribute() {}, appendChild() {} }) })),
      cloneNode: () => ({ removeAttribute() {}, appendChild() {} }),
    }
    let queries = 0
    vi.stubGlobal("document", { documentElement: { dataset: { platform: "ios" } }, querySelector: () => (queries++, wide) })
    const measures: unknown[] = []
    vi.stubGlobal("performance", { now: () => 1, getEntriesByName: () => [], measure: (n: string, o: unknown) => measures.push([n, o]), clearMeasures: () => {} })
    const next = vi.fn()
    snapshotCaptureMiddleware("/x", undefined, next)
    expect(isRememberedOversized(3)).toBe(true)
    expect(measures).toHaveLength(1)
    expect(measures[0]).toMatchObject([CAPTURE_MEASURE, { detail: { idx: 3, outcome: "oversized" } }])
    snapshotCaptureMiddleware("/x", undefined, next)
    expect(queries).toBe(1)
    expect(next).toHaveBeenCalledTimes(2)
    dropSnapshotsFrom(3)
    expect(isRememberedOversized(3)).toBe(false)
  })
})

describe("middleware order and install point", () => {
  it("the push default runs before the capture, so capture sees the final options", () => {
    stubBrowser({ state: null })
    vi.stubGlobal("document", { documentElement: { dataset: { platform: "ios" } }, querySelector: () => null })
    const seenByCapture: unknown[] = []
    const router = { routes: [] as RouteObject[], navigate: (_to: unknown, _o?: unknown) => "done" as unknown }
    const capture = (to: unknown, o: unknown, next: (t: unknown, o?: unknown) => unknown) => (seenByCapture.push(o), next(to, o))
    installNavigateMiddleware(router, [capture as never])
    installNavigateMiddleware(router, [createNativePushDefault(router)])
    router.navigate("/student/classes")
    expect(seenByCapture).toEqual([{ viewTransition: true }])
  })
  const src = (p: string) => readFileSync(resolve(__dirname, "../../src", p), "utf8")
  it("App.tsx installs both at module load, push default after the capture", () => {
    const app = src("App.tsx")
    expect(app.indexOf("[snapshotCaptureMiddleware]")).toBeGreaterThan(-1)
    expect(app.indexOf("createNativePushDefault(router)")).toBeGreaterThan(app.indexOf("[snapshotCaptureMiddleware]"))
  })
  it("navigateMiddleware.ts documents the module-load rule", () => {
    expect(src("lib/nav/navigateMiddleware.ts")).toMatch(/INSTALL AT MODULE LOAD[\s\S]*useSubmit/)
  })
})

describe("exposeRouterForChecks", () => {
  it("exposes only in dev or under the drift flag", () => {
    const router = { navigate: () => {} }
    const prod: Record<string, unknown> = {}
    vi.stubEnv("DEV", false)
    expect(exposeRouterForChecks(router, prod)).toBe(false)
    expect(prod.__lemelyRouter).toBeUndefined()
    const flagged: Record<string, unknown> = { __LEMELY_DRIFT__: true }
    expect(exposeRouterForChecks(router, flagged)).toBe(true)
    expect(flagged.__lemelyRouter).toBe(router)
    vi.stubEnv("DEV", true)
    const dev: Record<string, unknown> = {}
    expect(exposeRouterForChecks(router, dev)).toBe(true)
    vi.unstubAllEnvs()
  })
})
