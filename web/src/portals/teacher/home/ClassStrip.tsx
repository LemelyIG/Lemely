/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import type { ClassSummary } from "@/lib/teacherTypes"
import { classCardModel } from "./models"

export function ClassStrip({ classes }: { classes: ClassSummary[] }) {
  if (!classes.length) return null
  return (
    <section aria-labelledby="cs-h" className="min-w-0">
      <div className="flex items-baseline justify-between">
        <h2 id="cs-h" className="text-display-xs">Your classes</h2>
        <Link to="/teacher/classes" className="font-bold text-primary">All classes</Link>
      </div>
      <ul className="mt-3 flex snap-x gap-4 overflow-x-auto pb-2">
        {classes.map((c) => {
          const m = classCardModel(c)
          return (
            <li key={m.id} className="min-w-[280px] snap-start">
              <Link to={`/teacher/classes/${m.id}`} className="block rounded-tile bg-surface-container-lowest p-5 shadow-panel transition-shadow duration-150 hover:shadow-hover">
                <p className="font-bold">{m.title}</p>
                <p className="text-data-sm text-on-surface-variant">{m.meta}</p>
                {m.average && <p className="mt-2 text-data-md">Average {m.average}</p>}
                {m.weakTopic && <p className="mt-3 border-t border-outline-variant pt-3 text-body-sm">Weakest: {m.weakTopic}</p>}
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
