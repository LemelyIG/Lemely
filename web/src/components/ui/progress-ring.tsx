/* Hallmark · pre-emit critique: P4 H4 E5 S4 R5 V3 */
import { cn } from "@/lib/utils"
import type { ProgressTone } from "@/components/ui/progress-bar"

/*
 * Grading.tsx's auto-grading ring, extracted. It was `CIRC = 2 * Math.PI *
 * 42` plus a `dash` local recomputed inline, on one screen, with no test —
 * the exact "duplication risk" shape `ProgressBar` already avoided for the
 * linear case. This file gives the circular case the same treatment: a pure
 * function for the math (testable under D3.20's no-jsdom runner) and a
 * component for the SVG.
 *
 * DESIGN.md §9.2 permits animating `transform`/`opacity` only.
 * `stroke-dasharray` is neither, so this ring — like Grading's original —
 * changes value in a single discrete paint rather than sweeping toward it.
 * `ProgressBar`'s determinate fill gets its motion from `scaleX`, a transform
 * a bar can use because its fill is a rectangle; a ring's fill has no
 * transform equivalent, so the honest answer here is "don't animate it",
 * not "animate the wrong property anyway".
 */

const TONE_STROKE_CLASSES: Record<ProgressTone, string> = {
  accent: "stroke-accent",
  ok: "stroke-ok",
  err: "stroke-err",
}

/**
 * Dash-array pair for an SVG ring's value stroke: `value` (0–100, clamped)
 * of `circumference` filled, the remainder the gap. Pure and DOM-free so the
 * arithmetic is pinned without mounting the ring.
 */
export function ringDash(value: number, circumference: number): string {
  const clamped = Math.max(0, Math.min(100, value))
  return `${((circumference * clamped) / 100).toFixed(1)} ${circumference.toFixed(1)}`
}

export interface ProgressRingProps {
  /** 0–100. */
  value: number
  tone?: ProgressTone
  /** The whole accessible sentence (e.g. "12 of 30 papers graded") — mirrors
   * `ProgressBar`'s `label`. There is no separate `ariaLabel`: unlike a bar, a
   * ring has no room for a visible label beside it, so this is always the
   * sole accessible name. */
  label: string
  size?: number
  strokeWidth?: number
  className?: string
}

/** A circular determinate progress meter — the tile-shaped sibling to
 * `ProgressBar`'s linear one. `--paper-sunk`-equivalent track (`--rule`) plus
 * a tone-coloured value arc. */
export function ProgressRing({
  value,
  tone = "accent",
  label,
  size = 48,
  strokeWidth = 4,
  className,
}: ProgressRingProps) {
  const radius = size / 2 - strokeWidth / 2
  const circumference = 2 * Math.PI * radius
  const dash = ringDash(value, circumference)

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      width={size}
      height={size}
      // Starts the arc at 12 o'clock rather than SVG's native 3 o'clock, the
      // same convention Grading's original ring used.
      className={cn("-rotate-90", className)}
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
        className="stroke-border"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={dash}
        className={TONE_STROKE_CLASSES[tone]}
      />
    </svg>
  )
}
