/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * C-1 Grade badge. Letter grade (A*–G/U) at three sizes, with a hard visual
 * split between an *achieved* result (solid fill — confident, final) and a
 * *predicted* one (outlined on surface — provisional by construction, per
 * LEMELY_UI_SPEC "predicted should read as provisional"). `estimated` layers
 * on top of either basis: a dashed border plus an always-visible "Estimated"
 * label, because QUALITY-BAR/PRODUCT.md forbid ever presenting boundary-derived
 * data with borrowed precision it doesn't have — this must be legible without
 * relying on hover or color alone.
 */

export type Grade = "A*" | "A" | "B" | "C" | "D" | "E" | "F" | "G" | "U"
export type GradeBand = "top" | "mid" | "borderline" | "fail"
export type GradeBadgeSize = "hero" | "medium" | "inline"
export type GradeBadgeBasis = "achieved" | "predicted"

/** A-star, A and B group into "top"; C/D group "mid"; E is "borderline"; F/G/U are "fail". */
export function gradeBand(grade: string): GradeBand {
  if (grade === "A*" || grade === "A" || grade === "B") return "top"
  if (grade === "C" || grade === "D") return "mid"
  if (grade === "E") return "borderline"
  return "fail"
}

const bandClasses: Record<GradeBand, { text: string; bg: string; border: string }> = {
  top: { text: "text-grade-top", bg: "bg-grade-top-bg", border: "border-grade-top" },
  mid: { text: "text-grade-mid", bg: "bg-grade-mid-bg", border: "border-grade-mid" },
  borderline: {
    text: "text-grade-borderline",
    bg: "bg-grade-borderline-bg",
    border: "border-grade-borderline",
  },
  fail: { text: "text-grade-fail", bg: "bg-grade-fail-bg", border: "border-grade-fail" },
}

/*
 * P4.2: the grade letter is mono, not serif.
 *
 * DESIGN.md §4's data face covers "all scores, **grades**, marks, XP, timers,
 * paper codes, IDs", and §4.2's `data-lg` rung is named for exactly this use:
 * "the big number: a score, a predicted grade". This component rendered the
 * letter with `font-serif` at display rungs, so the product's headline grade
 * was set in Newsreader on every screen that shows one. Paired with the same
 * correction in `mark-display.tsx`, the two figures a student reads first —
 * the mark and the grade — now share the face the system reserves for figures,
 * instead of borrowing the heading face.
 *
 * `inline` keeps a distinct treatment because at 16px a mono letter beside
 * body text reads as a code rather than as a grade; it moves to `data-md`,
 * which is the mono rung sized for inline figures.
 */
const letterSize: Record<GradeBadgeSize, string> = {
  hero: "text-data-lg",
  medium: "text-display-md",
  inline: "text-data-md",
}

const padSize: Record<GradeBadgeSize, string> = {
  hero: "px-8 py-6 rounded-xl gap-1.5",
  medium: "px-4 py-3 rounded-lg gap-1",
  inline: "px-2.5 py-1 rounded-md gap-0.5",
}

const labelSize: Record<GradeBadgeSize, string> = {
  hero: "text-eyebrow text-ink-muted",
  medium: "text-eyebrow text-ink-muted",
  inline: "text-data-sm text-ink-faint",
}

export interface GradeBadgeProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /** A*, A, B, C, D, E, F, G, or U. */
  grade: string
  size?: GradeBadgeSize
  /** achieved = confident final result (solid fill). predicted = provisional (outlined). */
  basis?: GradeBadgeBasis
  /**
   * Boundary data behind this grade is incomplete. Forces provisional
   * (outlined) styling regardless of `basis` — an *achieved* grade can still
   * rest on an estimated boundary lookup — plus a dashed border and a
   * permanent "Estimated" label (never a tooltip-only signal).
   */
  estimated?: boolean
}

export function GradeBadge({
  grade,
  size = "medium",
  basis = "achieved",
  estimated = false,
  className,
  ...props
}: GradeBadgeProps) {
  const band = bandClasses[gradeBand(grade)]
  const provisional = estimated || basis === "predicted"
  const label = estimated ? "Estimated" : basis === "predicted" ? "Predicted" : null

  return (
    <div
      role="img"
      aria-label={`${label ? `${label} grade` : "Grade"} ${grade}`}
      className={cn(
        "inline-flex flex-col items-center justify-center leading-none border",
        padSize[size],
        provisional
          ? cn("bg-paper-raised", band.text, band.border, estimated && "border-dashed")
          : cn(band.bg, band.text, "border-transparent"),
        className,
      )}
      {...props}
    >
      {/* `medium` stays on the display rung: it is a section-heading-sized
          badge inside cards whose titles are Newsreader, and a 24px mono
          letter there reads as a paper code. The two rungs that carry a grade
          as a *figure* — hero and inline — are mono. */}
      <span className={cn(size === "medium" && "font-display", letterSize[size])}>{grade}</span>
      {label && <span className={labelSize[size]}>{label}</span>}
    </div>
  )
}
