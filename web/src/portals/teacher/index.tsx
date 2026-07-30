import type { RouteObject } from "react-router-dom"
import { Link, NavLink, Outlet } from "react-router-dom"
import {
  SquaresFour,
  FileText,
  ChartBar,
  Books,
  Sparkle,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { navItems, recentClasses, type NavItem } from "./data"
import { Overview } from "./screens/Overview"
import { Grading } from "./screens/Grading"
import { Review } from "./screens/Review"
import { Classes } from "./screens/Classes"
import { MarkSchemes } from "./screens/MarkSchemes"
import { Quizzes } from "./screens/Quizzes"

const NAV_ICON: Record<NavItem["icon"], Icon> = {
  overview: SquaresFour,
  grading: FileText,
  classes: ChartBar,
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
          {item.badge ? (
            <span className="font-mono text-[11px] bg-err-bg text-[oklch(0.42_0.10_22)] px-[7px] py-px rounded-full">
              {item.badge}
            </span>
          ) : null}
        </>
      )}
    </NavLink>
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

      <div>
        <div className="font-mono text-[10.5px] tracking-[0.12em] uppercase text-t3 px-3 pb-[9px] font-medium">
          Recent classes
        </div>
        <div className="flex flex-col gap-px">
          {recentClasses.map((c) => (
            <div
              key={c.label}
              className="flex items-center gap-[11px] px-3 py-[7px] text-[13.5px] text-t2 cursor-pointer rounded-[9px] hover:bg-[oklch(0.985_0.008_78)]"
            >
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full flex-none",
                  c.active ? "bg-accent" : "bg-[oklch(0.85_0.01_78)]",
                )}
              />
              {c.label}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-auto border-t border-border pt-[14px] flex flex-col gap-3">
        <Link
          to="/student"
          className="text-[11.5px] text-t3 px-1 hover:text-ink"
        >
          Open the student portal →
        </Link>
        <div className="flex items-center gap-[11px] px-1">
          <div className="w-8 h-8 rounded-full bg-accent-subtle text-[oklch(0.45_0.10_68)] flex items-center justify-center text-[12px] font-semibold">
            HS
          </div>
          <div className="leading-[1.25]">
            <div className="text-[13px] font-medium">Mr H. Sabry</div>
            <div className="text-[11px] text-t2">Physics dept · CAIE</div>
          </div>
        </div>
      </div>
    </aside>
  )
}

function TeacherLayout() {
  return (
    <div data-portal="teacher" className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 px-[34px] py-[30px] max-w-[1480px] w-full">
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
    { path: "schemes", element: <MarkSchemes /> },
    { path: "quizzes", element: <Quizzes /> },
  ],
}
