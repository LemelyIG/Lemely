import type { RouteObject } from "react-router-dom"
import { Link, NavLink, Outlet } from "react-router-dom"
import {
  SquaresFour,
  FileText,
  ChartBar,
  Warning,
  Books,
  Sparkle,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { navItems, type NavItem } from "./data"
import { Overview } from "./screens/Overview"
import { Grading } from "./screens/Grading"
import { Review } from "./screens/Review"
import { Classes } from "./screens/Classes"
import { ClassDetailLayout } from "./screens/ClassDetail"
import { ClassRoster } from "./screens/ClassRoster"
import { ClassAnalytics } from "./screens/ClassAnalytics"
import { StudentDetail } from "./screens/StudentDetail"
import { AtRiskList } from "./screens/AtRiskList"
import { MarkSchemes } from "./screens/MarkSchemes"
import { Quizzes } from "./screens/Quizzes"

const NAV_ICON: Record<NavItem["icon"], Icon> = {
  overview: SquaresFour,
  grading: FileText,
  classes: ChartBar,
  atRisk: Warning,
  schemes: Books,
  quizzes: Sparkle,
}

function SidebarNavItem({ item }: { item: NavItem }) {
  const Glyph = NAV_ICON[item.icon]
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 w-full text-left text-[14px] px-3 py-[10px] rounded-[11px] border transition-colors",
          isActive
            ? "bg-surface border-border text-t1 font-medium shadow-[0_1px_3px_oklch(0.2_0.02_60/.07)]"
            : "border-transparent text-[oklch(0.38_0.015_60)] font-normal hover:bg-[oklch(0.985_0.008_78)]",
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
              isActive ? "text-accent" : "text-[oklch(0.62_0.02_60)]",
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
      <div className="font-mono text-[10.5px] tracking-[0.12em] uppercase text-t3 px-3 pb-[9px] font-medium">
        Your classes
      </div>
      <div className="flex flex-col gap-px">
        {isPending ? (
          <div className="px-3 py-[7px] text-[12.5px] text-t3">Loading…</div>
        ) : isError ? (
          <div className="px-3 py-[7px] text-[12.5px] text-t3">Couldn't load classes.</div>
        ) : data.classes.length === 0 ? (
          <Link
            to="/teacher/classes"
            className="px-3 py-[7px] text-[12.5px] text-accent hover:underline"
          >
            Add your first class →
          </Link>
        ) : (
          <>
            {data.classes.slice(0, 5).map((c) => (
              <Link
                key={c.id}
                to={`/teacher/classes/${c.id}`}
                className="flex items-center gap-[11px] px-3 py-[7px] text-[13.5px] text-t2 rounded-[9px] hover:bg-[oklch(0.985_0.008_78)]"
              >
                <span className="w-1.5 h-1.5 rounded-full flex-none bg-[oklch(0.85_0.01_78)]" />
                {c.label}
              </Link>
            ))}
            {data.classes.length > 5 ? (
              <Link
                to="/teacher/classes"
                className="px-3 py-[7px] text-[12.5px] text-t3 hover:text-ink"
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
      <div className="w-8 h-8 rounded-full bg-accent-subtle text-[oklch(0.45_0.10_68)] flex items-center justify-center text-xs font-semibold flex-none">
        {initials}
      </div>
      <div className="leading-[1.25] min-w-0">
        <div className="text-[13px] font-medium truncate">{name}</div>
        <div className="text-[11px] text-t2">{roleLabel}</div>
      </div>
    </div>
  )
}

function Sidebar() {
  return (
    <aside className="hidden md:flex w-[252px] flex-none border-r border-border px-[14px] py-[22px] flex-col gap-6 sticky top-0 h-screen">
      <div className="flex items-center gap-2.5 px-2">
        <div className="w-[26px] h-[26px] rounded-full bg-accent text-accent-on flex items-center justify-center font-serif text-[16px] italic">
          l
        </div>
        <div className="font-serif text-[24px]">Lemely</div>
      </div>

      <nav className="flex flex-col gap-[3px]">
        {navItems.map((item) => (
          <SidebarNavItem key={item.to} item={item} />
        ))}
      </nav>

      <ClassesNavSection />

      <div className="mt-auto border-t border-border pt-[14px] flex flex-col gap-3">
        <Link
          to="/student"
          className="text-[11.5px] text-t3 px-1 hover:text-ink"
        >
          Open the student portal →
        </Link>
        <UserBlock />
      </div>
    </aside>
  )
}

function TeacherLayout() {
  return (
    <div data-portal="teacher" className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 min-w-0 overflow-x-hidden px-[34px] py-[30px] max-w-[1480px] w-full">
          <Outlet />
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
  ],
}
