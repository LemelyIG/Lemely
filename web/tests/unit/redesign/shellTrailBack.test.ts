import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { createStaticHandler, createStaticRouter, StaticRouterProvider } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

// `trailBack` is opt-in on the shared top bar: it must reach the phone trail through ShellTopBar and PortalShell,
// and a bar without it must render the same link it always did (teacher, parent and admin never pass it).
vi.mock("@/lib/useNativeFrame", () => ({ useNativeFrame: () => ({ native: false, platform: "web" }) }))
vi.mock("@/lib/hooks/useNotificationApi", () => ({ useNotificationCounts: () => ({ data: undefined }) }))
vi.mock("@/lib/nav/useOverlayState", () => ({ useOverlayState: () => ({}) }))
vi.mock("@/components/shell/useLargeTitleCollapse", () => ({ useLargeTitleCollapse: () => false }))
vi.mock("@/components/shell/NotificationsPanel", () => ({ NotificationsPanel: () => null }))
vi.mock("@/components/shell/AccountPanel", () => ({ AccountPanel: () => null }))
vi.mock("@/components/shell/NativeBack", () => ({ NativeBack: () => null }))

let ShellTopBar: typeof import("@/components/shell/ShellTopBar").ShellTopBar
beforeAll(async () => {
  ShellTopBar = (await import("@/components/shell/ShellTopBar")).ShellTopBar
}, 60_000)

async function render(element: ReactNode) {
  const handler = createStaticHandler([{ path: "*", element }])
  const context = await handler.query(new Request("http://localhost/x"))
  if (context instanceof Response) throw new Error("unexpected redirect")
  const router = createStaticRouter(handler.dataRoutes, context)
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: new QueryClient() }, createElement(StaticRouterProvider, { router, context })))
}

const bar = {
  title: "Past papers",
  trail: [{ label: "Practice", to: "/student/practice" }, { label: "Past papers" }],
  onOpenNav: () => {},
  navLabel: "Open student navigation",
  notifications: {} as never,
  settingsTo: "/student/settings",
  backFallback: "/student",
  account: {} as never,
  titleLevel: "detail" as const,
}
const phoneItem = (html: string) => html.match(/<li class="flex min-w-0 items-center sm:hidden">.*?<\/li>/s)?.[0] ?? ""

describe("ShellTopBar trailBack", () => {
  it("draws the phone trail control as a button with the destination's name", async () => {
    const html = await render(createElement(ShellTopBar, { ...bar, trailBack: { label: "Practice", ariaLabel: "Back to Practice", onActivate: () => {} } }))
    expect(phoneItem(html)).toMatch(/<button type="button" aria-label="Back to Practice"/)
    expect(phoneItem(html)).not.toContain("<a ")
  })
  it("keeps the parent link when trailBack is not passed", async () => {
    const html = await render(createElement(ShellTopBar, { ...bar }))
    expect(phoneItem(html)).toMatch(/<a [^>]*href="\/student\/practice"/)
    expect(phoneItem(html)).not.toContain("<button")
  })
  it("renders no trail at all for a root page, with or without trailBack", async () => {
    const root = { ...bar, trail: [{ label: "Overview" }], titleLevel: "root" as const }
    const html = await render(createElement(ShellTopBar, { ...root, trailBack: { label: "Back", onActivate: () => {} } }))
    expect(html).not.toContain('aria-label="Breadcrumb"')
  })
})
