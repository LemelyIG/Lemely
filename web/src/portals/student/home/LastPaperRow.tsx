import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, HIT, ROW_PRESS } from "./gradeClass"
import type { HomeVm } from "./model"

export function LastPaperRow({ last, allPapersTo, className }: { last: NonNullable<HomeVm["last"]>; allPapersTo: string | null; className?: string }) {
  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2", className)}>
      <Link to={last.to} className={cn("grid grid-cols-[36px_minmax(0,1fr)_18px] items-center gap-3 px-0.5 py-2.5 text-on-surface", ROW_PRESS, FOCUS)}>
        <b className={cn("text-center font-display text-[28px] font-extrabold leading-none", gradeText(last.grade))}>{last.grade}</b>
        <span className="min-w-0">
          <b className="block truncate text-[15px] font-bold">{last.title}</b>
          <span className="text-[13px] text-on-surface-variant">{last.sub}</span>
        </span>
        <CaretRight size={18} className="text-on-surface-variant" aria-hidden="true" />
      </Link>
      {allPapersTo ? (
        <Link to={allPapersTo} className={cn("flex min-h-11 items-center px-1 text-[13px] font-semibold text-primary", HIT, FOCUS)}>
          All papers
        </Link>
      ) : null}
    </div>
  )
}
