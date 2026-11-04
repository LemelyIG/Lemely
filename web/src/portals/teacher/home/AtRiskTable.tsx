import { Link } from "react-router-dom"
import type { AtRiskStudent } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { gradeChipClass } from "@/lib/grade"
import { atRiskRowModel } from "./models"

export function AtRiskTable({ students }: { students: AtRiskStudent[] }) {
  return (
    <section aria-labelledby="ar-h" className="rounded-card bg-surface-container-lowest p-6 shadow-panel">
      <div className="flex items-baseline justify-between">
        <h2 id="ar-h" className="font-display text-[28px] font-extrabold tracking-[-0.03em]">
          At-risk students<span className="sr-only">, {students.length} this week</span>{" "}
          <span aria-hidden className="text-eyebrow text-on-surface-variant">{students.length} this week</span>
        </h2>
        <Link to="/teacher/at-risk" className="font-bold text-primary">View all</Link>
      </div>
      {students.length === 0 ? (
        <p className="mt-4 text-body-md text-on-surface-variant">No student is on a falling trend right now.</p>
      ) : (
        <ul className="mt-2">
          {students.slice(0, 4).map((s, i) => {
            const m = atRiskRowModel(s)
            return (
              <li key={`${m.name}-${i}`} className="[&+&]:border-t [&+&]:border-outline-variant">
                <Link to="/teacher/at-risk" className="group flex items-center gap-4 py-3 outline-offset-[-2px] transition-transform duration-150 hover:translate-x-1 motion-reduce:hover:translate-x-0 focus-visible:outline-2 focus-visible:outline-primary">
                  <span aria-hidden className="grid size-10 place-items-center rounded-pill bg-primary-container font-bold text-on-primary-container transition-colors group-hover:bg-primary group-hover:text-on-primary">{m.initials}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-bold group-hover:underline">{m.name}</span>
                    <span className="flex items-center gap-2 text-body-sm text-on-surface-variant">
                      <span className="truncate">{m.reason}</span>
                      {m.moreReasons > 0 && <span className="flex-none">+{m.moreReasons} more</span>}
                      {m.acknowledged && (
                        <span className="flex-none rounded-pill bg-secondary-container px-2 py-px text-data-sm text-on-secondary-container">Acknowledged</span>
                      )}
                    </span>
                  </span>
                  {m.to && (
                    <span className="flex items-center gap-2" role="img" aria-label={m.from ? `${m.from} to ${m.to}` : m.to}>
                      {m.from && <span className={`grid size-9 place-items-center rounded-row font-bold ${gradeChipClass(m.from)}`}>{m.from}</span>}
                      {m.from && <span aria-hidden className="text-on-surface-variant"><ForwardArrow /></span>}
                      <span className={`grid size-9 place-items-center rounded-row font-bold ${gradeChipClass(m.to)}`}>{m.to}</span>
                    </span>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
