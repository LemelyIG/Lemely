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

const letterSize: Record<GradeBadgeSize, string> = {
  hero: "text-display-hero",
  medium: "text-display-md",
  inline: "text-base font-semibold font-sans",
}

const padSize: Record<GradeBadgeSize, string> = {
  hero: "px-8 py-6 rounded-xl gap-1.5",
  medium: "px-4 py-3 rounded-lg gap-1",
  inline: "px-2.5 py-1 rounded-md gap-0.5",
}

const labelSize: Record<GradeBadgeSize, string> = {
  hero: "text-label-sm text-t2",
  medium: "text-label-sm text-t2",
  inline: "text-metadata text-t3",
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
          ? cn("bg-surface", band.text, band.border, estimated && "border-dashed")
          : cn(band.bg, band.text, "border-transparent"),
        className,
      )}
      {...props}
    >
      <span className={cn("font-serif", letterSize[size])}>{grade}</span>
      {label && <span className={labelSize[size]}>{label}</span>}
    </div>
  )
}
