import { Link } from "react-router-dom"
import { CaretRight, Check } from "@phosphor-icons/react"
import { GoldRing } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { FOCUS, HIT, PRESS } from "./gradeClass"
import type { HomeVm } from "./model"
import { WeekStrip } from "./WeekStrip"

export function TodayBlock({ today, week }: { today: HomeVm["today"]; week: HomeVm["week"] }) {
  return (
    <div className="grid gap-3">
      <Link to={today.planTo} className={cn("inline-flex items-center gap-2 justify-self-start rounded-row py-1 pe-1.5 text-on-surface", HIT, PRESS, FOCUS)}>
        <GoldRing parts={today.parts} size={32} label={today.label} />
        <b className="text-[15px] font-bold">{today.label}</b>
        <span className="ms-1 text-[13px] font-semibold text-primary">Plan</span>
        <CaretRight size={14} weight="bold" className="text-on-surface-variant" aria-hidden="true" />
      </Link>
      <div className="flex flex-wrap gap-1.5">
        {today.chips.map((chip) => (
          <Link
            key={chip.label}
            to={chip.to}
            className={cn(
              "inline-flex min-h-9 items-center gap-1.5 whitespace-nowrap rounded-row px-2.5 text-[13px] font-semibold",
              HIT,
              PRESS,
              FOCUS,
              chip.done ? "bg-tertiary-container/70 ps-[7px] text-on-tertiary-container" : "bg-surface-container-lowest/70 text-on-surface-variant",
            )}
          >
            {chip.done ? (
              <span className="grid size-4 place-items-center rounded-[5px] bg-tertiary text-on-tertiary">
                <Check size={10} weight="bold" aria-hidden="true" />
              </span>
            ) : (
              <span aria-hidden="true" className="size-1.5 rounded-full bg-outline" />
            )}
            {chip.label}
            {chip.done ? <span className="sr-only">, done</span> : null}
          </Link>
        ))}
      </div>
      <WeekStrip days={week} className="-mt-0.5 md:hidden" />
    </div>
  )
}
