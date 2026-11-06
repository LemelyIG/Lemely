/* Hallmark · pre-emit critique: P4 H5 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import type { Overview } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { reviewQueueModel } from "./models"
import "./home.css"

/** Review queue tile, ported from the approved prototype's `.queue` card. */
export function ReviewQueueTile({ overview }: { overview: Overview }) {
  const m = reviewQueueModel(overview)
  const { thresholdPct, lowCount } = m
  const noun = m.count === 1 ? "answer" : "answers"
  const pct = <span className="th-accent tabular-nums">{thresholdPct}%</span>
  // Near the right edge the threshold label sits on the line's left so it never overflows.
  const labelLeft = thresholdPct > 75
  // A clean queue after real marking is an achievement; with no papers it stays quiet.
  const clear = m.empty && overview.paperCount > 0
  return (
    <section
      aria-labelledby="rq-h"
      className="th-queue th-lift relative grid min-w-0 grid-cols-[auto_minmax(0,1fr)] grid-rows-[auto_1fr_auto] gap-x-10 gap-y-2.5 rounded-tile px-5 py-4.5"
    >
      <h2 id="rq-h" className="th-accent col-span-full text-eyebrow">Review queue</h2>
      <div className="flex max-w-[150px] flex-col justify-center gap-2 xl:max-w-64">
        <p className="th-qnum text-display-xl">{m.count}</p>
        {clear ? (
          <p className="th-muted text-body-sm text-pretty">
            <span className="th-d mb-1 block text-display-xs">Queue clear</span>
            {overview.paperCount === 1 ? "The paper is marked, nothing flagged." : `All ${overview.paperCount} papers marked, nothing flagged.`}
          </p>
        ) : m.empty ? (
          <p className="th-muted text-body-sm text-pretty">Papers you upload will be checked here when Lemely is unsure.</p>
        ) : (
          <p className="th-muted text-body-sm text-pretty">
            <span className="th-d mb-1 block text-display-xs">
              {m.allLow ? (
                <>{noun} below {pct} confidence.</>
              ) : (
                <>{noun} waiting, <span className="tabular-nums">{lowCount}</span> below {pct} confidence.</>
              )}
            </span>
            None count until you confirm.
          </p>
        )}
      </div>
      {clear ? (
        <figure aria-label="Queue clear" className="m-0 grid min-w-0 place-items-center">
          <svg aria-hidden viewBox="0 0 48 48" className="th-tick th-accent size-20 max-w-full">
            <circle cx="24" cy="24" r="21" style={{ strokeWidth: 2, opacity: 0.45 }} />
            <path className="th-tick-path" pathLength={1} d="M14.5 25l6.5 6.5 13-15" />
          </svg>
        </figure>
      ) : (
      <figure aria-label="Pending answers by confidence" className="relative m-0 flex min-w-0 flex-col">
        <span className="sr-only">{m.count} {noun} waiting for review; {lowCount} of them scored below {thresholdPct}% confidence</span>
        <div aria-hidden className="mt-1 flex min-h-14 flex-1 items-end gap-1 pt-4">
          {m.bars.map((b) => (
            <i key={b.band} data-low={b.low || undefined} className="th-bar flex-1 rounded-bar" style={{ height: `${Math.round(b.height * 100)}%` }} />
          ))}
        </div>
        <figcaption aria-hidden className="th-ax th-muted flex justify-between text-metadata">
          <span>0%</span><span>confidence</span><span>100%</span>
        </figcaption>
        <span aria-hidden style={{ left: `${thresholdPct}%` }} className="th-thr absolute top-0 bottom-[18px]">
          <span className={`th-muted absolute -top-0.5 whitespace-nowrap text-metadata tabular-nums ${labelLeft ? "right-1.5" : "left-1.5"}`}>{thresholdPct}%</span>
        </span>
      </figure>
      )}
      {!m.empty && (
        <Link
          to="/teacher/review"
          className="th-go th-accent col-span-full inline-flex items-center gap-1.5 justify-self-start btn-text tracking-[0.01em] after:absolute after:inset-0 after:rounded-tile"
        >
          Open queue{m.estimate ? ` · ${m.estimate}` : ""}<ForwardArrow />
        </Link>
      )}
    </section>
  )
}
