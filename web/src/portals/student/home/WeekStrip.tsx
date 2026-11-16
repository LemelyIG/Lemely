import { Link } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS } from "./gradeClass"
import type { HomeVm } from "./model"

export function WeekStrip({ days, className }: { days: HomeVm["week"]; className?: string }) {
  return (
    <ol aria-label="This week" className={cn("grid grid-cols-7 gap-1", className)}>
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
  )
}
