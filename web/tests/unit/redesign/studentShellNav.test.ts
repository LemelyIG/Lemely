import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { createStaticHandler, createStaticRouter, StaticRouterProvider } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

// Renders the real StudentShell with PortalShell swapped for a probe that draws the real sidebar and captures
// the props the student shell hands down, so deleting an `isRoot` wiring or doubling a `page` goes red.
const captured: { props?: Record<string, any> } = {}
vi.mock("@/components/shell/PortalShell", async () => {
  const { createElement: h } = await import("react")
  const { ShellSidebar } = await import("@/components/shell/ShellSidebar")
  return {
    PortalShell: (props: Record<string, any>) => {
      captured.props = props
      return h(ShellSidebar, { variant: "rail", ...props.sidebar })
    },
  }
})
vi.mock("@/lib/hooks/useStudentApi", () => ({
  useOverview: () => ({ isPending: false, data: { subjects: [{ code: "0580", name: "Mathematics", grade: null, pct: 0 }] } }),
}))
vi.mock("@/lib/hooks/useMeApi", () => ({
  useProfile: () => ({ isPending: false, data: undefined }),
  useStudentProfile: () => ({ isPending: false, data: undefined }),
}))
vi.mock("@/lib/hooks/useReferenceApi", () => ({ useReference: () => ({ data: undefined }) }))

let StudentShell: typeof import("@/portals/student/shell").StudentShell
beforeAll(async () => {
  StudentShell = (await import("@/portals/student/shell")).StudentShell
}, 60_000)

async function render(path: string): Promise<string> {
  const element: ReactNode = createElement(StudentShell, { pending: false, prefetchCorrectPaper: {} as never })
  const handler = createStaticHandler([{ path: "*", element }])
  const context = await handler.query(new Request(`http://localhost${path}`))
  if (context instanceof Response) throw new Error("redirect")
  const router = createStaticRouter(handler.dataRoutes, context)
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: new QueryClient() }, createElement(StaticRouterProvider, { router, context })),
  )
}
const count = (html: string, value: string) => (html.match(new RegExp(`aria-current="${value}"`, "g")) ?? []).length

describe("student sidebar announces exactly one current page", () => {
  for (const path of ["/student/flashcards/0580", "/student/practice/0580", "/student/plan/0580", "/student"]) {
    it(path, async () => {
      const html = await render(path)
      expect(count(html, "page"), path).toBe(1)
    })
  }
  it("the section row is still marked (aria-current=true) beside the exact subject row", async () => {
    expect(count(await render("/student/flashcards/0580"), "true")).toBe(1)
  })
})

describe("student shell isRoot wiring", () => {
  it("Practice and Plan tabs carry isRoot, the others do not", async () => {
    await render("/student")
    const tabs = captured.props!.bottomTabs as { id: string; isRoot?: (p: string) => boolean }[]
    for (const id of ["practice", "plan"]) expect(tabs.find((t) => t.id === id)?.isRoot?.("/student/" + id + "/0580"), id).toBe(true)
    for (const id of ["home", "scan", "me"]) expect(tabs.find((t) => t.id === id)?.isRoot, id).toBeUndefined()
  })
  it("the top bar title level is root on a subject page and detail below it", async () => {
    for (const [path, level] of [
      ["/student/practice/0580", "root"],
      ["/student/plan/0580", "root"],
      ["/student/practice/set/a1", "detail"],
      ["/student/plan/0580/session/s1", "detail"],
    ] as const) {
      await render(path)
      expect(captured.props!.topBar.titleLevel, path).toBe(level)
    }
  })
})
