/* Hallmark · pre-emit critique: P4 H4 E4 S4 R3 V3 */
import type { ReactNode } from "react"
import { Display, Eyebrow } from "./primitives"
import { cn } from "@/lib/utils"
import { PageHeading } from "./page-heading"

/*
 * A page or panel head — eyebrow, title, kicker, action — as one primitive
 * instead of a hand-rolled `<div>` re-derived at every site that needed one
 * (`x-sectionhead-no-equivalent`). Student and teacher Overview, and two of
 * ClassAnalytics's and Review's panel heads, each grew their own version of
 * this same stack with small, accidental differences (a 12px gap here, a
 * 16px one there); this is the version that gets to be the answer.
 *
 * `Display` only ever renders a `<div>` (primitives.tsx is deliberately
 * untouched by this task), so it cannot itself become an `<h1>`/`<h2>`/`<h3>`.
 * The heading tag is rendered *inside* it instead of the other way round —
 * `<Display><Tag>…</Tag></Display>`, a `<div>` wrapping a heading, which is
 * valid nesting — and Tailwind's preflight resets a heading's own font-size,
 * font-weight and margin to `inherit`/`0`, so the tag carries none of its own
 * styling and reads identically to the div's text. `Tag` is computed from
 * `level`, never written as a literal `<h1>`/`<h2>`/`<h3>` — the caller's
 * `level` is the only thing that decides the document outline, so nothing in
 * this file may hardcode a rung of it.
 */

const RUNG_CLASS = {
  "display-lg": "text-display-lg",
  "display-md": "text-display-md",
  "display-sm": "text-display-sm",
} as const

type SectionHeadRung = keyof typeof RUNG_CLASS

export function SectionHead({
  eyebrow,
  title,
  kicker,
  action,
  level = 2,
  rung = "display-md",
  className,
  repeatsTitle,
}: {
  eyebrow?: string
  title: string
  kicker?: string
  action?: ReactNode
  level?: 1 | 2 | 3
  rung?: SectionHeadRung
  className?: string
  /** Level 1 only. Says whether this heading repeats the shell title. When it does, the native
   * frame hides the heading visually (the large title replaces it; still the page's h1 for
   * assistive technology) and drops the eyebrow and kicker, which the phone has no room for. */
  repeatsTitle?: boolean
}) {
  const Tag = `h${level}` as "h1" | "h2" | "h3"
  return (
    // When the large title replaces the heading and there is no action, everything inside is
    // hidden on native: the wrapper leaves the flow too (`sr-only` keeps the h1 for assistive
    // technology) so it does not take a slot in the page's column gap.
    <div className={cn("flex items-end justify-between gap-4", repeatsTitle && !action && "native:sr-only", className)}>
      <div className="flex flex-col gap-1 min-w-0">
        {eyebrow ? <Eyebrow className={cn(repeatsTitle && "native:hidden")}>{eyebrow}</Eyebrow> : null}
        <Display className={RUNG_CLASS[rung]}>
          {/* A level-1 head is the page's own heading: on the native frame it steps below the large title. */}
          {level === 1 && repeatsTitle !== undefined ? (
            <PageHeading repeatsTitle={repeatsTitle}>{title}</PageHeading>
          ) : (
            <Tag data-page-heading={level === 1 ? "own" : undefined}>{title}</Tag>
          )}
        </Display>
        {kicker ? <p className={cn("text-body-md text-on-surface-variant", repeatsTitle && "native:hidden")}>{kicker}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}
