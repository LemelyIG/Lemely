/* Hallmark · pre-emit critique: P4 H5 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import type { Overview } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { reviewQueueModel } from "./models"

export function ReviewQueueTile({ overview }: { overview: Overview }) {
  const m = reviewQueueModel(overview)
  const { thresholdPct, lowCount } = m
  return (
    <section aria-labelledby="rq-h" className="min-w-0 rounded-card bg-primary p-6 text-on-primary dark:bg-primary-container dark:text-on-primary-container">
      <h2 id="rq-h" className="text-eyebrow text-inverse-primary dark:text-primary">Review queue</h2>
      <div className="mt-3 grid grid-cols-1 items-end gap-6 sm:grid-cols-2">
        <div>
          <p className="text-display-xl"><span className="tabular-nums">{m.count}</span></p>
          {m.empty ? (
            <p className="mt-2 text-body-md">Nothing needs your eyes.</p>
          ) : (
            <p className="mt-2 text-body-md">
              {m.count === 1 ? "answer waiting" : "answers waiting"} for your review.
              <span className="block text-body-sm opacity-80">
                <span className="tabular-nums">{lowCount}</span> below <span className="text-inverse-primary dark:text-primary">{thresholdPct}%</span> confidence. None count until you confirm.
              </span>
            </p>
          )}
        </div>
        <figure aria-label="Pending answers by confidence" className="min-w-0">
          <span className="sr-only">{m.count} answers waiting for review; {lowCount} of them scored below {thresholdPct}% confidence</span>
          <div className="relative h-40">
            <div className="flex h-full items-end gap-1">
              {m.bars.map((b) => (
                <span
                  key={b.band}
                  className={b.low ? `flex-1 rounded-t-bar bg-error-container dark:bg-error ${Math.round(b.height * 100) > 0 ? "border border-error" : ""}` : "flex-1 rounded-t-bar bg-inverse-primary dark:bg-primary"}
                  style={{ height: `${Math.round(b.height * 100)}%` }}
                />
              ))}
            </div>
            <span aria-hidden style={{ left: `${thresholdPct}%` }} className="absolute inset-y-0 border-l border-dashed border-on-primary dark:border-on-primary-container" />
          </div>
          <figcaption className="mt-2 flex items-baseline justify-between gap-3 text-data-sm opacity-80">
            <span>0%</span><span>confidence</span><span>100%</span>
          </figcaption>
        </figure>
      </div>
      {!m.empty && (
        <Link to="/teacher/review" className="mt-4 inline-flex items-center gap-1 font-bold text-inverse-primary dark:text-primary">
          Open queue{m.estimate ? ` · ${m.estimate}` : ""}<ForwardArrow />
        </Link>
      )}
    </section>
  )
}
