/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useRef } from "react"
import { Link } from "react-router-dom"
import { gradeChipClass } from "@/lib/grade"
import type { ClassSummary } from "@/lib/teacherTypes"
import { cn } from "@/lib/utils"
import { classCardModel, type ClassCardTrend } from "./models"
import { useDragScroll } from "./useDragScroll"

const TREND_TONE: Record<ClassCardTrend["tone"], string> = {
  up: "text-success-text",
  // A fall is not a lost mark, so it stays neutral and carries an arrow instead of crimson.
  down: "text-on-surface-variant",
  flat: "text-on-surface-variant",
}

export function ClassStrip({ classes }: { classes: ClassSummary[] }) {
  const listRef = useRef<HTMLUListElement>(null)
  useDragScroll(listRef, classes.length > 0)
  if (!classes.length) return null
  return (
    <section aria-labelledby="cs-h" className="min-w-0">
      <div className="flex items-baseline justify-between">
        <h2 id="cs-h" className="text-display-xs">Your classes</h2>
        <Link to="/teacher/classes" className="font-bold text-primary">All classes</Link>
      </div>
      {/* A scroller clips at its padding box, so the cards' panel shadow
          (about 20px wide, 50px deep) gets room inside it: padding on three
          sides, with negative side margins so the first card still lines up
          with the heading. `-mx-4` stays within the page's own 16px gutter,
          so nothing overflows at 375. The bottom padding is real layout
          space (no negative margin), so the scrollbar sits below it and the
          next section never covers it. Mouse drag scrolls (useDragScroll);
          touch and keyboard stay native. */}
      <ul
        ref={listRef}
        className="-mx-4 mt-1 flex min-w-0 cursor-grab snap-x scroll-px-4 gap-4 overflow-x-auto px-4 pb-12 pt-2 [scrollbar-color:var(--color-outline)_transparent] [scrollbar-width:thin] data-[dragging]:cursor-grabbing data-[dragging]:select-none [&[data-dragging]_a]:cursor-grabbing"
      >
        {classes.map((c) => {
          const m = classCardModel(c)
          const trendLine = m.trend || m.meta2
          return (
            <li key={m.id} className="w-[min(280px,calc(100vw-3rem))] shrink-0 snap-start">
              <Link to={`/teacher/classes/${m.id}`} draggable={false} className="block h-full rounded-tile bg-surface-container-lowest p-5 shadow-panel transition-shadow duration-150 hover:shadow-hover">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-bold">{m.title}</p>
                    <p className="truncate text-data-sm text-on-surface-variant">{m.meta}</p>
                  </div>
                  {m.grade && (
                    <span className={cn("inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-data-sm font-bold", gradeChipClass(m.grade, { size: "small" }))}>
                      <span className="sr-only">Median grade </span>
                      {m.grade}
                    </span>
                  )}
                </div>
                {m.average && <p className="mt-2 text-data-md">Average {m.average}</p>}
                {trendLine && (
                  <p className="mt-1 truncate text-data-sm text-on-surface-variant">
                    {m.trend && (
                      <span className={TREND_TONE[m.trend.tone]}>
                        {m.trend.tone === "down" && <span aria-hidden>↓ </span>}
                        {m.trend.text}
                        <span className="sr-only"> points since the previous paper</span>
                      </span>
                    )}
                    {m.trend && m.meta2 && <span aria-hidden> · </span>}
                    {m.meta2}
                  </p>
                )}
                {m.weakTopic && (
                  <div className="mt-3 border-t border-outline-variant pt-3">
                    <p className="flex items-baseline justify-between gap-3 text-body-sm">
                      <span className="min-w-0 truncate">Weakest: {m.weakTopic}</span>
                      {m.weakPct && <span className="shrink-0 text-data-sm text-on-surface-variant">{m.weakPct}<span className="sr-only"> accuracy</span></span>}
                    </p>
                    {m.weakBar !== null && (
                      <div aria-hidden className="mt-2 h-1 overflow-hidden rounded-bar bg-surface-container-high">
                        <div className="h-full rounded-bar bg-primary" style={{ width: `${m.weakBar * 100}%` }} />
                      </div>
                    )}
                  </div>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
