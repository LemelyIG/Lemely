/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V3 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"
import { Eyebrow } from "./primitives"
import { gradeBand } from "./grade-badge"

/*
 * C-3 Boundary bar. "The single most motivating object in the product"
 * (LEMELY_UI_SPEC 2, C-3): a horizontal scale of this paper's grade
 * thresholds with the student's score positioned on it, and the distance to
 * the next boundary up read out in words ("2 marks from an A").
 *
 * Degrades honestly in two ways, per "never invent precision":
 *   - `estimated`: boundary data is incomplete — dashed container border +
 *     a permanent "Estimated boundaries" label (not color alone, not a
 *     tooltip).
 *   - no boundaries at all: an explicit "not available" message rather than
 *     a fabricated bar.
 */

export interface GradeBoundary {
  grade: string
  /** Minimum mark required to reach this grade. */
  minMark: number
}

export interface BoundaryBarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  score: number
  maxScore: number
  boundaries: GradeBoundary[]
  /** Boundary data behind this bar is incomplete (per-subject average fallback, not an exact per-variant lookup). */
  estimated?: boolean
  /** Override the section kicker, for a caller that can name the boundary
   * set more precisely (e.g. "Against the 2024 boundaries"). */
  label?: string
}

const bandBg: Record<string, string> = {
  top: "bg-grade-top",
  mid: "bg-grade-mid",
  borderline: "bg-grade-borderline",
  fail: "bg-grade-fail",
}
const bandText: Record<string, string> = {
  top: "text-grade-top",
  mid: "text-grade-mid",
  borderline: "text-grade-borderline",
  fail: "text-grade-fail",
}

export function BoundaryBar({
  score,
  maxScore,
  boundaries,
  estimated = false,
  label,
  className,
  ...props
}: BoundaryBarProps) {
  const sorted = [...boundaries].sort((a, b) => a.minMark - b.minMark)
  const clampPct = (v: number) => Math.max(0, Math.min(100, (v / Math.max(maxScore, 1)) * 100))
  const scorePct = clampPct(score)
  const next = sorted.find((b) => b.minMark > score)
  const distance = next ? next.minMark - score : null

  return (
    <div
      className={cn(
        "w-full rounded-lg border p-4",
        estimated ? "border-dashed border-rule" : "border-transparent",
        className,
      )}
      {...props}
    >
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        {/* P4.2: the caller may name this section itself. `PaperResult` was
            rendering its own "Against the 2024 boundaries" eyebrow directly
            above this component's, so the flagship screen showed two stacked
            kickers saying almost the same thing with an indented empty widget
            under them. The year is the caller's to know; the fallback stays
            for every other call site. */}
        <Eyebrow>{label ?? (estimated ? "Estimated boundaries" : "Grade boundaries")}</Eyebrow>
        {sorted.length > 0 && (
          <span className="text-body-sm text-ink-muted">
            {next && distance !== null
              ? `${distance} mark${distance === 1 ? "" : "s"} from ${next.grade}`
              : "Top grade reached"}
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <p className="text-body-md text-ink-faint m-0">
          Boundary data isn't available for this paper yet.
        </p>
      ) : (
        <div>
          <div className="relative h-9">
            <div
              className="absolute bottom-0 flex flex-col items-center -translate-x-1/2"
              style={{ left: `${scorePct}%` }}
            >
              <div className="bg-ink text-accent-on text-data-sm px-2 py-1 rounded-md whitespace-nowrap mb-1">
                You, {score}/{maxScore}
              </div>
              <div className="w-0.5 h-2 bg-ink" aria-hidden />
            </div>
          </div>

          <div className="relative h-2 rounded-full overflow-hidden bg-surface-2">
            {sorted.map((b, i) => {
              const start = clampPct(b.minMark)
              const end = i + 1 < sorted.length ? clampPct(sorted[i + 1].minMark) : 100
              return (
                <div
                  key={b.grade}
                  className={cn(
                    "absolute top-0 h-full",
                    bandBg[gradeBand(b.grade)],
                    estimated && "opacity-70",
                  )}
                  style={{ left: `${start}%`, width: `${Math.max(0, end - start)}%` }}
                />
              )
            })}
          </div>

          <div className="relative h-7 mt-1">
            {sorted.map((b) => (
              <div
                key={b.grade}
                className="absolute top-0 flex flex-col items-center -translate-x-1/2"
                style={{ left: `${clampPct(b.minMark)}%` }}
              >
                <div className="w-px h-2 bg-border" aria-hidden />
                <div className={cn("text-metadata mt-1", bandText[gradeBand(b.grade)])}>
                  {b.grade}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
