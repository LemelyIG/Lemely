/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { HairRow, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { gradeText } from "../gradeClass"
import type { subjectsVm } from "./meModel"

export function YourSubjects({ rows }: { rows: ReturnType<typeof subjectsVm> }) {
  return (
    <section aria-labelledby="me-subjects" className="grid gap-1.5">
      <h2 id="me-subjects" className="py-1 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Your subjects</h2>
      {rows.length > 0 ? (
        <HairRows aria-label="Your subjects">
          {rows.map((r) => (
            <HairRow
              key={r.to}
              to={r.to}
              leading={<b className={cn("w-9 text-center font-display text-[28px] font-extrabold leading-none", gradeText(r.grade))}>{r.grade}</b>}
              title={r.title}
              sub={r.sub}
            />
          ))}
        </HairRows>
      ) : (
        <p className="text-[13px] text-on-surface-variant">Your subjects appear after your first paper.</p>
      )}
    </section>
  )
}
