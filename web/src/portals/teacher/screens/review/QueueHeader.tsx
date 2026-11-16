import { useEffect, useRef, useState } from "react"
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
        <span key={bumpKey} className="lm-rq-bump inline-block font-display text-[44px] font-extrabold leading-none tracking-[-0.04em] text-primary tabular-nums shell-sm:text-[48px] shell-lg:text-[56px]" aria-hidden="true">
          {left}
        </span>
        <h1 className="text-[24px] font-extrabold leading-[1.15] tracking-[-0.02em] shell-lg:text-[32px]">
          <span className="sr-only">{left} </span>
          {headerTitle(left, done)}
        </h1>
      </div>
      <div className="h-2 overflow-hidden rounded-[4px] bg-surface-container-high" role="progressbar" aria-label="Answers decided" aria-valuemin={0} aria-valuemax={left + done} aria-valuenow={done}>
        <b className="block h-full rounded-[4px] bg-primary transition-[width] duration-500 ease-[var(--ease-out)] motion-reduce:transition-none" style={{ width: `${progressOf(left, done) * 100}%` }} />
      </div>
    </div>
  )
}
