/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS } from "./gradeClass"
import type { HomeVm } from "./model"

/*
 * Seven 44px targets and six 2px gaps need 320px. In the three-column Home the strip lives in the narrow
 * third column, whose width is a share of the Home container minus gaps, border and padding, so the strip
 * answers to its own column (the named `week` container), not to the Home width. Below 320px it wraps to
 * four across; the ceiling is just under 320 so a column of exactly 320 still fits seven. HomeSkeleton
 * repeats this rule so the placeholder keeps the strip's height.
 */
export function WeekStrip({ days, className }: { days: HomeVm["week"]; className?: string }) {
  return (
    <div className={cn("@container/week", className)}>
      <ol aria-label="This week" className="grid grid-cols-7 gap-0.5 @[900px]/home:@max-[319.9px]/week:grid-cols-4">
        {days.map((d) => (
          <li key={d.day}>
            <Link
              to={d.to}
              aria-label={d.ariaLabel}
              aria-current={d.isToday ? "date" : undefined}
              className={cn("grid min-h-11 min-w-11 justify-items-center gap-[5px] rounded-chip py-1.5 text-[12px] font-semibold", FOCUS, d.isToday ? "text-primary" : "text-on-surface-variant")}
            >
              <span aria-hidden="true">{d.letter}</span>
              <span
                aria-hidden="true"
                className={cn(
                  "grid size-5 place-items-center rounded-full text-on-tertiary",
                  d.done ? "bg-tertiary" : "ring-2 ring-inset ring-outline",
                  d.isToday && !d.done && "ring-[2.5px] ring-primary",
                  d.isToday && d.done && "outline-2 outline-primary",
                )}
              >
                {d.done ? <Check size={12} weight="bold" /> : null}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  )
}
