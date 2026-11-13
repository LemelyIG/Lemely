import { Suspense, useEffect, useState, type ReactNode } from "react"
import type { MouseEvent } from "react"
import { useLocation, useMatches, useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { List } from "@phosphor-icons/react"
import { BadgeSync } from "@/components/badge-sync"
import { EdgeSwipeBack } from "@/components/edge-swipe-back"
import { InstallBanner } from "@/components/InstallBanner"
import { portalErrorFallback } from "@/components/route-error"
import { installPressFeedback } from "@/lib/pressFeedback"
import { cn } from "@/lib/utils"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { NavDrawer } from "@/components/ui/nav-drawer"
import { BottomNav, type NavShellItem } from "@/components/ui/nav-shells"
import { OfflineBanner } from "@/components/ui/offline-banner"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { ScreenOutlet, type ScreenOverlay } from "@/components/ui/screen-outlet"
import { MAIN_CONTENT_ID, SkipLink } from "@/components/ui/skip-link"
import { VerifyEmailBanner } from "@/components/ui/verify-email-banner"
import { MoreSheet } from "./MoreSheet"
import { ShellPullToRefresh } from "./ShellPullToRefresh"
import { ShellSidebar, type ShellSidebarContent } from "./ShellSidebar"
import { ShellTopBar, type ShellTopBarProps } from "./ShellTopBar"
import type { NavDirectionState } from "@/lib/nav/navDirectionState"
import { activeTabTap } from "./tabTap"
import { titleLevelFor } from "./largeTitle"

export interface PortalShellProps {
  portal: "student" | "teacher"
  sidebar: ShellSidebarContent
  topBar: Omit<ShellTopBarProps, "onOpenNav">
  /** Route tabs for the phone bar; the shell appends "More", which opens the drawer. */
  bottomTabs: NavShellItem[]
  bottomEmphasisId?: string
  /** Accessible name of the drawer dialog. */
  drawerTitle: string
  /** The portal's gate query is pending: the content slot shows RouteSkeleton. */
  pending: boolean
  /** Settings-as-dialog wiring for ScreenOutlet. */
  overlay?: ScreenOverlay
  /** Android native phones: the portal's floating action button (hidden on immersive routes). */
  fab?: ReactNode
}

/**
 * The frame around every student and teacher page (design A `.as-app`): the
 * sidebar column from `shell-lg` (1248px), the same sidebar as a drawer below it, the
 * floating top bar, the page well, and the phone tab bar below the `sidebar`
 * breakpoint (approved drift: design A's own phone bar differs).
 *
 * `<main>` holds only what the route rendered, so the skip link skips the
 * navigation. One error boundary around the outlet keeps the shell painted
 * when a screen crashes; `resetKey` clears it on navigation. A pending gate
 * query shows the same RouteSkeleton a chunk load does.
 */
export function PortalShell({
  portal,
  sidebar,
  topBar,
  bottomTabs,
  bottomEmphasisId,
  drawerTitle,
  pending,
  overlay,
  fab,
}: PortalShellProps) {
  const [navOpen, setNavOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const { native } = useNativeFrame()
  // Overflow destinations for the native More sheet: the sidebar's items minus the tab bar's own.
  const tabTargets = new Set(bottomTabs.map((tab) => tab.to))
  const moreItems = sidebar.items.filter((item) => item.to && !tabTargets.has(item.to))
  useEffect(() => installPressFeedback(document), [])
  const location = useLocation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const matches = useMatches()
  const immersive = matches.some((m) => (m.handle as { immersive?: boolean } | undefined)?.immersive)
  const level = topBar.titleLevel ?? titleLevelFor(topBar.trail)
  const closeNav = () => setNavOpen(false)
  const onActiveTap = (item: NavShellItem, event: MouseEvent) => {
    if (!item.to) return
    const action = activeTabTap({ pathname: location.pathname, tabTo: item.to, scrollY: window.scrollY })
    if (action === "none") return
    event.preventDefault()
    if (action === "scroll-top") {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
      window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" })
    } else navigate(item.to, { viewTransition: true, state: { navDirection: "back" } satisfies NavDirectionState })
  }
  return (
    <div data-portal={portal} className="flex min-h-dvh bg-surface-container">
      <SkipLink />
      <BadgeSync />
      <ShellSidebar variant="rail" {...sidebar} />
      <NavDrawer variant="shell" open={navOpen} onClose={closeNav} title={drawerTitle}>
        <ShellSidebar variant="drawer" {...sidebar} onClose={closeNav} />
      </NavDrawer>
      <MoreSheet open={moreOpen && native} onClose={() => setMoreOpen(false)} items={moreItems} />
      <EdgeSwipeBack />
      <div className="flex min-w-0 flex-1 flex-col">
        <ShellTopBar {...topBar} onOpenNav={() => setNavOpen(true)} />
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          data-immersive={immersive || undefined}
          data-fab={fab && !immersive ? "" : undefined}
          className="lm-native-main @container/home w-full min-w-0 flex-1 overflow-x-hidden px-[72px] pt-1 pb-10 focus:outline-none max-shell-lg:px-3.5 max-shell-lg:pb-9 max-sidebar:pb-bottom-nav"
        >
          <OfflineBanner
            onRetry={() =>
              void queryClient.refetchQueries({ type: "active", predicate: (query) => query.state.status === "error" })
            }
          />
          <VerifyEmailBanner />
          <InstallBanner />
          {pending ? (
            <RouteSkeleton />
          ) : (
            <Suspense fallback={<RouteSkeleton />}>
              <ErrorBoundary label="This page" resetKey={location.pathname} fallback={portalErrorFallback}>
                <ShellPullToRefresh enabled={native && level === "root"}>
                  <ScreenOutlet overlay={overlay} />
                </ShellPullToRefresh>
              </ErrorBoundary>
            </Suspense>
          )}
        </main>
      </div>
      <BottomNav
        items={[
          ...bottomTabs,
          {
            id: "more",
            label: "More",
            icon: <List size={22} aria-hidden="true" />,
            // Native phones get the titled sheet; tablet and desktop keep the drawer.
            onClick: () => (native ? setMoreOpen(true) : setNavOpen(true)),
            popup: { expanded: native ? moreOpen : navOpen },
          },
        ]}
        emphasisId={bottomEmphasisId}
        // User decision (2026-11-13): re-tapping the active tab stays active wherever the tab bar shows, not gated to native.
        onActiveTap={onActiveTap}
        className={cn("sidebar:hidden", immersive && "native:hidden")}
      />
      {immersive ? null : fab}
    </div>
  )
}
