/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { Fragment, lazy, Suspense, useState } from "react"
import { Link, NavLink, Outlet, useLocation } from "react-router-dom"
import {
  SquaresFour,
  Armchair,
  Buildings,
  ChalkboardTeacher,
  UsersThree,
  Gauge,
  ClipboardText,
  FlowArrow,
  type Icon,
} from "@phosphor-icons/react"
import { useQueryClient } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { portalErrorFallback } from "@/components/route-error"
import { NavDrawer, NavDrawerTrigger } from "@/components/ui/nav-drawer"
import { OfflineBanner } from "@/components/ui/offline-banner"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { RouteFallback } from "@/components/ui/state-views"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { useProfile } from "@/lib/hooks/useMeApi"
import {
  platformNavItems,
  resolveAdminTrail,
  schoolNavItems,
  type AdminLane,
  type AdminNavItem,
} from "./data"

/*
 * The two admin lanes (P4.7, D1.6: "fully build the required screens and
 * completely wire them"). One shell, two route subtrees, each guarded to a
 * single role in `routes.tsx`.
 *
 * `data-portal="teacher"` on the layout root is deliberate and is the one thing
 * in this file worth arguing about. DESIGN.md gives each portal an accent, and
 * the admin lanes are new. Minting a fifth accent for them would say these
 * screens are a different *product*; they are not. They are the staff side of
 * the same one, at a different altitude, and UI spec 4.10's own note for the
 * platform console is "utilitarian, function over polish, but consistent with
 * the system". Sharing the teacher palette is that consistency, and it is also
 * literally true for a school admin, who moves between `/school` and `/teacher`
 * inside one session.
 */

const SchoolDashboard = lazy(() =>
  import("./screens/SchoolDashboard").then((m) => ({ default: m.SchoolDashboard })),
)
const Seats = lazy(() => import("./screens/Seats").then((m) => ({ default: m.Seats })))
const Teachers = lazy(() => import("./screens/Teachers").then((m) => ({ default: m.Teachers })))
const Classes = lazy(() => import("./screens/Classes").then((m) => ({ default: m.Classes })))
const PlatformConsole = lazy(() =>
  import("./screens/PlatformConsole").then((m) => ({ default: m.PlatformConsole })),
)
const Activations = lazy(() =>
  import("./screens/Activations").then((m) => ({ default: m.Activations })),
)
const PipelineHealth = lazy(() =>
  import("./screens/PipelineHealth").then((m) => ({ default: m.PipelineHealth })),
)
const Schools = lazy(() => import("./screens/Schools").then((m) => ({ default: m.Schools })))

const NAV_ICON: Record<AdminNavItem["icon"], Icon> = {
  dashboard: SquaresFour,
  // A seat is a chair. The glyph is the literal object the quota counts, which
  // is clearer here than an abstract "capacity" meter would be.
  seats: Armchair,
  teachers: ChalkboardTeacher,
  classes: UsersThree,
  console: Gauge,
  activations: ClipboardText,
  pipeline: FlowArrow,
}

function SidebarNavItem({
  item,
  glyph: Glyph,
  touch = false,
}: {
  // Deliberately narrower than `AdminNavItem`: this component no longer knows
  // about the `icon` union itself (see `AdminNav` below for why), so it takes
  // the resolved icon component directly instead of a key to look one up.
  item: { to: string; label: string; end?: boolean }
  glyph: Icon
  touch?: boolean
}) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          // Symmetric padding has no direction, so this row needs no logical
          // rewrite (P3.4).
          // `pointer-coarse:min-h-11` is §6.1's 44px floor. The row measured
          // 32px, and the same row in the student portal was raised while this
          // one and the teacher's were not — the standing rule that a defect
          // fixed on one surface is usually live on another. Safe as a min
          // here: the row is already `flex items-center`, so the label centres
          // in the taller box instead of sitting at its top.
          "flex items-center gap-2.5 w-full text-start text-label px-[9px] py-2 pointer-coarse:min-h-11 rounded-md",
          "transition-colors duration-[var(--dur-instant)] ease-out-soft",
          // `focus-ring`, not `accent`: §3.9 keeps focus deliberately blue so it
          // stays distinguishable from the accent the active row already uses.
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
          // The active rule is reserved at every state, transparent when
          // inactive, so turning it on cannot nudge the label sideways.
          "border-s-2",
          touch && "min-h-11",
          isActive
            ? "border-accent bg-paper-raised text-ink"
            : "border-transparent bg-transparent text-ink-muted hover:bg-paper hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          <Glyph
            size={16}
            weight={isActive ? "fill" : "regular"}
            className={cn("shrink-0", isActive ? "text-accent" : "text-ink-faint")}
            aria-hidden="true"
          />
          <span className="flex-1">{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

/**
 * Sidebar identity block. `GET /api/me/profile`, same as the teacher portal's.
 *
 * The role line matters more here than it does there. These two lanes look
 * alike and an administrator may hold an account on either, so the subtitle is
 * the one place the screen says which kind of administrator is signed in.
 */
function UserBlock() {
  const { data, isPending, isError } = useProfile()

  if (isPending || isError || !data) {
    return (
      <div className="flex items-center gap-2.5 px-0.5 text-body-sm text-ink-faint">
        {isPending ? "Loading…" : "Signed in"}
      </div>
    )
  }

  const name = data.displayName ?? data.email.split("@")[0]
  const roleLabel = data.role
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")

  return (
    <div className="flex items-center gap-2.5">
      <Avatar name={name} size="sm" />
      <div className="min-w-0">
        <div className="truncate text-body-sm font-medium text-ink">{name}</div>
        <div className="text-body-sm text-ink-faint">{roleLabel}</div>
      </div>
    </div>
  )
}

/**
 * Nav list, shared by the desktop aside and the mobile drawer.
 *
 * One list rendered twice, never two lists: navigation that exists at one width
 * and not another is the defect P3.1 fixed portal-wide, and a second copy is
 * how it comes back.
 */
function AdminNav({ lane, touch = false }: { lane: AdminLane; touch?: boolean }) {
  const items = lane === "school" ? schoolNavItems : platformNavItems
  return (
    <nav
      aria-label={lane === "school" ? "School admin sections" : "Platform admin sections"}
      className="flex flex-col gap-0.5"
    >
      {items.map((item, index) => (
        <Fragment key={item.to}>
          <SidebarNavItem item={item} glyph={NAV_ICON[item.icon]} touch={touch} />
          {/* Task 22 (D7.8): `/platform/schools` is registered on
              `platformAdminRoute` below, in this same file. Its nav entry is
              injected here instead of living in `platformNavItems`
              (`./data.ts`) because that file sits outside this task's file
              allowlist while other agents are editing the surfaces it
              describes. Placed right after the dashboard entry — "look at the
              console, then go provision a school" is the same "look, then
              provision" ordering `schoolNavItems` already uses for its own
              lane (Dashboard, then Seats). `resolveAdminTrail` in data.ts does
              not know this path either, so the mobile breadcrumb falls back to
              its own documented behaviour for an unmatched path (the lane
              root alone, no second crumb) rather than showing a wrong one —
              a disclosed gap, not a silent one; see Task 22's report. */}
          {lane === "platform" && index === 0 ? (
            <SidebarNavItem
              item={{ to: "/platform/schools", label: "Schools" }}
              glyph={Buildings}
              touch={touch}
            />
          ) : null}
        </Fragment>
      ))}
    </nav>
  )
}

/**
 * Account link, plus — for a school admin only — the way into the teacher
 * portal.
 *
 * That cross-link is not a convenience, it is the honest half of this surface.
 * A school admin holds the teacher API's roles for their own school, so
 * `/teacher` genuinely works for them: it is where marking review, class
 * analytics and school-wide announcements live, and none of those are rebuilt
 * here. Leaving it out would have quietly *removed* working capability in the
 * name of giving them a home screen.
 *
 * A platform admin gets no such link, because for them `/teacher` is guarded
 * shut and every panel behind it would be empty by design (see `./data.ts`).
 */
function SidebarFooter({ lane }: { lane: AdminLane }) {
  return (
    <div className="flex flex-col gap-3">
      {lane === "school" ? (
        /* P6.1: both of these were one long sentence inside a ~219px sidebar,
           so the clickable text always broke across two lines — the thing §6
           bans outright, and measured here at every width from 320 to 768. The
           label is now one line and the detail is a second line inside the same
           link, so the whole block stays one target and nothing that reads as
           part of the link is untappable. Shortening the sentence instead would
           have cost a school admin the only statement of what is behind a
           destination they have never visited. */
        <Link
          to="/teacher"
          className="flex flex-col justify-center gap-0.5 rounded-sm px-0.5 pointer-coarse:min-h-11 text-body-sm text-ink-faint transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <span className="whitespace-nowrap">Teaching tools &rarr;</span>
          <span className="text-body-sm text-ink-faint">
            Marking, review, announcements
          </span>
        </Link>
      ) : null}
      <Link
        to="/settings/devices"
        className="flex flex-col justify-center gap-0.5 rounded-sm px-0.5 pointer-coarse:min-h-11 text-body-sm text-ink-faint transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        <span className="whitespace-nowrap">Your account &rarr;</span>
        <span className="text-body-sm text-ink-faint">Devices and notifications</span>
      </Link>
      <UserBlock />
    </div>
  )
}

/*
 * `alt=""` and `aria-hidden`: the wordmark beside it already says "Lemely", so
 * describing the mark too makes a screen reader announce the brand twice.
 *
 * The lane name sits under the wordmark rather than replacing it. An
 * administrator needs to know which console they are in — the two look alike
 * and the nav lists are short — but they are still in Lemely, and a sidebar
 * that says only "Platform" reads like a different application.
 */
function BrandLockup({ lane }: { lane: AdminLane }) {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
      <div className="min-w-0">
        <div className="text-display-sm text-ink">Lemely</div>
        <div className="text-eyebrow text-ink-faint">
          {lane === "school" ? "School admin" : "Platform admin"}
        </div>
      </div>
    </div>
  )
}

function Sidebar({ lane }: { lane: AdminLane }) {
  return (
    // A well, per DESIGN.md §3.1: `--paper-sunk`'s stated use is "sidebars,
    // table headers, code blocks, inset areas".
    <aside className="hidden md:flex w-[252px] flex-none bg-paper-sunk border-e border-rule px-4 py-[22px] flex-col gap-[26px] sticky top-0 h-screen">
      <BrandLockup lane={lane} />

      <div className="lm-scroll min-h-0 flex-1 overflow-y-auto">
        <AdminNav lane={lane} />
      </div>

      <div className="mt-auto border-t border-rule pt-[14px]">
        <SidebarFooter lane={lane} />
      </div>
    </aside>
  )
}

/**
 * Mobile chrome (below `md`, where the aside does not exist): the menu trigger
 * and the breadcrumb trail on one sticky row.
 *
 * The bar is mobile-only because above `md` the sidebar carries the mark and
 * the menu button has nothing to open. The trail itself renders at every width.
 */
function AdminTopBar({ lane, onOpenNav }: { lane: AdminLane; onOpenNav: () => void }) {
  const location = useLocation()
  const trail = resolveAdminTrail(location.pathname, lane)

  return (
    <div className="sticky top-0 z-nav flex min-h-14 items-center gap-3 border-b border-rule bg-paper/80 px-page-mobile py-2.5 backdrop-blur-nav md:px-page-desktop">
      <NavDrawerTrigger
        onClick={onOpenNav}
        label={lane === "school" ? "Open school admin navigation" : "Open platform navigation"}
        className="-ms-2 md:hidden"
      />
      {/* One crumb means the trail is just the page's own name, which the page
          heading already says. Rendering nothing beats repeating the <h1>. */}
      {trail.length > 1 ? <Breadcrumbs items={trail} /> : null}
    </div>
  )
}

function AdminLayout({ lane }: { lane: AdminLane }) {
  const [navOpen, setNavOpen] = useState(false)
  // Only read here for `ErrorBoundary`'s `resetKey` below — `AdminTopBar`
  // calls `useLocation()` independently for its own breadcrumb trail.
  const location = useLocation()
  const queryClient = useQueryClient()

  return (
    // `paper-grain` is DESIGN.md §8's first texture element and the cheapest
    // carrier of the one protected quality (§1). Even the utilitarian console
    // gets it: "consistent with the system" is 4.10's own instruction.
    // `bg-paper`: the shell owns its own ground rather than depending on
    // `body`'s paint showing through beneath the fixed grain overlay.
    <div data-portal="teacher" className="paper-grain flex min-h-screen bg-paper">
      <SkipLink />
      <Sidebar lane={lane} />

      <NavDrawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title="Lemely"
        footer={<SidebarFooter lane={lane} />}
      >
        <AdminNav lane={lane} touch />
      </NavDrawer>

      <div className="flex-1 min-w-0 flex flex-col">
        <AdminTopBar lane={lane} onOpenNav={() => setNavOpen(true)} />
        {/* `<main>` is the content area only, not the whole column: the skip
            link's target must not contain the navigation it skips. */}
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="flex-1 min-w-0 overflow-x-hidden w-full max-w-app px-page-mobile py-6 md:px-page-tablet lg:px-page-desktop lg:py-8 focus:outline-none"
        >
          {/* PR 2 part C: offline recovery banner, above the Suspense/
              ErrorBoundary content it sits over — it renders nothing while
              online, so its own `mb-6` is the only spacing this adds. */}
          <OfflineBanner
            onRetry={() =>
              void queryClient.refetchQueries({
                type: "active",
                predicate: (query) => query.state.status === "error",
              })
            }
          />
          <Suspense fallback={<RouteFallback className="text-body-md" />}>
            {/* PR 1B fulfils `routes.tsx`'s note ("Phase 4 places those as it
                rebuilds each surface") for both admin lanes: a render crash
                in one screen stays inside this content slot rather than
                taking the sidebar down with it or falling out to the
                top-level `errorElement`. Inside `Suspense` so a failed chunk
                load and a render throw both land in this boundary.
                `resetKey={location.pathname}` clears a caught error on
                navigation. */}
            <ErrorBoundary
              label="This page"
              resetKey={location.pathname}
              fallback={portalErrorFallback}
            >
              <Outlet />
            </ErrorBoundary>
          </Suspense>
        </main>
      </div>
    </div>
  )
}

/** K-01…K-04. Guarded to `school_admin` in `routes.tsx`. */
export const schoolAdminRoute: RouteObject = {
  path: "school",
  element: <AdminLayout lane="school" />,
  children: [
    // P6.5 · `handle.title` on every child. See `lib/meta/documentMeta.ts`.
    // Both admin lanes prefix their titles ("School ..." / "Platform ..."),
    // because a school_admin holds BOTH this portal and the teacher one and
    // would otherwise have two tabs reading "Classes" that are different
    // screens over different data.
    { index: true, element: <SchoolDashboard />, handle: { title: "School overview" } },
    { path: "seats", element: <Seats />, handle: { title: "School seats" } },
    { path: "teachers", element: <Teachers />, handle: { title: "School teachers" } },
    { path: "classes", element: <Classes />, handle: { title: "School classes" } },
    // Last, so it only matches what nothing above did. An unmatched path here
    // would otherwise fall to the top-level `*` and cost the reader the sidebar
    // (P4.10, `portals/misc/NotFound.tsx`).
    { path: "*", element: <PortalNotFound />, handle: { title: "Page not found" } },
  ],
}

/** X-01…X-03. Guarded to `platform_admin` in `routes.tsx`. */
export const platformAdminRoute: RouteObject = {
  path: "platform",
  element: <AdminLayout lane="platform" />,
  children: [
    { index: true, element: <PlatformConsole />, handle: { title: "Platform console" } },
    // Task 22 (D7.8): the account graph's missing first link (spec §1.1) —
    // before this route existed, no production code path created a `School`
    // row or a `school_admin` account. Guarded by inheriting the same
    // `RequireAuth allowedRoles={PLATFORM_ADMIN_ROLES}` that `routes.tsx`
    // already wraps around `platformAdminRoute.element`: that wrap is around
    // the layout `<Outlet />` renders every child of this array into, so a
    // new entry here needs no guard of its own, and `web/tests/unit/
    // adminRoutes.test.ts` pins that this stays true in both directions
    // (platform_admin reaches it; the other four roles do not).
    { path: "schools", element: <Schools />, handle: { title: "Platform schools" } },
    { path: "activations", element: <Activations />, handle: { title: "Platform activations" } },
    { path: "pipeline", element: <PipelineHealth />, handle: { title: "Pipeline health" } },
    { path: "*", element: <PortalNotFound />, handle: { title: "Page not found" } },
  ],
}
