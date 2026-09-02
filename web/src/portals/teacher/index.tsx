/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy, Suspense, useState } from "react"
import { RouteFallback } from "@/components/ui/state-views"
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom"
import {
  SquaresFour,
  FileText,
  SealQuestion,
  ChartBar,
  Warning,
  Books,
  Sparkle,
  Megaphone,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { NavDrawer, NavDrawerTrigger } from "@/components/ui/nav-drawer"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { navItems, resolveTrail, type NavItem } from "./data"
import { ForwardArrow } from "@/components/ui/inline-arrow"

// P6.1b: screens are `React.lazy`, not static imports — see the same note in
// `portals/student/index.tsx`. QuizBuilder and ClassAnalytics in particular
// are heavy screens that most teacher sessions (grading, review) never open;
// they no longer ride along in the bundle every route pays for. Named
// exports (not default), hence the `.then((m) => ({ default: m.X }))` shape.
const Overview = lazy(() => import("./screens/Overview").then((m) => ({ default: m.Overview })))
const Grading = lazy(() => import("./screens/Grading").then((m) => ({ default: m.Grading })))
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
// D7.10 / Task 21 — the create-first-class step `teacherFirstClassRedirect`
// (below) sends a zero-class teacher to. Lazy for the same reason as every
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
}

function SidebarNavItem({ item, touch = false }: { item: NavItem; touch?: boolean }) {
  const Glyph = NAV_ICON[item.icon]
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          // Symmetric padding has no direction, so this row needs no logical
          // rewrite (P3.4).
          // §6.1's 44px floor; this row measured 32px. See the same line in the
          // admin and student sidebars — one shape, three portals.
          "flex items-center gap-2.5 w-full text-start text-label px-[9px] py-2 pointer-coarse:min-h-11 rounded-md",
          "transition-colors duration-[var(--dur-instant)] ease-out-soft",
          // `focus-ring`, not `accent`: DESIGN.md §3.9 makes focus deliberately
          // blue so it stays distinguishable from the accent's own hover and
          // selected states. This row used `outline-accent`, which made
          // "focused" and "current" the same colour on a nav whose active row
          // is already accent-marked. Same fix the student sidebar took.
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
          // The active rule is reserved at every state, transparent when
          // inactive, so turning it on cannot nudge the label sideways by 2px
          // as you navigate.
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
          {/* §10 permits `fill` for a single active-state nav icon, and this is
              it. The active row therefore carries four independent signals —
              the accent margin rule, the raised sheet, full-strength ink, and
              the filled glyph — so none of them carries the state alone. */}
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
      <div className="text-eyebrow text-ink-faint px-2 pb-[9px]">Your classes</div>
      <div className="flex flex-col gap-px">
        {isPending ? (
          <div className="px-2 py-[7px] text-body-sm text-ink-faint">Loading…</div>
        ) : isError ? (
          <div className="px-2 py-[7px] text-body-sm text-ink-faint">Couldn't load classes.</div>
        ) : data.classes.length === 0 ? (
          <Link
            to="/teacher/classes"
            className="px-2 py-[7px] pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-accent-ink hover:underline rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            Add your first class <ForwardArrow />
          </Link>
        ) : (
          <>
            {data.classes.slice(0, 5).map((c) => (
              <Link
                key={c.id}
                to={`/teacher/classes/${c.id}`}
                // §6.1's 44px floor; these class rows measured 34px. Already
                // `flex items-center`, so the label stays centred.
                className="flex items-center gap-2.5 px-2 py-[7px] pointer-coarse:min-h-11 text-body-sm text-ink-muted rounded-md hover:bg-paper hover:text-ink transition-colors duration-[var(--dur-instant)] ease-out-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
              >
                <span className="w-1.5 h-1.5 rounded-full flex-none bg-rule-strong" />
                <span className="truncate">{c.label}</span>
              </Link>
            ))}
            {data.classes.length > 5 ? (
              <Link
                to="/teacher/classes"
                className="px-2 py-[7px] pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-ink-faint transition-colors hover:text-ink rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
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
 * Nav list + "Your classes", with no chrome. Shared by the desktop aside and
 * the mobile drawer for the same reason as the student portal's `NavGroups`:
 * the defect P3.1 fixes is navigation that exists at one width and not
 * another, and two copies of the list is how that comes back.
 */
function TeacherNav({ touch = false }: { touch?: boolean }) {
  return (
    <div className="flex flex-col gap-[22px]">
      <nav aria-label="Teacher sections" className="flex flex-col gap-0.5">
        {navItems.map((item) => (
          <SidebarNavItem key={item.to} item={item} touch={touch} />
        ))}
      </nav>
      <ClassesNavSection />
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
      {/* Settings sits here rather than in `navItems` above, and that is a
          judgement rather than convenience. The primary nav is this teacher's
          *work* — every entry is a route under /teacher with a NavLink active
          state. `/settings/*` is neither: it is account-level, shared with
          every other role, and would never render active from a list matched
          against the teacher subtree. One entry is enough because the two
          settings screens link to each other. P5.9 chunk D. */}
      <Link
        to="/settings/devices"
        className="text-body-sm text-ink-faint px-0.5 pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 transition-colors hover:text-ink rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        Account, devices &amp; notifications <ForwardArrow />
      </Link>
      <UserBlock />
    </div>
  )
}

/*
 * The real mark, replacing the accent-circle-with-an-italic-*l* that stood in
 * for it. That placeholder is audit finding M9 ("the logo is a lowercase
 * italic *l* in a filled circle, stamped in three places"); the student
 * sidebar's copy was replaced when surface 1 landed and this one was still
 * live, which is P4.2's second lesson exactly — a defect fixed on one portal
 * can still be shipping on another.
 *
 * It was also the last `font-serif` call site in this file, i.e. the D4.1
 * defect: the class resolves to Tailwind's default Georgia stack, so the
 * placeholder was not even rendering in the display face it was reaching for.
 *
 * `alt=""` and `aria-hidden`, not a described image: the wordmark beside it
 * already says "Lemely", so describing the mark too makes a screen reader
 * announce the brand twice.
 */
function BrandLockup() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
      <span className="text-display-sm text-ink">Lemely</span>
    </div>
  )
}

function Sidebar() {
  return (
    // A well, per DESIGN.md §3.1: `--paper-sunk` is the token whose stated use
    // is "sidebars, table headers, code blocks, inset areas".
    <aside className="hidden md:flex w-[252px] flex-none bg-paper-sunk border-e border-rule px-4 py-[22px] flex-col gap-[26px] sticky top-0 h-screen">
      <BrandLockup />

      <div className="lm-scroll min-h-0 flex-1 overflow-y-auto">
        <TeacherNav />
      </div>

      <div className="mt-auto border-t border-rule pt-[14px]">
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
function TeacherTopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const location = useLocation()
  const trail = resolveTrail(location.pathname)

  return (
    // `z-nav`, not the raw `z-[var(--z-index-sticky)]` this row used to carry.
    // Both resolve to a real rung, but the bar holds the only navigation that
    // exists below `md`, so it belongs on the nav layer with the sidebar rather
    // than on the sticky-table-header layer beneath it — and DESIGN.md §7 wants
    // the rung named, not reached through an arbitrary value.
    <div className="sticky top-0 z-nav flex min-h-14 items-center gap-3 border-b border-rule bg-paper/80 px-page-mobile py-2.5 backdrop-blur-nav md:px-page-desktop">
      <NavDrawerTrigger
        onClick={onOpenNav}
        label="Open teacher navigation"
        className="-ms-2 md:hidden"
      />
      {/* One crumb means the trail is just the page's own name, which the page
          heading already says. Rendering nothing is better than rendering a
          row that repeats the <h1> underneath it. */}
      {trail.length > 1 ? <Breadcrumbs items={trail} /> : null}
    </div>
  )
}

/**
 * D7.10 — is a redirect to `/teacher/first-class` owed on this render?
 *
 * The teacher-side mirror of `studentOnboardingRedirect` (D7.9,
 * `portals/student/index.tsx`), pulled out of `TeacherLayout` as a pure
 * function for the identical reason: `vitest.config.ts` runs this repo's
 * unit suite under Node with no jsdom and no renderer (D3.20), so nothing
 * that requires mounting `TeacherLayout` — a hook call, `useLocation()`
 * itself — is reachable from a unit test here. The *decision* the gate makes
 * is reachable, once it is something callable on its own:
 * `web/tests/unit/teacherFirstRun.test.ts` pins it directly, all four states.
 *
 * `status` is `useTeacherClasses()`'s own three-way react-query status, not a
 * boolean the caller reduces it to first — the same defence D7.9's version
 * takes, for the same reason. The two states that must NEVER redirect are
 * exactly the two non-`"success"` ones, and a caller left holding only a
 * class count cannot tell "the list hasn't loaded yet" (`undefined`,
 * mid-flight) apart from "the list loaded and it is empty" (`0`, resolved) —
 * both look like "nothing" to a careless `!count` check. Firing on the
 * pending state would bounce a returning teacher who has real classes on
 * every cold load; firing on error would trap an account whenever
 * `GET /teacher/classes` hiccups. Requiring the real status up front makes
 * both structurally impossible here, rather than a discipline every call
 * site has to keep separately.
 *
 * The third guard, `pathname === "/teacher/first-class"`, is what keeps this
 * a redirect and not a trap: the step this gate sends a teacher to is itself
 * a route under `/teacher`, so without this guard a teacher standing on
 * it — which is every such teacher, immediately after the gate has already
 * sent them there once — would be told to redirect to the exact page they
 * are already on, on every render.
 *
 * Unlike onboarding, there is deliberately no "skip for now" reachable from
 * here. D7.10's own rationale is why: the review queue, the at-risk list,
 * class analytics and the join code itself all have nothing to scope to
 * without at least one class, so there is nowhere useful for a skip to land.
 */
export type TeacherClassesQueryStatus = "pending" | "error" | "success"

export function teacherFirstClassRedirect(
  status: TeacherClassesQueryStatus,
  classCount: number,
  pathname: string,
): string | null {
  if (status !== "success") return null
  if (classCount > 0) return null
  if (pathname === "/teacher/first-class") return null
  return "/teacher/first-class"
}

function TeacherLayout() {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()

  /*
   * The wiring for `teacherFirstClassRedirect` above. Reads the same query
   * `ClassesNavSection` already subscribes to (`useTeacherClasses()`,
   * `GET /teacher/classes`) — react-query dedupes by queryKey
   * (`["teacher", "classes"]`), so this adds no second network request, only
   * a second subscriber to the one already in flight.
   *
   * A pending query renders the shared route fallback in place of the whole
   * shell rather than the shell-with-a-fallback-inside-it, for the same
   * reason D7.9's version does: until the list resolves we do not yet know
   * whether this teacher belongs on this route, so there is nothing honest
   * to put in a sidebar built for a destination we might immediately
   * redirect away from. An errored query falls through to the portal exactly
   * as it rendered before this gate existed — a `/teacher/classes` hiccup
   * must degrade to "the portal renders", never to "the account is stuck on
   * the first-class step until the network recovers".
   */
  const classesQuery = useTeacherClasses()
  if (classesQuery.isPending) {
    return <RouteFallback className="p-8" />
  }
  const firstClassRedirect = teacherFirstClassRedirect(
    classesQuery.status,
    classesQuery.data?.classes.length ?? 0,
    location.pathname,
  )
  if (firstClassRedirect) {
    return <Navigate to={firstClassRedirect} replace />
  }

  return (
    // `paper-grain` is DESIGN.md §8's first texture element and the cheapest
    // carrier of the one protected quality (§1). The student shell has had it
    // since surface 1; the teacher portal had none of the texture layer at all,
    // which is why it read as the generic dashboard the anti-references name.
    <div data-portal="teacher" className="paper-grain flex min-h-screen">
      <SkipLink />
      <Sidebar />

      <NavDrawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title="Lemely"
        footer={<SidebarFooter />}
      >
        <TeacherNav touch />
      </NavDrawer>

      <div className="flex-1 min-w-0 flex flex-col">
        <TeacherTopBar onOpenNav={() => setNavOpen(true)} />
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

export const teacherRoute: RouteObject = {
  path: "teacher",
  element: <TeacherLayout />,
  children: [
    // P6.5 · `handle.title` on every child. See `lib/meta/documentMeta.ts`.
    { index: true, element: <Overview />, handle: { title: "Teacher dashboard" } },
    { path: "grading", element: <Grading />, handle: { title: "Grading console" } },
    { path: "review", element: <Review />, handle: { title: "Review queue" } },
    { path: "review/:itemId", element: <ReviewItem />, handle: { title: "Review a mark" } },
    { path: "classes", element: <Classes />, handle: { title: "Classes" } },
    {
      path: "classes/:classId",
      element: <ClassDetailLayout />,
      // The layout carries a title so its `index` child (the roster) inherits
      // one, and `analytics` overrides it. Deepest wins, so this is the
      // fallback rather than a competing entry.
      handle: { title: "Class" },
      children: [
        { index: true, element: <ClassRoster />, handle: { title: "Class roster" } },
        { path: "analytics", element: <ClassAnalytics />, handle: { title: "Class analytics" } },
      ],
    },
    // D7.10 / Task 21. Deliberately not in `navItems` (`./data.ts`), matching
    // `/student/onboard`'s exclusion from the student nav for the identical
    // reason: this is a gate destination, not a standing section a teacher
    // with classes already has any reason to navigate to. It stays mounted
    // and deep-linkable regardless — `teacherFirstClassRedirect` above only
    // ever sends a teacher here, it does not gate this route itself, so a
    // teacher who already has classes can still open it directly (e.g. to
    // create a second class the same way) without being bounced.
    {
      path: "first-class",
      element: <CreateFirstClass />,
      handle: { title: "Create your first class" },
    },
    { path: "students/:studentId", element: <StudentDetail />, handle: { title: "Student" } },
    { path: "at-risk", element: <AtRiskList />, handle: { title: "Students at risk" } },
    { path: "schemes", element: <MarkSchemes />, handle: { title: "Mark schemes" } },
    { path: "quizzes", element: <Quizzes />, handle: { title: "Quizzes" } },
    { path: "quizzes/:quizId", element: <QuizBuilder />, handle: { title: "Quiz builder" } },
    // T-10 is per assignment, never per quiz (§1.6) — the route shape is the
    // first place that has to say so.
    {
      path: "quizzes/:quizId/assignments/:assignmentId/results",
      element: <QuizResults />,
      handle: { title: "Quiz results" },
    },
    { path: "announcements", element: <Announcements />, handle: { title: "Announcements" } },
    // P4.10. Last, so it only matches what nothing above did — an unmatched
    // path in this portal used to fall to the top-level `*` and cost the
    // reader the sidebar. See `portals/misc/NotFound.tsx`.
    { path: "*", element: <PortalNotFound />, handle: { title: "Page not found" } },
  ],
}
