/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { FOCUS, gradeText, ROW_PRESS } from "../gradeClass"
import type { statsVm } from "./meModel"

export function StatsRow({ stats }: { stats: ReturnType<typeof statsVm> }) {
  return (
    <div className="grid grid-cols-3 border-y border-outline-variant py-3.5">
      {stats.map((s, i) => (
        <Link key={s.label} to={s.to} className={cn("grid justify-items-center gap-0.5 text-on-surface", ROW_PRESS, FOCUS, i > 0 && "border-s border-outline-variant")}>
          <b className={cn("text-[30px] font-extrabold leading-none tracking-[-0.02em]", s.grade ? cn("font-display", gradeText(s.grade)) : "font-mono text-primary")}>{s.value}</b>
          <span className="text-[13px] text-on-surface-variant">{s.label}</span>
        </Link>
      ))}
    </div>
  )
}
