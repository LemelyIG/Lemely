/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, PRESS } from "./gradeClass"
import type { HomeVm } from "./model"

export function GradeFloor({ floor }: { floor: HomeVm["floor"] }) {
  // Sparse: pad the last row with ghost slots so one or two grades read as a floor still filling.
  const ghosts = floor.length % 3 === 0 ? 0 : 3 - (floor.length % 3)
  return (
    <nav aria-label="Your grades" className="grid grid-cols-3 border-y border-outline-variant py-3.5">
      {floor.map((f, i) => (
        <Link
          key={f.code}
          to={f.to}
          className={cn("grid justify-items-center gap-0.5 px-1 py-0.5 text-center", PRESS, FOCUS, i % 3 !== 0 && "border-s border-outline-variant")}
        >
          <b className={cn("font-display text-[44px] font-extrabold leading-none tracking-[-0.03em]", gradeText(f.grade))}>{f.grade}</b>
          <span className="mt-1 text-[15px] font-bold text-on-surface">{f.name}</span>
          <span className="text-[13px] text-on-surface-variant">{f.sub}</span>
        </Link>
      ))}
      {Array.from({ length: ghosts }, (_, g) => (
        <div key={`ghost-${g}`} aria-hidden="true" className="grid content-center justify-items-center gap-1.5 border-s border-outline-variant px-1 py-0.5">
          <span className="h-11 w-9 rounded-row bg-surface-container-high" />
          <span className="h-3 w-16 rounded-bar bg-surface-container-high" />
        </div>
      ))}
    </nav>
  )
}
