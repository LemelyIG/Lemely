import type { RouteObject } from "react-router-dom"
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom"
import { MagnifyingGlass } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { crumbs, navGroups, studentMeta, studentName } from "./data"
import { Overview } from "./screens/Overview"
import { Subject } from "./screens/Subject"
import { PaperResult } from "./screens/PaperResult"
import { CorrectPaper } from "./screens/CorrectPaper"
import { StudyPlan } from "./screens/StudyPlan"
import { Standings } from "./screens/Standings"
import { Onboarding } from "./screens/Onboarding"
import { Landing } from "./screens/Landing"
import { Directions } from "./screens/Directions"
import { Parents } from "./screens/Parents"

/*
 * Student portal (terracotta). Grouped sidebar nav + a sticky top header
 * (breadcrumb, search, streak pill, "Correct a paper" CTA) wrap an <Outlet/>.
 * The layout root sets data-portal="student" so the token layer resolves to the
 * terracotta accent + neutrals (student is also the default scope).
 */

function Sidebar() {
  return (
    <aside className="hidden min-[820px]:flex w-[246px] flex-none bg-surface-2 border-r border-border px-4 py-[22px] flex-col gap-[26px] sticky top-0 h-screen">
      <div className="flex items-center gap-[9px] px-2">
        <div className="w-[11px] h-[11px] rounded-full bg-accent" />
        <div className="font-serif text-[25px] tracking-[0.01em]">Lemely</div>
      </div>

      <div className="flex flex-col gap-[22px] overflow-auto lm-scroll">
        {navGroups.map((grp) => (
          <div key={grp.label} className="flex flex-col gap-0.5">
            <div className="text-[10.5px] tracking-[0.12em] uppercase text-t3 px-2 pb-[7px] font-medium">
              {grp.label}
            </div>
            {grp.items.map((it) => (
              <NavLink
                key={it.to}
                to={it.to}
                end={it.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 w-full text-left text-[13.5px] px-[9px] py-2 rounded-[9px] transition-colors",
                    isActive
                      ? "bg-[oklch(0.90_0.02_40)] text-t1 font-medium"
                      : "bg-transparent text-[oklch(0.36_0.018_35)] font-normal hover:bg-[oklch(0.93_0.01_40)]",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={cn(
                        "w-1.5 h-1.5 rounded-full flex-none",
                        isActive ? "bg-accent" : "bg-[oklch(0.85_0.008_40)]",
                      )}
                    />
                    <span className="flex-1">{it.label}</span>
                    {it.tag ? (
                      <span className="font-mono text-[10px] text-t3">
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
        <Link to="/teacher" className="text-[11.5px] text-t3 px-0.5 hover:text-ink">
          Open the teacher portal -&gt;
        </Link>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-accent-subtle text-accent flex items-center justify-center text-[12.5px] font-semibold">
            MR
          </div>
          <div className="leading-[1.25]">
            <div className="text-[13px] font-medium">{studentName}</div>
            <div className="text-[11px] text-t2">{studentMeta}</div>
          </div>
        </div>
      </div>
    </aside>
  )
}

/**
 * Resolve the breadcrumb for a pathname: exact static lookup first (the
 * `crumbs` map), falling back to pattern matching for routes with a dynamic
 * segment that can't be enumerated in that map ahead of time.
 */
function resolveCrumb(pathname: string): string {
  const exact = crumbs[pathname]
  if (exact) return exact

  const subjectMatch = pathname.match(/^\/student\/subject\/([^/]+)$/)
  if (subjectMatch) return `Home / ${subjectMatch[1]}`

  const resultMatch = pathname.match(/^\/student\/result\/([^/]+)$/)
  if (resultMatch) return `Home / Result ${resultMatch[1]}`

  return "Home"
}

function Header() {
  const location = useLocation()
  const navigate = useNavigate()
  const crumb = resolveCrumb(location.pathname)
  return (
    // Responsive sizing here is load-bearing, not cosmetic: this row's fixed
    // items (34px padding either side, the streak pill, the 138px CTA and two
    // 18px gaps) summed to 391px, so /student/result overflowed a 380px
    // viewport by 10px — a real QUALITY-BAR "no horizontal scroll from 320px
    // up" failure, found by P3.10 chunk b's responsive gate once it covered
    // this route. The crumb must be able to shrink (`min-w-0 truncate`; it
    // renders "Home / Result <uuid>", the longest string on the row), the
    // padding tightens below 640px, and the streak pill hides there — the
    // same treatment the search affordance already gets below 1080px, and
    // the streak is shown again on the dashboard itself.
    <header className="lm-head flex items-center gap-[18px] px-4 min-[640px]:px-[34px] py-4 border-b border-border bg-[oklch(0.97_0.007_40/0.82)] backdrop-blur-[10px] sticky top-0 z-20">
      <div className="font-mono text-[11.5px] text-t2 min-w-0 truncate">{crumb}</div>
      <div className="flex-1" />
      <div className="hidden min-[1080px]:flex items-center gap-2 bg-surface border border-border rounded-[9px] px-3 py-[7px] w-[280px]">
        <MagnifyingGlass size={13} className="text-t3" weight="bold" />
        <span className="text-[12.5px] text-t3">
          Search papers, topics, students
        </span>
      </div>
      <div className="hidden min-[640px]:flex items-center gap-[7px] border border-border bg-surface rounded-[9px] px-[11px] py-[7px]">
        <span className="text-[12.5px] font-semibold font-mono">24</span>
        <span className="text-[11.5px] text-t2">day streak</span>
      </div>
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
    { path: "plan", element: <StudyPlan /> },
    { path: "board", element: <Standings /> },
    // The only place a parent_child_links row is created (D3.11).
    { path: "parents", element: <Parents /> },
    { path: "onboard", element: <Onboarding /> },
    { path: "landing", element: <Landing /> },
    { path: "directions", element: <Directions /> },
  ],
}
