import type { RouteObject } from "react-router-dom"
import { lazy, Suspense, useState } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { RouteFallback } from "@/components/ui/state-views"
import { NavDrawer, NavDrawerTrigger } from "@/components/ui/nav-drawer"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { useProfile } from "@/lib/hooks/useMeApi"
import { navGroups, resolveCrumb } from "./data"

/*
 * Student portal (terracotta). Grouped sidebar nav + a sticky top header
 * (breadcrumb, search, streak pill, "Correct a paper" CTA) wrap an <Outlet/>.
 * The layout root sets data-portal="student" so the token layer resolves to the
 * terracotta accent + neutrals (student is also the default scope).
 *
 * P6.1b: every screen below is `React.lazy`, not a static import. This portal
 * alone pulled in ~24 screens' worth of JS (subject drilldowns, the whole
 * practice/placement/flashcards/studyplan flow) into the ONE bundle every
 * route paid for, regardless of which screen a session actually visited.
 * Splitting at the screen boundary means a student who only ever opens
 * Overview and Subject never downloads QuizBuilder-sized code they'll never
 * run. Screens are named exports (not default), so each lazy import needs the
 * `.then((m) => ({ default: m.X }))` adapter — `React.lazy` only accepts a
 * default-export module.
 */
const Overview = lazy(() => import("./screens/Overview").then((m) => ({ default: m.Overview })))
const Subject = lazy(() => import("./screens/Subject").then((m) => ({ default: m.Subject })))
const PaperResult = lazy(() => import("./screens/PaperResult").then((m) => ({ default: m.PaperResult })))
const CorrectPaper = lazy(() => import("./screens/CorrectPaper").then((m) => ({ default: m.CorrectPaper })))
const StudyPlanSession = lazy(() =>
  import("./screens/studyplan/StudyPlanSession").then((m) => ({ default: m.StudyPlanSession })),
)
const StudyPlanWeek = lazy(() =>
  import("./screens/studyplan/StudyPlanWeek").then((m) => ({ default: m.StudyPlanWeek })),
)
const Standings = lazy(() => import("./screens/Standings").then((m) => ({ default: m.Standings })))
const Announcements = lazy(() =>
  import("./screens/Announcements").then((m) => ({ default: m.Announcements })),
)
const Notifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.Notifications })),
)
const Friends = lazy(() => import("./screens/Friends").then((m) => ({ default: m.Friends })))
const Profile = lazy(() => import("./screens/Profile").then((m) => ({ default: m.Profile })))
const Onboarding = lazy(() => import("./screens/Onboarding").then((m) => ({ default: m.Onboarding })))
const PlacementInvite = lazy(() =>
  import("./screens/placement/PlacementInvite").then((m) => ({ default: m.PlacementInvite })),
)
const PlacementTest = lazy(() =>
  import("./screens/placement/PlacementTest").then((m) => ({ default: m.PlacementTest })),
)
const PlacementResult = lazy(() =>
  import("./screens/placement/PlacementResult").then((m) => ({ default: m.PlacementResult })),
)
const PracticeGenerator = lazy(() =>
  import("./screens/practice/PracticeGenerator").then((m) => ({ default: m.PracticeGenerator })),
)
const PracticeSet = lazy(() =>
  import("./screens/practice/PracticeSet").then((m) => ({ default: m.PracticeSet })),
)
const PracticeResult = lazy(() =>
  import("./screens/practice/PracticeResult").then((m) => ({ default: m.PracticeResult })),
)
const PracticePrint = lazy(() =>
  import("./screens/practice/PracticePrint").then((m) => ({ default: m.PracticePrint })),
)
const FlashcardDecks = lazy(() =>
  import("./screens/flashcards/FlashcardDecks").then((m) => ({ default: m.FlashcardDecks })),
)
const FlashcardReview = lazy(() =>
  import("./screens/flashcards/FlashcardReview").then((m) => ({ default: m.FlashcardReview })),
)
const Landing = lazy(() => import("./screens/Landing").then((m) => ({ default: m.Landing })))
const Directions = lazy(() => import("./screens/Directions").then((m) => ({ default: m.Directions })))
const Parents = lazy(() => import("./screens/Parents").then((m) => ({ default: m.Parents })))

/**
 * Sidebar identity block. Wired to `GET /api/me/profile` (`useProfile()`) —
 * replaces the mock's hardcoded "Maya Rahman / Year 11 - Helwan Science
 * Centre" and "MR" initials, which no field anywhere supplies. This is the
 * same fiction P3.7 chunk b removed from the *teacher* sidebar; the student
 * side was missed then and is fixed here (P3.10 chunk c), reusing that
 * screen's `UserBlock` shape verbatim so the two cannot drift.
 *
 * `displayName` is nullable (a caller who never set one); the fallback is the
 * email's local part, never a fabricated name. The subtitle is the caller's
 * real platform role — the only affiliation-like fact this account actually
 * carries. There is no year-group or school-name field on `Profile`, so no
 * "Year 11 - <school>" line is rendered at all rather than invented.
 */
function UserBlock() {
  const { data, isPending, isError } = useProfile()

  if (isPending || isError || !data) {
    return (
      <div className="flex items-center gap-2.5 px-0.5 text-xs text-t3">
        {isPending ? "Loading…" : "Signed in"}
      </div>
    )
  }

  const name = data.displayName ?? data.email.split("@")[0]
  const initials = name
    .split(" ")
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()
  const roleLabel = data.role
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")

  return (
    <div className="flex items-center gap-2.5">
      <div className="w-8 h-8 rounded-full bg-accent-subtle text-accent-subtle-on flex items-center justify-center text-dense-sm font-semibold flex-none">
        {initials}
      </div>
      <div className="leading-[1.25] min-w-0">
        <div className="text-dense font-medium truncate">{name}</div>
        <div className="text-2xs text-t2">{roleLabel}</div>
      </div>
    </div>
  )
}

/**
 * The grouped destination list itself, with no chrome around it.
 *
 * Extracted from `Sidebar` in P3.1 so the desktop aside and the mobile drawer
 * render the same list from the same code. Two copies would have been the
 * shorter diff and the wrong answer: the whole defect being fixed here is a
 * navigation that exists at one width and not another, and the surest way to
 * reintroduce it is to give each width its own copy of the item list to drift.
 *
 * `touch` raises every row to the 44px minimum Phase 6 requires. It is on in
 * the drawer (a phone, a thumb) and off in the desktop aside, where a 34px row
 * is being clicked with a pointer and eleven 44px rows would push the last of
 * them off a laptop screen.
 */
function NavGroups({ touch = false }: { touch?: boolean }) {
  return (
    <div className="flex flex-col gap-[22px]">
      {navGroups.map((grp) => (
        <div key={grp.label} className="flex flex-col gap-0.5">
          <div className="text-3xs tracking-[0.12em] uppercase text-t3 px-2 pb-[7px] font-medium">
            {grp.label}
          </div>
          {grp.items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              className={({ isActive }) =>
                cn(
                  // `px-[9px]` not `pl-`/`pr-`: symmetric padding has no
                  // direction, so this row needs no logical rewrite (P3.4).
                  "flex items-center gap-2.5 w-full text-start text-dense-lg px-[9px] py-2 rounded transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                  touch && "min-h-11",
                  isActive
                    ? "bg-surface text-t1 font-medium"
                    : "bg-transparent text-t2 font-normal hover:bg-bg",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      "w-1.5 h-1.5 rounded-full flex-none",
                      isActive ? "bg-accent" : "bg-border",
                    )}
                  />
                  <span className="flex-1">{it.label}</span>
                  {it.tag ? (
                    <span className="font-mono text-3xs text-t3">{it.tag}</span>
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
        </div>
      ))}
    </div>
  )
}

/*
 * P3.1: the "Open the teacher portal →" link that used to sit in this footer
 * is gone, and so is its twin in the teacher sidebar. Neither one worked for
 * anybody. `RequireAuth` gates `/teacher` to teacher/school_admin/
 * platform_admin, so a student following it is redirected straight back to
 * `/student` by `portalPathForRole` — and there is no role that holds both, so
 * there was no user for whom either link did anything at all. They are
 * build-era conveniences from before the guard existed, left rendering in the
 * product as two guaranteed dead ends. Role switching for the accounts that
 * genuinely hold two roles is a real feature and is not this.
 */

function Sidebar() {
  return (
    <aside className="hidden min-[820px]:flex w-[246px] flex-none bg-surface-2 border-e border-border px-4 py-[22px] flex-col gap-[26px] sticky top-0 h-screen">
      <div className="flex items-center gap-[9px] px-2">
        <div className="w-[11px] h-[11px] rounded-full bg-accent" />
        <div className="text-display-sm tracking-[0.01em]">Lemely</div>
      </div>

      <nav aria-label="Student sections" className="overflow-auto lm-scroll">
        <NavGroups />
      </nav>

      <div className="mt-auto border-t border-border pt-[14px]">
        <UserBlock />
      </div>
    </aside>
  )
}

function Header({ onOpenNav }: { onOpenNav: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const crumb = resolveCrumb(location.pathname)
  return (
    // Responsive sizing here is load-bearing, not cosmetic: this row's fixed
    // items (34px padding either side, the 138px CTA and the gaps) overflowed
    // a 380px viewport on /student/result — a real QUALITY-BAR "no horizontal
    // scroll from 320px up" failure, found by P3.10 chunk b's responsive gate
    // once it covered this route. The crumb must still be able to shrink
    // (`min-w-0 truncate`; it renders "Home / Result <uuid>", the longest
    // string on the row) and the padding still tightens below 640px.
    //
    // P3.10 chunk c removed two of the fixed items this row used to carry, so
    // it now has considerably more slack than the fix above needed:
    //   - a `<span>` styled as a search input ("Search papers, topics,
    //     students"). It was not an input, had no handler, and no search
    //     endpoint exists anywhere in the API — fabricated UI.
    //   - a "24 day streak" pill, where the 24 was a literal. The only
    //     streak-shaped field in the API is `StandingsDTO.streakDays`, and
    //     that is `len({distinct dates in history})` — a count of active
    //     days, NOT consecutive ones. Wiring the pill to it would have
    //     replaced a hardcoded lie with a mislabelled one, so the pill is
    //     gone instead; streaks are Phase 5's to build for real.
    <header className="lm-head flex items-center gap-[18px] px-4 min-[640px]:px-[34px] py-4 border-b border-border bg-bg/80 backdrop-blur-[10px] sticky top-0 z-20">
      {/* P3.1: the only navigation entry point below 820px, which is where the
          sidebar stops existing. `-ms-2` pulls the 44px target back level with
          the crumb's text edge without shrinking the target itself. */}
      <NavDrawerTrigger
        onClick={onOpenNav}
        label="Open student navigation"
        className="-ms-2 min-[820px]:hidden"
      />
      <div className="font-mono text-xs text-t2 min-w-0 truncate">{crumb}</div>
      <div className="flex-1" />
      <Button
        variant="accent"
        size="md"
        onClick={() => navigate("/student/correct")}
      >
        Correct a paper
      </Button>
    </header>
  )
}

// One boundary around the Outlet, not one per <Route element>: the sidebar,
// header and chrome above stay mounted and interactive while a screen chunk
// downloads, so navigating never blanks the whole page — only the content
// slot shows the loading state, then swaps to the real screen. Matches the
// "Loading…" `role="status"` text every screen below already uses for its own
// data-pending state (see e.g. `screens/Overview.tsx`), so a chunk load reads
// as the same kind of wait, not a new visual language. The fallback itself is
// `RouteFallback` from the C-11 state-view family — one shared component, since
// all three portals and `App.tsx` need it and four local copies had already
// drifted to three different type/padding combinations before they were merged.

function StudentLayout() {
  const [navOpen, setNavOpen] = useState(false)

  return (
    <div data-portal="student" className="flex min-h-screen">
      <SkipLink />
      <Sidebar />

      {/* Same list, same source, different chrome — see `NavGroups`. The
          drawer closes itself on navigation, so nothing here has to. */}
      <NavDrawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title="Lemely"
        footer={<UserBlock />}
      >
        <nav aria-label="Student sections">
          <NavGroups touch />
        </nav>
      </NavDrawer>

      <div className="flex-1 min-w-0 flex flex-col">
        <Header onOpenNav={() => setNavOpen(true)} />
        {/* `<main>` moved inward in P3.1. It used to wrap the header as well,
            which made the skip link's target include the navigation it exists
            to skip past, and gave the page two competing landmarks for "the
            content". The header is chrome; `main` is what the route rendered. */}
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="lm-body flex-1 p-[34px] max-w-[1320px] w-full focus:outline-none"
        >
          <Suspense fallback={<RouteFallback className="text-dense-lg" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}

export const studentRoute: RouteObject = {
  path: "student",
  element: <StudentLayout />,
  children: [
    { index: true, element: <Overview /> },
    { path: "subject/:code", element: <Subject /> },
    { path: "result/:paperId", element: <PaperResult /> },
    { path: "correct", element: <CorrectPaper /> },
    { path: "plan/:subjectCode", element: <StudyPlanWeek /> },
    { path: "plan/:subjectCode/session/:sessionId", element: <StudyPlanSession /> },
    { path: "board", element: <Standings /> },
    { path: "announcements", element: <Announcements /> },
    { path: "notifications", element: <Notifications /> },
    { path: "friends", element: <Friends /> },
    { path: "profile", element: <Profile /> },
    // The only place a parent_child_links row is created (D3.11).
    { path: "parents", element: <Parents /> },
    { path: "onboard", element: <Onboarding /> },
    { path: "placement/:subjectCode", element: <PlacementInvite /> },
    { path: "placement/test/:assignmentId", element: <PlacementTest /> },
    { path: "placement/result/:assignmentId", element: <PlacementResult /> },
    { path: "practice/:subjectCode", element: <PracticeGenerator /> },
    { path: "practice/set/:assignmentId", element: <PracticeSet /> },
    { path: "practice/result/:assignmentId", element: <PracticeResult /> },
    { path: "practice/print/:assignmentId", element: <PracticePrint /> },
    { path: "flashcards/:subjectCode", element: <FlashcardDecks /> },
    { path: "flashcards/review/:subjectCode", element: <FlashcardReview /> },
    { path: "landing", element: <Landing /> },
    { path: "directions", element: <Directions /> },
  ],
}
