/* Hallmark · pre-emit critique: P4 H5 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import type { Overview } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { reviewQueueModel } from "./models"

export function ReviewQueueTile({ overview }: { overview: Overview }) {
  const m = reviewQueueModel(overview)
  const { thresholdPct, lowCount } = m
  return (
    <section aria-labelledby="rq-h" className="rounded-card bg-inverse-surface p-6 text-inverse-on-surface">
      <h2 id="rq-h" className="text-eyebrow text-inverse-primary">Review queue</h2>
      <div className="mt-3 grid grid-cols-[auto_1fr] items-end gap-6">
        <div>
          <p className="text-display-xl"><span className="tabular-nums">{m.count}</span></p>
          {m.empty ? (
            <p className="mt-2 text-body-md">Nothing needs your eyes.</p>
          ) : (
            <p className="mt-2 text-body-md">
              {m.count === 1 ? "answer waiting" : "answers waiting"} for your review.
              <span className="block text-body-sm opacity-80">
                <span className="tabular-nums">{lowCount}</span> below <span className="text-inverse-primary">{thresholdPct}%</span> confidence. None count until you confirm.
              </span>
            </p>
          )}
        </div>
        <figure aria-label="Pending answers by confidence" className="relative h-40">
          <span className="sr-only">{m.count} answers waiting for review; {lowCount} of them scored below {thresholdPct}% confidence</span>
          <div className="flex h-full items-end gap-1">
            {m.bars.map((b) => (
              <span
                key={b.band}
                className={b.low ? `flex-1 rounded-t-bar bg-error-container ${Math.round(b.height * 100) > 0 ? "border border-error" : ""}` : "flex-1 rounded-t-bar bg-inverse-primary"}
                style={{ height: `${Math.round(b.height * 100)}%` }}
              />
            ))}
          </div>
          <span aria-hidden style={{ left: `${thresholdPct}%` }} className="absolute inset-y-0 border-l border-dashed border-inverse-on-surface/50" />
          <figcaption className="mt-1 flex justify-between text-data-sm opacity-80">
            <span>0%</span><span>confidence</span><span>100%</span>
          </figcaption>
        </figure>
      </div>
      {!m.empty && (
        <Link to="/teacher/review" className="mt-4 inline-flex items-center gap-1 font-bold text-inverse-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-inverse-primary">
          Open queue{m.estimate ? ` · ${m.estimate}` : ""}<ForwardArrow />
        </Link>
      )}
    </section>
  )
}
