/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Copy, UploadSimple, Plus } from "@phosphor-icons/react"
import type { GrowthModel, NextAction, Unlock } from "./growth"
import "./home.css"

/** A tick that draws itself once on mount (CSS stroke-dashoffset; static under reduced motion). */
export function DrawnCheck({ size = 16, delay = 0, className }: { size?: number; delay?: number; className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width={size} height={size} className={`th-tick ${className ?? ""}`}>
      <path className="th-tick-path" pathLength={1} d="M5 12.5l4.5 4.5L19 7.5" style={{ animationDelay: `${delay}ms` }} />
    </svg>
  )
}

/** The unlock ladder with its meter: done items quiet and checked, the first locked one emphasised. */
export function UnlockLadder({ unlocks, as: Heading = "h3", headingId }: { unlocks: Unlock[]; as?: "h2" | "h3"; headingId: string }) {
  const done = unlocks.filter((u) => u.done).length
  const firstLocked = unlocks.findIndex((u) => !u.done)
  // The fill starts empty and settles on the next frame, so it animates on mount.
  const [filled, setFilled] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setFilled(true))
    return () => cancelAnimationFrame(id)
  }, [])
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3">
        <Heading id={headingId} className={Heading === "h2" ? "text-display-xs" : "font-bold"}>What fills in as you add more</Heading>
        <span className="shrink-0 text-data-md text-on-surface-variant">{done} of {unlocks.length} unlocked</span>
      </div>
      <div aria-hidden className="mt-3 h-1.5 overflow-hidden rounded-bar bg-surface-container-high">
        <i className="block h-full origin-left bg-primary transition-transform duration-350 ease-expo motion-reduce:transition-none" style={{ transform: `scaleX(${filled ? done / unlocks.length : 0})` }} />
      </div>
      <ul className="mt-4 grid gap-3">
        {unlocks.map((u, i) => {
          const focus = i === firstLocked
          return (
            <li key={u.key} className="flex gap-3">
              {u.done ? (
                <span aria-hidden className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-pill bg-primary-container text-on-primary-container"><DrawnCheck size={12} delay={300 + i * 120} /></span>
              ) : (
                <span aria-hidden className={`mt-0.5 size-5 shrink-0 rounded-pill border-2 border-dashed ${focus ? "border-primary" : "border-outline"}`} />
              )}
              <div className="min-w-0">
                <p className={u.done ? "text-body-sm text-on-surface-variant" : focus ? "font-bold" : "text-body-sm font-bold text-on-surface-variant"}>
                  <span className="sr-only">{u.done ? "Unlocked: " : "Locked: "}</span>{u.title}
                </p>
                {!u.done && <p className="text-body-sm text-on-surface-variant">{u.how}</p>}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

const BTN = "inline-flex items-center gap-2 rounded-button bg-primary px-4 py-2.5 btn-text text-on-primary transition-colors hover:bg-primary-hover"

function ActionButton({ next }: { next: NextAction }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current) }, [])
  if (next.kind === "share" && next.code) {
    const code = next.code
    const copy = async () => {
      try { await navigator.clipboard.writeText(code) } catch { /* clipboard blocked: the code is still visible */ }
      setCopied(true)
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => { timer.current = null; setCopied(false) }, 1600)
    }
    return (
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <code className="rounded-md bg-surface-container-high px-3 py-2 text-data-md text-on-surface">{code}</code>
        <button type="button" onClick={() => void copy()} className={BTN}><Copy size={16} />{copied ? "Copied" : next.cta}</button>
        <span aria-live="polite" className="sr-only">{copied ? "Join code copied" : ""}</span>
      </div>
    )
  }
  const Icon = next.kind === "upload" || next.kind === "second" ? UploadSimple : Plus
  return <Link to={next.to!} className={`mt-4 ${BTN}`}><Icon size={16} />{next.cta}</Link>
}

/** The home's growth panel: one next action and what a fuller classroom unlocks. Absent when complete. */
export function NextUp({ growth }: { growth: GrowthModel }) {
  if (growth.complete) return null
  const { next } = growth
  return (
    <section aria-labelledby={next ? "nu-h" : "nu-l"} className={`grid min-w-0 gap-8 rounded-card bg-surface-container-lowest p-6 shadow-panel ${next ? "lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-12" : ""}`}>
      {next && (
        <div className="min-w-0">
          <h2 id="nu-h" className="text-display-md">{next.title}</h2>
          <p className="mt-2 max-w-prose text-body-md text-on-surface-variant">{next.body}</p>
          <ActionButton next={next} />
        </div>
      )}
      <UnlockLadder unlocks={growth.unlocks} as={next ? "h3" : "h2"} headingId={next ? "nu-l-h" : "nu-l"} />
    </section>
  )
}
