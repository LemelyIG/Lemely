/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"
import { gradeChipClass, gradeTone, type GradeChipSize, type GradeTone } from "@/lib/grade"

/*
 * C-1 Grade badge. Letter grade (A*–G/U) at three sizes, with a hard visual
 * split between an *achieved* result (confident, final: solid Jewel fill
 * where the letter is large text, a solid 2px Jewel border elsewhere) and a
 * *predicted* one (outlined on surface — provisional by construction, per
 * LEMELY_UI_SPEC "predicted should read as provisional"). `estimated` layers
 * on top of either basis: a dashed border plus an always-visible "Estimated"
 * label, because QUALITY-BAR/PRODUCT.md forbid ever presenting boundary-derived
 * data with borrowed precision it doesn't have — this must be legible without
 * relying on hover or color alone.
 */

/*
 * The vocabulary is data now, served per subject and tier by
 * `GET /api/reference` — see `lib/types.ts`'s `Grade` for why this widened to
 * `string` rather than staying a fixed union that omitted grades some
 * subjects genuinely award.
 */
export type Grade = string
export type GradeBand = "top" | "mid" | "borderline" | "fail"
export type GradeBadgeSize = "hero" | "medium" | "inline"
/*
 * P4.5 added `target`. The quiz list rendered a teacher's chosen target grade
 * with `basis="predicted"`, so a column headed "Target grade" showed a badge
 * captioned "Predicted" — the product telling a teacher it forecasts a B when
 * in fact they had asked for one. A target is neither achieved nor predicted;
 * it is an intention, and it is the only one of the three the reader set
 * themselves.
 *
 * It shares `predicted`'s provisional (outlined) styling, because a target is
 * likewise not a fact about a result, and only the caption differs.
 */
export type GradeBadgeBasis = "achieved" | "predicted" | "target"

/** A-star, A and B group into "top"; C/D group "mid"; E is "borderline"; F/G/U are "fail". */
export function gradeBand(grade: string): GradeBand {
  if (grade === "A*" || grade === "A" || grade === "B") return "top"
  if (grade === "C" || grade === "D") return "mid"
  if (grade === "E") return "borderline"
  return "fail"
}

/*
 * Provisional (outlined) chips carry the tone as border colour only (letters are small text, so they stay `text-on-surface`), and
 * Tailwind only emits classes it sees as literals, so the full table is spelled
 * out. Achieved chips use `gradeChipClass` (see `CHIP_SIZE` below).
 */
const toneOutline: Record<GradeTone, string> = {
  "a-star": "border-grade-a-star",
  a: "border-grade-a",
  b: "border-grade-b",
  c: "border-grade-c",
  d: "border-grade-d",
  e: "border-grade-e",
  f: "border-grade-f",
  g: "border-grade-g",
  u: "border-grade-u",
}
const NO_TONE_OUTLINE = "border-outline"

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

/*
 * White letters on a Jewel fill clear only large-text AA (3:1), so an achieved
 * badge keeps its fill only where the letter is large text (>= 18.66px bold):
 * `medium` (32px display rung). `hero` and `inline` letters are 16px and 14px
 * mono, so their achieved badge is the outlined small chip (2px Jewel border,
 * `on-surface` letter); the thicker solid border still separates it from the
 * 1px provisional outline, and provisional badges always carry a caption.
 */
const CHIP_SIZE: Record<GradeBadgeSize, GradeChipSize> = {
  hero: "small",
  medium: "large",
  inline: "small",
}

const padSize: Record<GradeBadgeSize, string> = {
  hero: "px-8 py-6 rounded-xl gap-1.5",
  medium: "px-4 py-3 rounded-lg gap-1",
  inline: "px-2.5 py-1 rounded-md gap-0.5",
}

const labelSize: Record<GradeBadgeSize, string> = {
  hero: "text-eyebrow text-on-surface-variant",
  medium: "text-eyebrow text-on-surface-variant",
  inline: "text-data-sm text-on-surface-variant",
}

export interface GradeBadgeProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /** A*, A, B, C, D, E, F, G, or U. */
  grade: string
  size?: GradeBadgeSize
  /**
   * achieved = a confident final result: a solid Jewel fill at `medium`, the
   * one size whose letter is large text; a solid 2px Jewel border around an
   * `on-surface` letter at `hero` and `inline`, where white on Jewel would fail
   * AA (see CHIP_SIZE). predicted = a forecast,
   * provisional (outlined). target = a grade someone is aiming for, also
   * outlined, and never to be confused with either of the other two.
   */
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
  const tone = gradeTone(grade)
  const provisional = estimated || basis !== "achieved"
  const label = estimated
    ? "Estimated"
    : basis === "predicted"
      ? "Predicted"
      : basis === "target"
        ? "Target"
        : null

  return (
    <div
      role="img"
      aria-label={`${label ? `${label} grade` : "Grade"} ${grade}`}
      className={cn(
        "inline-flex flex-col items-center justify-center leading-none border",
        padSize[size],
        provisional
          ? cn(
              "bg-surface-container-lowest text-on-surface",
              tone ? toneOutline[tone] : NO_TONE_OUTLINE,
              estimated && "border-dashed",
            )
          : CHIP_SIZE[size] === "large"
            ? cn(gradeChipClass(grade, { size: "large" }), "border-transparent")
            : gradeChipClass(grade, { size: "small" }),
        className,
      )}
      {...props}
    >
      {/* `medium` stays on the display rung: it is a section-heading-sized
          badge inside cards whose titles are display type, and a 32px mono
          letter there reads as a paper code. The two rungs that carry a grade
          as a *figure* — hero and inline — are mono. */}
      <span className={cn(size === "medium" && "font-display", letterSize[size])}>{grade}</span>
      {label && <span className={labelSize[size]}>{label}</span>}
    </div>
  )
}
