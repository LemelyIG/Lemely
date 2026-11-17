/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { ChalkboardTeacher, Camera, FileText, TrendUp } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { gradeText } from "./gradeClass"
import type { RowLeading, RowVm } from "./model"

const ICONS = { sheet: FileText, camera: Camera, class: ChalkboardTeacher, trend: TrendUp } as const

function Leading({ leading }: { leading: RowLeading }) {
  const base = "grid size-10 place-items-center rounded-full"
  if (leading.type === "grade") {
    return <span className={cn(base, "bg-surface-container font-display text-[20px] font-extrabold", gradeText(leading.grade))}>{leading.grade}</span>
  }
  if (leading.type === "initials") {
    return <span aria-hidden="true" className={cn(base, "bg-primary-container text-[13px] font-bold text-primary")}>{leading.text}</span>
  }
  const Icon = ICONS[leading.icon]
  return (
    <span className={cn(base, "bg-primary-container text-primary")}>
      <Icon size={20} aria-hidden="true" />
    </span>
  )
}

export function MomentRows({ rows, className }: { rows: RowVm[]; className?: string }) {
  if (rows.length === 0) return null
  return (
    <div className={cn("grid", className)}>
      <HairRows aria-label="For you">
        {rows.map((r) => (
          <HairRow key={r.key} to={r.to} leading={<Leading leading={r.leading} />} title={r.title} sub={r.sub} />
        ))}
      </HairRows>
    </div>
  )
}
