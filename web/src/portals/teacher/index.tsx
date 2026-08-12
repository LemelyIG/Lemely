import type { RouteObject } from "react-router-dom"
import { lazy, Suspense } from "react"
import { RouteFallback } from "@/components/ui/state-views"
import { Link, NavLink, Outlet } from "react-router-dom"
import {
  SquaresFour,
  FileText,
  ChartBar,
  Warning,
  Books,
  Sparkle,
  Megaphone,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { navItems, type NavItem } from "./data"

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
  classes: ChartBar,
  atRisk: Warning,
  schemes: Books,
  quizzes: Sparkle,
  announcements: Megaphone,
}

function SidebarNavItem({ item }: { item: NavItem }) {
  const Glyph = NAV_ICON[item.icon]
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 w-full text-left text-sm px-3 py-[10px] rounded-md border transition-colors",
          isActive
            ? "bg-surface border-border text-t1 font-medium shadow-sm"
            : "border-transparent text-t2 font-normal hover:bg-surface-2",
        )
      }
    >
      {({ isActive }) => (
        <>
          <Glyph
            size={16}
            weight={isActive ? "fill" : "regular"}
            className={cn(
              "flex-none",
              isActive ? "text-accent" : "text-t3",
            )}
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
      <div className="font-mono text-3xs tracking-[0.12em] uppercase text-t3 px-3 pb-[9px] font-medium">
        Your classes
      </div>
      <div className="flex flex-col gap-px">
        {isPending ? (
          <div className="px-3 py-[7px] text-dense-sm text-t3">Loading…</div>
        ) : isError ? (
          <div className="px-3 py-[7px] text-dense-sm text-t3">Couldn't load classes.</div>
        ) : data.classes.length === 0 ? (
          <Link
            to="/teacher/classes"
            className="px-3 py-[7px] text-dense-sm text-accent hover:underline"
          >
            Add your first class →
          </Link>
        ) : (
          <>
            {data.classes.slice(0, 5).map((c) => (
              <Link
                key={c.id}
                to={`/teacher/classes/${c.id}`}
                className="flex items-center gap-[11px] px-3 py-[7px] text-dense-lg text-t2 rounded hover:bg-surface-2"
              >
                <span className="w-1.5 h-1.5 rounded-full flex-none bg-border" />
                {c.label}
              </Link>
            ))}
            {data.classes.length > 5 ? (
              <Link
                to="/teacher/classes"
                className="px-3 py-[7px] text-dense-sm text-t3 hover:text-ink"
              >
                See all {data.classes.length} →
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
 */
function UserBlock() {
  const { data, isPending, isError } = useProfile()

  if (isPending || isError || !data) {
    return (
      <div className="flex items-center gap-[11px] px-1 text-xs text-t3">
        {isPending ? "Loading…" : "Signed in"}
      </div>
    )
  }

  const name = data.displayName ?? data.email.split("@")[0]
  const initials = (data.displayName ?? name)
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
    <div className="flex items-center gap-[11px] px-1">
      <div className="w-8 h-8 rounded-full bg-accent-subtle text-accent-subtle-on flex items-center justify-center text-xs font-semibold flex-none">
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
    <aside className="hidden md:flex w-[252px] flex-none border-r border-border px-[14px] py-[22px] flex-col gap-6 sticky top-0 h-screen">
      <div className="flex items-center gap-2.5 px-2">
        <div className="w-[26px] h-[26px] rounded-full bg-accent text-accent-on flex items-center justify-center font-serif text-base italic">
          l
        </div>
        <div className="text-display-sm">Lemely</div>
      </div>

      <nav className="flex flex-col gap-[3px]">
        {navItems.map((item) => (
          <SidebarNavItem key={item.to} item={item} />
        ))}
      </nav>

      <ClassesNavSection />

      <div className="mt-auto border-t border-border pt-[14px] flex flex-col gap-3">
        {/* Settings sits here rather than in `navItems` above, and that is a
            judgement rather than convenience. The primary nav is this teacher's
            *work* — every entry is a route under /teacher with a NavLink active
            state. `/settings/*` is neither: it is account-level, shared with
            every other role, and would never render active from a list matched
            against the teacher subtree. One entry is enough because the two
            settings screens link to each other. P5.9 chunk D. */}
        <Link
          to="/settings/devices"
          className="text-xs text-t3 px-1 hover:text-ink"
        >
          Account, devices &amp; notifications →
        </Link>
        <Link
          to="/student"
          className="text-xs text-t3 px-1 hover:text-ink"
        >
          Open the student portal →
        </Link>
        <UserBlock />
      </div>
    </aside>
  )
}

// One boundary around the Outlet (not per-route): sidebar and chrome stay
// mounted and interactive while a screen chunk loads. Fallback is the shared
// `RouteFallback` (C-11 state-view family); see the student portal for the
// reasoning, and `state-views.tsx` for why it is not a full `StateView`.

function TeacherLayout() {
  return (
    <div data-portal="teacher" className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 min-w-0 overflow-x-hidden px-[34px] py-[30px] max-w-[1480px] w-full">
          <Suspense fallback={<RouteFallback className="text-dense-lg" />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  )
}

export const teacherRoute: RouteObject = {
  path: "teacher",
  element: <TeacherLayout />,
  children: [
    { index: true, element: <Overview /> },
    { path: "grading", element: <Grading /> },
    { path: "review", element: <Review /> },
    { path: "review/:itemId", element: <ReviewItem /> },
    { path: "classes", element: <Classes /> },
    {
      path: "classes/:classId",
      element: <ClassDetailLayout />,
      children: [
        { index: true, element: <ClassRoster /> },
        { path: "analytics", element: <ClassAnalytics /> },
      ],
    },
    { path: "students/:studentId", element: <StudentDetail /> },
    { path: "at-risk", element: <AtRiskList /> },
    { path: "schemes", element: <MarkSchemes /> },
    { path: "quizzes", element: <Quizzes /> },
    { path: "quizzes/:quizId", element: <QuizBuilder /> },
    // T-10 is per assignment, never per quiz (§1.6) — the route shape is the
    // first place that has to say so.
    {
      path: "quizzes/:quizId/assignments/:assignmentId/results",
      element: <QuizResults />,
    },
    { path: "announcements", element: <Announcements /> },
  ],
}
