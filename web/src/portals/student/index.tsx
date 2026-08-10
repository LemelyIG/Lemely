import type { RouteObject } from "react-router-dom"
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { useProfile } from "@/lib/hooks/useMeApi"
import { navGroups, resolveCrumb } from "./data"
import { Overview } from "./screens/Overview"
import { Subject } from "./screens/Subject"
import { PaperResult } from "./screens/PaperResult"
import { CorrectPaper } from "./screens/CorrectPaper"
import { StudyPlanSession } from "./screens/studyplan/StudyPlanSession"
import { StudyPlanWeek } from "./screens/studyplan/StudyPlanWeek"
import { Standings } from "./screens/Standings"
import { Announcements } from "./screens/Announcements"
import { Friends } from "./screens/Friends"
import { Onboarding } from "./screens/Onboarding"
import { PlacementInvite } from "./screens/placement/PlacementInvite"
import { PlacementTest } from "./screens/placement/PlacementTest"
import { PlacementResult } from "./screens/placement/PlacementResult"
import { PracticeGenerator } from "./screens/practice/PracticeGenerator"
import { PracticeSet } from "./screens/practice/PracticeSet"
import { PracticeResult } from "./screens/practice/PracticeResult"
import { PracticePrint } from "./screens/practice/PracticePrint"
import { FlashcardDecks } from "./screens/flashcards/FlashcardDecks"
import { FlashcardReview } from "./screens/flashcards/FlashcardReview"
import { Landing } from "./screens/Landing"
import { Directions } from "./screens/Directions"
import { Parents } from "./screens/Parents"

/*
 * Student portal (terracotta). Grouped sidebar nav + a sticky top header
 * (breadcrumb, search, streak pill, "Correct a paper" CTA) wrap an <Outlet/>.
 * The layout root sets data-portal="student" so the token layer resolves to the
 * terracotta accent + neutrals (student is also the default scope).
 */

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

function Sidebar() {
  return (
    <aside className="hidden min-[820px]:flex w-[246px] flex-none bg-surface-2 border-r border-border px-4 py-[22px] flex-col gap-[26px] sticky top-0 h-screen">
      <div className="flex items-center gap-[9px] px-2">
        <div className="w-[11px] h-[11px] rounded-full bg-accent" />
        <div className="text-display-sm tracking-[0.01em]">Lemely</div>
      </div>

      <div className="flex flex-col gap-[22px] overflow-auto lm-scroll">
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
                    "flex items-center gap-2.5 w-full text-left text-dense-lg px-[9px] py-2 rounded transition-colors",
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
                      <span className="font-mono text-3xs text-t3">
                        {it.tag}
                      </span>
                    ) : null}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </div>

      <div className="mt-auto border-t border-border pt-[14px] flex flex-col gap-3">
        <Link to="/teacher" className="text-xs text-t3 px-0.5 hover:text-ink">
          Open the teacher portal -&gt;
        </Link>
        <UserBlock />
      </div>
    </aside>
  )
}

function Header() {
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

function StudentLayout() {
  return (
    <div data-portal="student" className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0 flex flex-col">
        <Header />
        <div className="lm-body flex-1 p-[34px] max-w-[1320px] w-full">
          <Outlet />
        </div>
      </main>
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
    { path: "friends", element: <Friends /> },
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
