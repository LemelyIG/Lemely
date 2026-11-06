import { Suspense, useState } from "react"
import { useLocation } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { List } from "@phosphor-icons/react"
import { BadgeSync } from "@/components/badge-sync"
import { EdgeSwipeBack } from "@/components/edge-swipe-back"
import { InstallBanner } from "@/components/InstallBanner"
import { portalErrorFallback } from "@/components/route-error"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { NavDrawer } from "@/components/ui/nav-drawer"
import { BottomNav, type NavShellItem } from "@/components/ui/nav-shells"
import { OfflineBanner } from "@/components/ui/offline-banner"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { ScreenOutlet, type ScreenOverlay } from "@/components/ui/screen-outlet"
import { MAIN_CONTENT_ID, SkipLink } from "@/components/ui/skip-link"
import { VerifyEmailBanner } from "@/components/ui/verify-email-banner"
import { ShellSidebar, type ShellSidebarContent } from "./ShellSidebar"
import { ShellTopBar, type ShellTopBarProps } from "./ShellTopBar"

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
}: PortalShellProps) {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()
  const queryClient = useQueryClient()
  const closeNav = () => setNavOpen(false)
  return (
    <div data-portal={portal} className="flex min-h-dvh bg-surface-container">
      <SkipLink />
      <BadgeSync />
      <ShellSidebar variant="rail" {...sidebar} />
      <NavDrawer variant="shell" open={navOpen} onClose={closeNav} title={drawerTitle}>
        <ShellSidebar variant="drawer" {...sidebar} onClose={closeNav} />
      </NavDrawer>
      <EdgeSwipeBack />
      <div className="flex min-w-0 flex-1 flex-col">
        <ShellTopBar {...topBar} onOpenNav={() => setNavOpen(true)} />
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="@container/home w-full min-w-0 flex-1 overflow-x-hidden px-[72px] pt-1 pb-10 focus:outline-none max-shell-lg:px-3.5 max-shell-lg:pb-9 max-sidebar:pb-bottom-nav"
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
                <ScreenOutlet overlay={overlay} />
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
            onClick: () => setNavOpen(true),
          },
        ]}
        emphasisId={bottomEmphasisId}
        className="sidebar:hidden"
      />
    </div>
  )
}
