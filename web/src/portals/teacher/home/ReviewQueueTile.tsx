import { Link } from "react-router-dom"
import type { Overview } from "@/lib/teacherTypes"
import { ForwardArrow } from "@/components/ui/inline-arrow"
import { reviewQueueModel } from "./models"

export function ReviewQueueTile({ overview }: { overview: Overview }) {
  const m = reviewQueueModel(overview)
  return (
    <section aria-labelledby="rq-h" className="rounded-card bg-inverse-surface p-6 text-inverse-on-surface">
      <h2 id="rq-h" className="text-eyebrow text-inverse-primary">Review queue</h2>
      <div className="mt-3 grid grid-cols-[auto_1fr] items-end gap-6">
        <div>
          <p className="font-display text-[64px] font-extrabold leading-none tracking-[-0.03em] tabular-nums">{m.count}</p>
          {m.empty ? (
            <p className="mt-2 text-body-md">Nothing needs your eyes.</p>
          ) : (
            <p className="mt-2 text-body-md">
              answers below <span className="text-inverse-primary">70%</span> confidence.
              <span className="block text-body-sm opacity-80">None count until you confirm.</span>
            </p>
          )}
        </div>
        <figure aria-label="Pending answers by confidence" className="relative h-40">
          <div className="flex h-full items-end gap-1">
            {m.bars.map((b) => (
              <span
                key={b.band}
                className={b.low ? "flex-1 rounded-t-bar bg-error" : "flex-1 rounded-t-bar bg-inverse-primary"}
                style={{ height: `${Math.round(b.height * 100)}%` }}
              />
            ))}
          </div>
          <span aria-hidden className="absolute inset-y-0 left-[70%] border-l border-dashed border-inverse-on-surface/50" />
          <figcaption className="mt-1 flex justify-between text-data-sm opacity-80">
            <span>0%</span><span>confidence</span><span>100%</span>
          </figcaption>
        </figure>
      </div>
      {!m.empty && (
        <Link to="/teacher/review" className="mt-4 inline-flex items-center gap-1 font-bold text-inverse-primary">
          Open queue{m.estimate ? ` · ${m.estimate}` : ""}<ForwardArrow />
        </Link>
      )}
    </section>
  )
}
