/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { ChalkboardTeacher, ChartBar, Heart, UsersThree } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, ROW_PRESS } from "../gradeClass"
import type { peopleVm } from "./meModel"

const ICON = { classes: ChalkboardTeacher, standings: ChartBar, friends: UsersThree, parents: Heart } as const

export function PeopleDoors({ doors, className }: { doors: ReturnType<typeof peopleVm>; className?: string }) {
  return (
    <nav aria-label="Your people" className={cn("grid grid-cols-4 gap-1.5 md:gap-3", className)}>
      {doors.map((d) => {
        const Icon = ICON[d.id]
        return (
          <Link key={d.id} to={d.to} className={cn("grid min-w-0 justify-items-center gap-1.5 text-center text-[13px] font-semibold text-on-surface", ROW_PRESS, FOCUS)}>
            <span className="grid size-14 place-items-center rounded-tile bg-primary-container text-primary md:size-16 md:rounded-[22px]">
              <Icon size={24} aria-hidden="true" />
            </span>
            <span>{d.label}</span>
            {d.sub ? <small className="-mt-1 text-[12px] font-medium text-on-surface-variant">{d.sub}</small> : null}
          </Link>
        )
      })}
    </nav>
  )
}
