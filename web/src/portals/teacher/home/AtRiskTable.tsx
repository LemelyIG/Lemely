/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import type { AtRiskStudent } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { gradeChipClass } from "@/lib/grade"
import { atRiskRowModel } from "./models"

/** `trendsReady` is false while no class has two marked papers, so an empty list means "not yet" rather than "all clear". */
export function AtRiskTable({ students, trendsReady = true }: { students: AtRiskStudent[]; trendsReady?: boolean }) {
  return (
    <section aria-labelledby="ar-h" className="min-w-0 rounded-card bg-surface-container-lowest p-6 shadow-panel">
      <div className="flex items-baseline justify-between">
        <h2 id="ar-h" className="text-display-md">
          At-risk students<span className="sr-only">, {students.length}</span>{" "}
          <span aria-hidden className="text-eyebrow text-on-surface-variant tabular-nums">{students.length}</span>
        </h2>
        <Link to="/teacher/at-risk" className="font-bold text-primary">View all</Link>
      </div>
      {students.length === 0 ? (
        <p className="mt-4 text-body-md text-on-surface-variant">{trendsReady ? "No student is on a falling trend right now." : "Trends start once each student has two marked papers. Then anyone falling behind shows up here."}</p>
      ) : (
        <ul className="mt-2">
          {students.slice(0, 4).map((s, i) => {
            const m = atRiskRowModel(s)
            return (
              <li key={`${m.name}-${i}`} className="[&+&]:border-t [&+&]:border-outline-variant">
                <Link to="/teacher/at-risk" className="group flex items-center gap-4 py-3 transition-transform duration-150 hover:translate-x-1 motion-reduce:hover:translate-x-0">
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
