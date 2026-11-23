/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
import { useEffect, useRef, useState } from "react"
import { PageHeading } from "@/components/ui/page-heading"
import "./review.css"
import { headerTitle, progressOf } from "./reviewQueueModel"

export function QueueHeader({ left, done }: { left: number; done: number }) {
  const [bumpKey, setBumpKey] = useState(0)
  const prev = useRef(left)
  useEffect(() => {
    if (prev.current !== left) setBumpKey((k) => k + 1)
    prev.current = left
  }, [left])
  return (
    <div className="grid gap-3">
      <div className="flex items-baseline gap-2.5">
        <span key={bumpKey} className="rq-bump inline-block font-display text-5xl font-extrabold leading-none tracking-[-0.04em] text-primary tabular-nums shell-lg:text-6xl" aria-hidden="true">
          {left}
        </span>
        <PageHeading repeatsTitle={false} tabIndex={-1} data-review-heading className="outline-none text-2xl font-extrabold leading-[1.15] tracking-[-0.02em] shell-lg:text-3xl">
          <span className="sr-only">{left} </span>
          {headerTitle(left, done)}
        </PageHeading>
      </div>
      <div className="h-2 overflow-hidden rounded-bar bg-surface-container-high" role="progressbar" aria-label="Answers decided" aria-valuemin={0} aria-valuemax={left + done} aria-valuenow={done}>
        <b className="block h-full rounded-bar bg-primary transition-[width] duration-500 ease-[var(--ease-out)] motion-reduce:transition-none" style={{ width: `${progressOf(left, done) * 100}%` }} />
      </div>
    </div>
  )
}
