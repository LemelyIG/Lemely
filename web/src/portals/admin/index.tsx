/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy, Suspense, useState } from "react"
import { Link, NavLink, Outlet, useLocation } from "react-router-dom"
import {
  SquaresFour,
  Armchair,
  ChalkboardTeacher,
  UsersThree,
  Gauge,
  ClipboardText,
  FlowArrow,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { NavDrawer, NavDrawerTrigger } from "@/components/ui/nav-drawer"
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

function SidebarNavItem({ item, touch = false }: { item: AdminNavItem; touch?: boolean }) {
  const Glyph = NAV_ICON[item.icon]
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
      {items.map((item) => (
        <SidebarNavItem key={item.to} item={item} touch={touch} />
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

  return (
    // `paper-grain` is DESIGN.md §8's first texture element and the cheapest
    // carrier of the one protected quality (§1). Even the utilitarian console
    // gets it: "consistent with the system" is 4.10's own instruction.
    <div data-portal="teacher" className="paper-grain flex min-h-screen">
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
          <Suspense fallback={<RouteFallback className="text-body-md" />}>
            <Outlet />
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
    { index: true, element: <SchoolDashboard /> },
    { path: "seats", element: <Seats /> },
    { path: "teachers", element: <Teachers /> },
    { path: "classes", element: <Classes /> },
    // Last, so it only matches what nothing above did. An unmatched path here
    // would otherwise fall to the top-level `*` and cost the reader the sidebar
    // (P4.10, `portals/misc/NotFound.tsx`).
    { path: "*", element: <PortalNotFound /> },
  ],
}

/** X-01…X-03. Guarded to `platform_admin` in `routes.tsx`. */
export const platformAdminRoute: RouteObject = {
  path: "platform",
  element: <AdminLayout lane="platform" />,
  children: [
    { index: true, element: <PlatformConsole /> },
    { path: "activations", element: <Activations /> },
    { path: "pipeline", element: <PipelineHealth /> },
    { path: "*", element: <PortalNotFound /> },
  ],
}
