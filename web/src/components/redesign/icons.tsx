/* Hallmark · pre-emit critique: P3 H3 E3 S4 R4 V3 */
import type { TopicState } from "./topics"

/* The mock's drawn stroke icons (t.js CHEV/SUB/CAL/FLAME, sjf.js IC, pa.js AR). Decorative: aria-hidden. */

export function Chevron() {
  return (
    <svg className="rd-chev" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M7 4l5 5-5 5" />
    </svg>
  )
}

export function SmallChevron() {
  return (
    <svg className="rd-chev" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M6 3.5 10.5 8 6 12.5" />
    </svg>
  )
}

export function CalendarGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" focusable="false">
      <rect x="3" y="4.5" width="14" height="12" rx="2.5" />
      <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
    </svg>
  )
}

export function FlameGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M10 2.5c.5 3 4.5 4.5 4.5 9a4.5 4.5 0 0 1-9 0c0-2 1-3.2 2-4 .2 1.6 1 2.4 2 2.6C9 8 9.5 5 10 2.5Z" />
    </svg>
  )
}

const TOPIC_PATHS: Record<TopicState, React.ReactNode> = {
  secure: <path d="M2.5 6.3 5 8.6l4.5-5" />,
  getting: <path d="M2.5 6h7" />,
  work: (
    <>
      <circle cx="6" cy="6" r="3.6" />
      <circle cx="6" cy="6" r=".6" fill="currentColor" />
    </>
  ),
}

/** Target for Work on (never a down arrow), dash for Getting there, tick for Secure. */
export function TopicGlyph({ state }: { state: TopicState }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {TOPIC_PATHS[state]}
    </svg>
  )
}

const TREND_PATHS = {
  better: "M6 10V2.5M2.8 5.5 6 2.3l3.2 3.2",
  worse: "M6 2v7.5M2.8 6.5 6 9.7l3.2-3.2",
  same: "M2 6h8",
} as const

export function TrendGlyph({ trend }: { trend: keyof typeof TREND_PATHS }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={TREND_PATHS[trend]} />
    </svg>
  )
}
