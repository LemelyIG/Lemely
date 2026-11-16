import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { createStaticHandler, createStaticRouter, StaticRouterProvider } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

// Behavioural wiring tests: render the real shell and read the markup, so deleting a prop pass-through goes red
// (the source-regex tests in studentShellScan.test.ts stay green on a deleted `phoneMenu={phoneMenu}`).
vi.mock("@/lib/useNativeFrame", () => ({ useNativeFrame: () => ({ native: false, platform: "web" }) }))
vi.mock("@/lib/hooks/useNotificationApi", () => ({ useNotificationCounts: () => ({ data: undefined }) }))
vi.mock("@/lib/nav/useOverlayState", () => ({ useOverlayState: () => ({}) }))
vi.mock("@/components/shell/useLargeTitleCollapse", () => ({ useLargeTitleCollapse: () => false }))
vi.mock("@/components/shell/NotificationsPanel", () => ({ NotificationsPanel: () => null }))
vi.mock("@/components/shell/AccountPanel", () => ({ AccountPanel: () => null }))
vi.mock("@/components/shell/NativeBack", () => ({ NativeBack: () => null }))
vi.mock("@/components/badge-sync", () => ({ BadgeSync: () => null }))
vi.mock("@/components/edge-swipe-back", () => ({ EdgeSwipeBack: () => null }))
vi.mock("@/components/InstallBanner", () => ({ InstallBanner: () => null }))
vi.mock("@/components/ui/offline-banner", () => ({ OfflineBanner: () => null }))
vi.mock("@/components/ui/verify-email-banner", () => ({ VerifyEmailBanner: () => null }))
vi.mock("@/components/ui/screen-outlet", () => ({ ScreenOutlet: () => null }))
vi.mock("@/components/shell/ShellSidebar", () => ({ ShellSidebar: () => null }))
vi.mock("@/components/shell/MoreSheet", () => ({ MoreSheet: () => null }))
vi.mock("@/components/shell/ShellPullToRefresh", () => ({ ShellPullToRefresh: () => null }))
vi.mock("@/components/ui/nav-drawer", () => ({ NavDrawer: () => null }))

type Mods = {
  PortalShell: typeof import("@/components/shell/PortalShell").PortalShell
  ShellTopBar: typeof import("@/components/shell/ShellTopBar").ShellTopBar
}
let mods: Mods
beforeAll(async () => {
  mods = {
    PortalShell: (await import("@/components/shell/PortalShell")).PortalShell,
    ShellTopBar: (await import("@/components/shell/ShellTopBar")).ShellTopBar,
  }
})

async function renderWithRouter(element: ReactNode, path = "/student") {
  const routes = [{ path: "*", element }]
  const handler = createStaticHandler(routes)
  const context = await handler.query(new Request(`http://localhost${path}`))
  if (context instanceof Response) throw new Error("unexpected redirect")
  const router = createStaticRouter(handler.dataRoutes, context)
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: new QueryClient() }, createElement(StaticRouterProvider, { router, context })),
  )
}

const barProps = {
  title: "Home",
  trail: [],
  onOpenNav: () => {},
  navLabel: "Open student navigation",
  notifications: {} as never,
  settingsTo: "/student/settings",
  backFallback: "/student",
  account: {} as never,
}
const menuButton = (html: string) => html.match(/<button[^>]*aria-label="Open student navigation"[^>]*>/)?.[0] ?? ""

describe("ShellTopBar menu button", () => {
  it("shows on phones when phoneMenu is set, hidden below the shell-sm breakpoint otherwise", async () => {
    const on = await renderWithRouter(createElement(mods.ShellTopBar, { ...barProps, phoneMenu: true }))
    const off = await renderWithRouter(createElement(mods.ShellTopBar, { ...barProps }))
    expect(menuButton(on)).not.toBe("")
    expect(menuButton(on)).not.toContain("max-shell-sm:hidden")
    expect(menuButton(off)).toContain("max-shell-sm:hidden")
  })
})

describe("PortalShell passes phoneMenu and moreTab through", () => {
  const shellProps = {
    portal: "student" as const,
    sidebar: { navLabel: "Main", homeTo: "/student", homeLabel: "Lemely", items: [], user: null } as never,
    topBar: { ...barProps, onOpenNav: undefined } as never,
    bottomTabs: [{ id: "home", to: "/student", end: true, label: "Home", icon: createElement("svg") }],
    drawerTitle: "Lemely",
    pending: false,
  }
  it("phoneMenu reaches the bar's menu button", async () => {
    const on = await renderWithRouter(createElement(mods.PortalShell, { ...shellProps, phoneMenu: true }))
    const off = await renderWithRouter(createElement(mods.PortalShell, { ...shellProps }))
    expect(menuButton(on)).not.toBe("")
    expect(menuButton(on)).not.toContain("max-shell-sm:hidden")
    expect(menuButton(off)).toContain("max-shell-sm:hidden")
  })
  it("moreTab appends the More cell by default and omits it when false", async () => {
    const withMore = await renderWithRouter(createElement(mods.PortalShell, { ...shellProps }))
    const without = await renderWithRouter(createElement(mods.PortalShell, { ...shellProps, moreTab: false }))
    expect(withMore).toMatch(/<button[^>]*>.*?More<\/span>/s)
    expect(without).not.toMatch(/>More</)
  })
})
