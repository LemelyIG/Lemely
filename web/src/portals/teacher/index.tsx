/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy, Suspense, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { OfflineBanner } from "@/components/ui/offline-banner"
import { VerifyEmailBanner } from "@/components/ui/verify-email-banner"
import { InstallBanner } from "@/components/InstallBanner"
import { BadgeSync } from "@/components/badge-sync"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { ScreenOutlet } from "@/components/ui/screen-outlet"
import { Link, NavLink, useLocation } from "react-router-dom"
import {
  SquaresFour,
  FileText,
  SealQuestion,
  ChartBar,
  Warning,
  Books,
  Sparkle,
  Bell,
  Megaphone,
  Gear,
  List,
  Trash,
  Plus,
  UploadSimple,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { portalErrorFallback } from "@/components/route-error"
import { NavDrawer, NavDrawerTrigger } from "@/components/ui/nav-drawer"
import { BottomNav, SidebarNav, type NavShellItem } from "@/components/ui/nav-shells"
import { EdgeSwipeBack } from "@/components/edge-swipe-back"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"
import { useReviewQueueCount } from "@/lib/hooks/useReviewQueueCount"
import { unreadBadgeLabel } from "@/lib/staffInbox"
import { navItems, resolveTrail, classesItemActive, type NavItem } from "./data"
import { ForwardArrow } from "@/components/ui/inline-arrow"

// P6.1b: screens are `React.lazy`, not static imports — see the same note in
// `portals/student/index.tsx`. QuizBuilder and ClassAnalytics in particular
// are heavy screens that most teacher sessions (grading, review) never open;
// they no longer ride along in the bundle every route pays for. Named
// exports (not default), hence the `.then((m) => ({ default: m.X }))` shape.
const Overview = lazy(() => import("./home/TeacherHome").then((m) => ({ default: m.TeacherHome })))
const Grading = lazy(() => import("./screens/Grading").then((m) => ({ default: m.Grading })))
const RecentlyDeleted = lazy(() =>
  import("./screens/RecentlyDeleted").then((m) => ({ default: m.RecentlyDeleted })),
)
const Review = lazy(() => import("./screens/Review").then((m) => ({ default: m.Review })))
const ReviewItem = lazy(() => import("./screens/ReviewItem").then((m) => ({ default: m.ReviewItem })))
const Classes = lazy(() => import("./screens/Classes").then((m) => ({ default: m.Classes })))
const ClassDetailLayout = lazy(() =>
  import("./screens/ClassDetail").then((m) => ({ default: m.ClassDetailLayout })),
)
const ClassRoster = lazy(() => import("./screens/ClassRoster").then((m) => ({ default: m.ClassRoster })))
const ClassAnalytics = lazy(() =>
  import("./screens/ClassAnalytics").then((m) => ({ default: m.ClassAnalytics })),
)
const ClassPapers = lazy(() =>
  import("./screens/ClassPapers").then((m) => ({ default: m.ClassPapers })),
)
// D7.10 / Task 21 — the create-first-class step the teacher setup screen
// (`home/TeacherSetup`) links to. Lazy for the same reason as every
// other screen here (P6.1b): most sessions, most of the time, never mount it.
const CreateFirstClass = lazy(() =>
  import("./screens/CreateFirstClass").then((m) => ({ default: m.CreateFirstClass })),
)
const StudentDetail = lazy(() =>
  import("./screens/StudentDetail").then((m) => ({ default: m.StudentDetail })),
)
const AtRiskList = lazy(() => import("./screens/AtRiskList").then((m) => ({ default: m.AtRiskList })))
const MarkSchemes = lazy(() => import("./screens/MarkSchemes").then((m) => ({ default: m.MarkSchemes })))
const Quizzes = lazy(() => import("./screens/Quizzes").then((m) => ({ default: m.Quizzes })))
const QuizBuilder = lazy(() => import("./screens/QuizBuilder").then((m) => ({ default: m.QuizBuilder })))
const QuizResults = lazy(() => import("./screens/QuizResults").then((m) => ({ default: m.QuizResults })))
const Announcements = lazy(() =>
  import("./screens/Announcements").then((m) => ({ default: m.Announcements })),
)
const TeacherNotifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.TeacherNotifications })),
)
// Settings' three screens now mount here too, alongside every other lazy
// screen in this portal, rather than only reaching the top-level
// `/settings/*` lane from a footer link — see `data.ts`'s `navItems` and the
// route registration below.
// Each imported from its own module rather than the `@/portals/settings`
// barrel: importing all four through one barrel module means a chunk
// containing any one of them pulls in the code for all four, defeating the
// per-screen splitting this whole file otherwise does. The barrel still
// exists for other consumers (its own header explains why) — this portal
// just does not use it for the lazy boundary.
const PortalSettingsLayout = lazy(() =>
  import("@/portals/settings/PortalSettingsLayout").then((m) => ({
    default: m.PortalSettingsLayout,
  })),
)
const ProfileSettingsSection = lazy(() =>
  import("@/portals/settings/ProfileSettings").then((m) => ({
    default: m.ProfileSettingsSection,
  })),
)
const DeviceSettingsSection = lazy(() =>
  import("@/portals/settings/DeviceSettings").then((m) => ({ default: m.DeviceSettingsSection })),
)
const NotificationSettingsSection = lazy(() =>
  import("@/portals/settings/NotificationSettings").then((m) => ({
    default: m.NotificationSettingsSection,
  })),
)
const InstallSettingsSection = lazy(() =>
  import("@/portals/settings/InstallSettings").then((m) => ({
    default: m.InstallSettingsSection,
  })),
)

const SIDEBAR_PRIMARY: NavItem["icon"][] = ["overview", "grading", "review", "classes", "atRisk"]
const SIDEBAR_TOOLS: NavItem["icon"][] = ["schemes", "quizzes", "announcements", "deleted"]

const NAV_ICON: Record<NavItem["icon"], Icon> = {
  overview: SquaresFour,
  grading: FileText,
  // The review queue holds the marks the system was not confident enough to
  // apply on its own, so the glyph is a seal with a question in it rather than
  // a checklist: what is waiting here is doubt, not tasks.
  review: SealQuestion,
  classes: ChartBar,
  atRisk: Warning,
  schemes: Books,
  quizzes: Sparkle,
  announcements: Megaphone,
  notifications: Bell,
  settings: Gear,
  deleted: Trash,
}

/*
 * Packet B3 (Task 4): rows now render through the shared `SidebarNav`
 * primitive (`TeacherNav` below) rather than this file's own copy of the
 * active-row/focus-ring/touch-floor styling — the same retrofit the admin
 * portal took. `unread` is resolved here (not inside `NavShellItem.badge`,
 * which is a plain `string | number`) and passed down as the notifications
 * row's own badge value.
 */
function toNavShellItem(
  item: NavItem,
  options: { forceActive?: boolean; badge?: string | number; urgent?: boolean } = {},
): NavShellItem {
  const Glyph = NAV_ICON[item.icon]
  return {
    id: item.to,
    to: item.to,
    end: item.end,
    label: item.label,
    icon: <Glyph size={16} aria-hidden="true" />,
    active: options.forceActive,
    badge: options.badge,
    urgent: options.urgent,
  }
}

/**
 * Sidebar "Your classes" list. Wired to `GET /teacher/classes`
 * (`useTeacherClasses()`) — replaces the mock's 3 hardcoded classes
 * (`recentClasses` in `./data.ts`, one of them fake-flagged "active" with no
 * real "current class" concept anywhere in the app to back it). Capped at 5
 * with a link to the full list rather than an unbounded sidebar.
 */
function ClassesNavSection() {
  const { data, isPending, isError } = useTeacherClasses()

  return (
    <div>
      <div className="text-eyebrow text-on-surface-variant px-2.5 pb-[9px]">Your classes</div>
      <div className="flex flex-col gap-px">
        {isPending ? (
          <div className="px-2.5 py-[7px] text-body-sm text-on-surface-variant">Loading…</div>
        ) : isError ? (
          <div className="px-2.5 py-[7px] text-body-sm text-on-surface-variant">Couldn't load classes.</div>
        ) : data.classes.length === 0 ? (
          <Link
            to="/teacher/classes"
            className="px-2.5 py-[7px] pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-on-primary-container hover:underline rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Add your first class <ForwardArrow />
          </Link>
        ) : (
          <>
            {data.classes.slice(0, 5).map((c) => (
              // A `NavLink`, not a plain `Link`: this row is a navigation
              // destination like any other in the sidebar, so it tells a
              // teacher which class they are looking at. No `end` — the
              // default (non-exact) match is deliberate, since this row must
              // also read as current on the class's `/analytics` child.
              //
              // No grade chip: `ClassSummary` carries `average` (a percentage)
              // and no grade, and a grade is not something to invent here. The
              // trailing figure is the real `studentCount`.
              <NavLink
                key={c.id}
                to={`/teacher/classes/${c.id}`}
                // §6.1's 44px floor on coarse pointers.
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-chip px-2.5 py-1.5 pointer-coarse:min-h-11 text-[14px] font-semibold transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                    isActive
                      ? "bg-primary-container text-primary"
                      : "text-on-surface hover:bg-surface-container",
                  )
                }
              >
                <span className="truncate">{c.label}</span>
                <span className="ml-auto flex-none text-data-sm text-on-surface-variant">{c.studentCount}</span>
              </NavLink>
            ))}
            {data.classes.length > 5 ? (
              <Link
                to="/teacher/classes"
                className="px-2.5 py-[7px] pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-on-surface-variant transition-colors hover:text-on-surface rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                See all {data.classes.length} <ForwardArrow />
              </Link>
            ) : null}
          </>
        )}
      </div>
    </div>
  )
}

/**
 * Sidebar identity block. Wired to `GET /api/me/profile` (`useProfile()`) —
 * replaces the mock's hardcoded "Mr H. Sabry / Physics dept · CAIE", which no
 * field anywhere supplies. `displayName` is nullable (a caller who never set
 * one); the fallback is the email's local part, never a fabricated name. The
 * subtitle is the caller's real platform role — the only affiliation-like
 * fact this account actually carries, not an invented department/exam board.
 *
 * The squircle comes from the kit's `<Avatar>` rather than a local circle: see
 * the note on the deleted `portals/teacher/components/Avatar.tsx` in the phase
 * report. DESIGN.md §6 reserves circles for status dots so a dot never reads
 * as a person.
 */
function UserBlock() {
  const { data, isPending, isError } = useProfile()

  if (isPending || isError || !data) {
    return (
      <div className="flex items-center gap-2.5 px-0.5 text-body-sm text-on-surface-variant">
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
      <Avatar name={name} src={data.avatarUrl ?? undefined} size="sm" />
      <div className="min-w-0">
        <div className="truncate text-body-sm font-medium text-on-surface">{name}</div>
        <div className="text-body-sm text-on-surface-variant">{roleLabel}</div>
      </div>
    </div>
  )
}

/**
 * Nav list + "Your classes", with no chrome. Shared by the desktop aside and
 * the mobile drawer for the same reason as the student portal's `NavGroups`:
 * the defect P3.1 fixes is navigation that exists at one width and not
 * another, and two copies of the list is how that comes back.
 */
function TeacherNav() {
  const location = useLocation()
  // Same query `ClassesNavSection` below subscribes to — react-query dedupes
  // by queryKey, so this adds no second request, only a second subscriber to
  // the classes list already in flight (or cached).
  const { data } = useTeacherClasses()
  const visibleClassIds = data?.classes.slice(0, 5).map((c) => c.id) ?? []
  // Same query `BadgeSync` (the app badge) already subscribes to — no second
  // request, only a second subscriber to the one query.
  const { data: counts } = useNotificationCounts()
  const unread = unreadBadgeLabel(counts) ?? undefined
  // Task 9 (C3d): the sidebar's own subscriber to `useReviewQueueCount` —
  // `BottomNav`'s Review tab below subscribes to the same hook, so the two
  // badges share one deduped `limit: 1` request (see that hook's own doc
  // comment on why).
  const reviewQueueCount = useReviewQueueCount()
  const reviewBadge = reviewQueueCount && reviewQueueCount > 0 ? reviewQueueCount : undefined

  const toShell = (item: NavItem) =>
    toNavShellItem(item, {
      forceActive:
        item.to === "/teacher/classes"
          ? classesItemActive(location.pathname, visibleClassIds)
          : undefined,
      badge:
        item.badge === "unread-notifications"
          ? unread
          : item.badge === "review-queue"
            ? reviewBadge
            : undefined,
      urgent: item.badge === "review-queue",
    })

  // Notifications and Settings live in the top bar (icon buttons), so the
  // sidebar carries the work sections and the tools.
  const primaryItems = navItems.filter((i) => SIDEBAR_PRIMARY.includes(i.icon)).map(toShell)
  const toolItems = navItems.filter((i) => SIDEBAR_TOOLS.includes(i.icon)).map(toShell)

  return (
    <div className="flex flex-col gap-[18px]">
      <SidebarNav variant="abyss" aria-label="Teacher sections" items={primaryItems} />
      <ClassesNavSection />
      <SidebarNav variant="abyss" aria-label="Teacher tools" groups={[{ label: "Tools", items: toolItems }]} />
    </div>
  )
}

/**
 * Account link + identity. Also shared between aside and drawer.
 *
 * P3.1 removed the "Open the student portal →" link that used to sit between
 * these two. It could not work for anyone: `RequireAuth` gates `/student` to
 * the `student` role alone, so a teacher, school_admin or platform_admin
 * following it was redirected straight back to `/teacher`. Its twin in the
 * student sidebar pointed the other way and failed the same way. Both are
 * build-era conveniences from before the guard existed.
 */
function SidebarFooter() {
  return (
    <div className="flex flex-col gap-3">
      <Link
        to="/teacher/grading"
        className="inline-flex h-9 w-full items-center justify-center gap-[7px] rounded-chip bg-primary px-3.5 text-[14px] font-bold text-on-primary transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        <UploadSimple size={16} aria-hidden="true" />
        Upload papers
      </Link>
      <UserBlock />
    </div>
  )
}

function Sidebar() {
  return (
    // A well, per DESIGN.md §3.1: `--paper-sunk` is the token whose stated use
    // is "sidebars, table headers, code blocks, inset areas".
    <aside className="hidden sidebar:flex w-sidebar flex-none bg-surface-container-lowest border-e border-outline-variant px-3 pb-3 pt-[18px] flex-col gap-4 sticky top-0 h-screen">
      <BrandLockup className="px-2" />

      <div className="lm-scroll min-h-0 flex-1 overflow-y-auto">
        <TeacherNav />
      </div>

      <div className="mt-auto border-t border-outline-variant pt-4">
        <SidebarFooter />
      </div>
    </aside>
  )
}

// One boundary around the Outlet (not per-route): sidebar and chrome stay
// mounted and interactive while a screen chunk loads. Fallback is the shared
// `RouteFallback` (C-11 state-view family); see the student portal for the
// reasoning, and `state-views.tsx` for why it is not a full `StateView`.

/**
 * Mobile chrome (below `md`, where the aside does not exist): the menu trigger
 * and the breadcrumb trail on one sticky row.
 *
 * The trail renders at every width, not just here — it is the D1.5 back
 * affordance, and a drilled-into screen like `/teacher/students/:id` needs a
 * route back on a laptop too. The *bar* is mobile-only because above `md` the
 * sidebar already carries the logo and the menu button has nothing to open.
 */
const TOP_BAR_ICON_BUTTON =
  "relative flex h-9 w-9 flex-none items-center justify-center rounded-chip text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:h-11 pointer-coarse:w-11"

function TeacherTopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const location = useLocation()
  const trail = resolveTrail(location.pathname)
  const title = trail[trail.length - 1]?.label ?? "Overview"
  const { data: counts } = useNotificationCounts()
  const unread = unreadBadgeLabel(counts)

  return (
    <>
      {/* `z-nav`: the bar holds the only navigation that exists below the
          `sidebar` breakpoint, so it belongs on the nav layer with the
          sidebar (DESIGN.md §7). Side margins are 16px on mobile, 28px from
          `md`; the page well below carries its own 72px at `lg`. */}
      <div className="lm-app-header lm-nav-chrome sticky top-2 z-nav mx-4 mb-6 mt-2 flex h-14 items-center gap-2 rounded-inner bg-surface-container-lowest pe-3 ps-3 ring-1 ring-outline-variant shadow-[var(--shadow-float)] md:mx-7 md:ps-[18px]">
        <NavDrawerTrigger
          onClick={onOpenNav}
          label="Open teacher navigation"
          className="-ms-1 sidebar:hidden"
        />
        <p className="min-w-0 truncate text-[19px] font-extrabold leading-none tracking-[-0.04em] text-on-surface">
          {title}
        </p>
        <div className="flex-1" />
        <Link
          to="/teacher/first-class"
          className="inline-flex h-9 flex-none items-center gap-[7px] rounded-chip bg-secondary-container px-3 text-[14px] font-bold text-on-secondary-container transition-colors hover:bg-secondary-container/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:px-3.5 pointer-coarse:h-11"
        >
          <Plus size={16} aria-hidden="true" />
          <span className="hidden sm:inline">Create</span>
          <span className="sr-only sm:hidden">Create a class</span>
        </Link>
        <Link
          to="/teacher/grading"
          className="me-2.5 inline-flex h-9 flex-none items-center gap-[7px] rounded-chip bg-primary px-3 text-[14px] font-bold text-on-primary transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:px-3.5 pointer-coarse:h-11"
        >
          <UploadSimple size={16} aria-hidden="true" />
          <span className="hidden sm:inline">Upload papers</span>
          <span className="sr-only sm:hidden">Upload papers</span>
        </Link>
        <Link
          to="/teacher/notifications"
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          className={TOP_BAR_ICON_BUTTON}
        >
          <Bell size={20} aria-hidden="true" />
          {unread ? (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-pill bg-primary px-1 text-metadata leading-none text-on-primary">
              {unread}
            </span>
          ) : null}
        </Link>
        <Link to="/teacher/settings" aria-label="Settings" className={cn(TOP_BAR_ICON_BUTTON, "hidden sm:flex")}>
          <Gear size={20} aria-hidden="true" />
        </Link>
      </div>
      {/* The D1.5 back affordance: one crumb is just the page's own name, which
          the title already says, so the trail renders only when drilled in. */}
      {trail.length > 1 ? (
        <div className="-mt-3 mb-4 px-4 md:px-7 lg:px-[72px]">
          <Breadcrumbs items={trail} />
        </div>
      ) : null}
    </>
  )
}

/** The four route-backed BottomNav tabs, exported so `navigation.test.ts` can
 * assert each `to` resolves to a mounted route without rendering the shell.
 * Labels declared in tab order ("Overview", "Grading", "Review", "Classes")
 * ahead of `TeacherLayout`'s own "More" so `navShells.test.ts`'s ordered
 * regex over the stripped source sees all five labels in the same order the
 * bar renders them. */
export const TEACHER_BOTTOM_TABS: readonly {
  id: string
  label: string
  to: string
  end?: boolean
  icon: Icon
}[] = [
  { id: "overview", label: "Overview", to: "/teacher", end: true, icon: SquaresFour },
  { id: "grading", label: "Grading", to: "/teacher/grading", icon: FileText },
  { id: "review", label: "Review", to: "/teacher/review", icon: SealQuestion },
  { id: "classes", label: "Classes", to: "/teacher/classes", icon: ChartBar },
]

function TeacherLayout() {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()
  const queryClient = useQueryClient()

  /*
   * Reads the same query
   * `ClassesNavSection` already subscribes to (`useTeacherClasses()`,
   * `GET /teacher/classes`) — react-query dedupes by queryKey
   * (`["teacher", "classes"]`), so this adds no second network request, only
   * a second subscriber to the one already in flight.
   *
   * A pending query used to render the shared route fallback in place of the
   * whole shell — sidebar and all — rather than the shell with a fallback
   * inside it. Packet B1 corrects that the same way it does for the student
   * portal: the shell renders regardless, with `<RouteSkeleton />` standing
   * in for the content below. A zero-class teacher is no longer redirected:
   * the home route shows the setup screen instead.
   */
  const classesQuery = useTeacherClasses()
  // Task 9 (C3d): shares its cache/request with `TeacherNav`'s own
  // `useReviewQueueCount()` subscriber (same query key) — mounting both the
  // desktop sidebar and this bottom bar costs one network request, not two.
  const reviewQueueCount = useReviewQueueCount()

  return (
    // `bg-surface`: the shell owns its own ground rather than depending on
    // `body`'s paint showing through.
    <div data-portal="teacher" className="flex min-h-dvh bg-surface">
      <SkipLink />
      {/* Task 7 (B5a): see student/index.tsx's own comment on this line —
          same reason, same shape. */}
      <BadgeSync />
      <Sidebar />

      <NavDrawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title="Lemely"
        footer={<SidebarFooter />}
      >
        <TeacherNav />
      </NavDrawer>

      {/* Packet B3 (Task 4): standalone-only, renders nothing — see the
          component's own doc comment. */}
      <EdgeSwipeBack />

      <div className="flex-1 min-w-0 flex flex-col">
        <TeacherTopBar onOpenNav={() => setNavOpen(true)} />
        {/* `<main>` is the content area only, not the whole column: the skip
            link's target must not contain the navigation it skips.
            `pb-bottom-nav`/`sidebar:pb-8`: clearance for the fixed
            `BottomNav` below the `sidebar` breakpoint, an ordinary bottom
            gutter once it is gone. */}
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="flex-1 min-w-0 overflow-x-hidden w-full max-w-app px-page-mobile pt-2 pb-bottom-nav sidebar:pb-8 md:px-page-tablet lg:px-[72px] focus:outline-none"
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
          {/* Below the offline strip on purpose: connectivity is the transient,
              self-healing message and belongs on top, while this is a standing fact
              about the account. Renders nothing, and no margin either, unless the
              profile has resolved and says the address is unverified. */}
          <VerifyEmailBanner />
          {/* Packet A7: same "renders nothing unless there's something to
              say" shape as the two banners above. Student and teacher only —
              see the component's own header for why. */}
          <InstallBanner />
          {/* Packet B1: the classes-query pending state renders the same
              `RouteSkeleton` a chunk-load wait does, in the same content
              slot, rather than blanking the shell below `TeacherTopBar` —
              see the comment above `classesQuery` for why this is safe to
              gate on here rather than bailing out of the whole layout. */}
          {classesQuery.isPending ? (
            <RouteSkeleton />
          ) : (
            <Suspense fallback={<RouteSkeleton />}>
              {/* PR 1B fulfils `routes.tsx`'s note ("Phase 4 places those as it
                  rebuilds each surface") for this portal: a render crash in one
                  screen stays inside this content slot rather than taking the
                  sidebar down with it or falling out to the top-level
                  `errorElement`. Inside `Suspense` so a failed chunk load and a
                  render throw both land in this boundary.
                  `resetKey={location.pathname}` clears a caught error on
                  navigation. */}
              <ErrorBoundary
                label="This page"
                resetKey={location.pathname}
                fallback={portalErrorFallback}
              >
                <ScreenOutlet />
              </ErrorBoundary>
            </Suspense>
          )}
        </main>
      </div>

      {/* Below the `sidebar` breakpoint, the primary navigation — same
          shape as the student portal's own BottomNav, see that file's
          comment on the identical mount. The Review tab's badge (Task 9,
          C3d) is `reviewQueueCount` above. */}
      <BottomNav
        items={[
          ...TEACHER_BOTTOM_TABS.map(
            (tab): NavShellItem => ({
              id: tab.id,
              to: tab.to,
              end: tab.end,
              label: tab.label,
              icon: <tab.icon size={22} aria-hidden="true" />,
              badge:
                tab.id === "review" && reviewQueueCount && reviewQueueCount > 0
                  ? reviewQueueCount
                  : undefined,
            }),
          ),
          {
            id: "more",
            label: "More",
            icon: <List size={22} aria-hidden="true" />,
            onClick: () => setNavOpen(true),
          },
        ]}
        className="sidebar:hidden"
      />
    </div>
  )
}

export const teacherRoute: RouteObject = {
  path: "teacher",
  element: <TeacherLayout />,
  children: [
    // P6.5 · `handle.title` on every child. See `lib/meta/documentMeta.ts`.
    {
      index: true,
      element: <Overview />,
      handle: { title: "Teacher dashboard", skeleton: "card-grid" },
    },
    {
      path: "grading",
      element: <Grading />,
      handle: { title: "Grading console", skeleton: "page-header" },
    },
    {
      path: "deleted",
      element: <RecentlyDeleted />,
      handle: { title: "Recently deleted", skeleton: "list" },
    },
    {
      path: "review",
      element: <Review />,
      handle: { title: "Review queue", skeleton: "list" },
    },
    {
      path: "review/:itemId",
      element: <ReviewItem />,
      handle: { title: "Review a mark", skeleton: "page-header" },
    },
    {
      path: "classes",
      element: <Classes />,
      handle: { title: "Classes", skeleton: "card-grid" },
    },
    {
      path: "classes/:classId",
      element: <ClassDetailLayout />,
      // The layout carries a title so its `index` child (the roster) inherits
      // one, and `analytics` overrides it. Deepest wins, so this is the
      // fallback rather than a competing entry.
      handle: { title: "Class", skeleton: "page-header" },
      children: [
        {
          index: true,
          element: <ClassRoster />,
          handle: { title: "Class roster", skeleton: "page-header" },
        },
        {
          path: "analytics",
          element: <ClassAnalytics />,
          handle: { title: "Class analytics", skeleton: "page-header" },
        },
        {
          path: "papers",
          element: <ClassPapers />,
          handle: { title: "Class papers", skeleton: "page-header" },
        },
      ],
    },
    // D7.10 / Task 21. Deliberately not in `navItems` (`./data.ts`), matching
    // `/student/onboard`'s exclusion from the student nav for the identical
    // reason: this is a gate destination, not a standing section a teacher
    // with classes already has any reason to navigate to. It stays mounted
    // and deep-linkable regardless — the setup screen only
    // ever sends a teacher here, it does not gate this route itself, so a
    // teacher who already has classes can still open it directly (e.g. to
    // create a second class the same way) without being bounced.
    {
      path: "first-class",
      element: <CreateFirstClass />,
      handle: { title: "Create your first class", skeleton: "page-header" },
    },
    {
      path: "students/:studentId",
      element: <StudentDetail />,
      handle: { title: "Student", skeleton: "page-header" },
    },
    {
      path: "at-risk",
      element: <AtRiskList />,
      handle: { title: "Students at risk", skeleton: "list" },
    },
    {
      path: "schemes",
      element: <MarkSchemes />,
      handle: { title: "Mark schemes", skeleton: "list" },
    },
    {
      path: "quizzes",
      element: <Quizzes />,
      handle: { title: "Quizzes", skeleton: "card-grid" },
    },
    {
      path: "quizzes/:quizId",
      element: <QuizBuilder />,
      handle: { title: "Quiz builder", skeleton: "page-header" },
    },
    // T-10 is per assignment, never per quiz (§1.6) — the route shape is the
    // first place that has to say so.
    {
      path: "quizzes/:quizId/assignments/:assignmentId/results",
      element: <QuizResults />,
      handle: { title: "Quiz results", skeleton: "page-header" },
    },
    {
      path: "announcements",
      element: <Announcements />,
      handle: { title: "Announcements", skeleton: "list" },
    },
    {
      path: "notifications",
      element: <TeacherNotifications />,
      handle: { title: "Notifications", skeleton: "list" },
    },
    {
      path: "settings",
      element: <PortalSettingsLayout basePath="/teacher/settings" />,
      handle: { title: "Settings", skeleton: "page-header" },
      children: [
        {
          index: true,
          element: <ProfileSettingsSection />,
          handle: { title: "Profile settings", skeleton: "page-header" },
        },
        {
          path: "devices",
          element: <DeviceSettingsSection />,
          handle: { title: "Account and devices", skeleton: "page-header" },
        },
        {
          path: "notifications",
          // R10: the only portal that shows `reviewWithdrawn` — it fires
          // only for a teacher (Task 9's `_notify_withdrawn_reviewers`).
          element: <NotificationSettingsSection showTeacherOnly />,
          handle: { title: "Notification settings", skeleton: "page-header" },
        },
        {
          path: "install",
          element: <InstallSettingsSection />,
          handle: { title: "Install Lemely", skeleton: "page-header" },
        },
      ],
    },
    // P4.10. Last, so it only matches what nothing above did — an unmatched
    // path in this portal used to fall to the top-level `*` and cost the
    // reader the sidebar. See `portals/misc/NotFound.tsx`.
    {
      path: "*",
      element: <PortalNotFound />,
      handle: { title: "Page not found", skeleton: "page-header" },
    },
  ],
}
