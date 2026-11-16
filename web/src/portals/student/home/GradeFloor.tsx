import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, PRESS } from "./gradeClass"
import type { HomeVm } from "./model"

export function GradeFloor({ floor }: { floor: HomeVm["floor"] }) {
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
    </nav>
  )
}
