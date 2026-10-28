/* Hallmark · pre-emit critique: P5 H4 E4 S4 R3 V3 — bar, rung list and table are one datum in three forms; the outside-label leader lines are the one fussy part. */
import { useId, useState } from "react"
import { EyeSlash } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { gradeBand, type GradeBand } from "@/components/ui/grade-badge"
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import { StateView } from "@/components/ui/state-views"
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table"
import {
  INSUFFICIENT_RESULTS_HEADING,
  distributionAriaLabel,
  distributionCaption,
  distributionHidden,
  distributionTableRows,
  insufficientResultsBody,
  layoutOrdinal,
} from "@/lib/tutoring/ordinalLayout"
import type { OutcomeDistribution } from "@/lib/tutoringTypes"

/*
 * C-17 Ordinal distribution (SPEC §d, decision-log row 8). A horizontal stacked
 * bar over an ordered grade ladder: one segment per grade that has students,
 * every rung of the ladder listed underneath (a rung nobody reached reads 0),
 * `n` stated, and the same numbers as a real table behind "Show as table".
 *
 * Why it is built the way it is:
 *   - Ordinal, not categorical. Segments run in ladder order and take the grade
 *     band colours of C-1 (`gradeBand`), so the bar reads best-to-worst without
 *     a legend. Colour is never the only carrier: each segment names its grade
 *     and count, and the list below names every rung.
 *   - The ladder comes from the API (`OutcomesDTO.ladder`); nothing here knows
 *     what grades exist.
 *   - Under the figure threshold it draws nothing and says why, in the C-11
 *     empty family. That is `state: "insufficient"`, and also a "sufficient"
 *     figure whose graded count is under `k` (a second guard, so a bad payload
 *     cannot show a small group). It does not draw an empty bar: an empty bar
 *     reads as "no one did well", which is a claim. The hidden state never
 *     shows a count.
 *   - Pure SVG, laid out in percentages so it scales with its container; text is
 *     real SVG text in the data face. Layout decisions (which labels move
 *     outside, how far apart) are in `lib/tutoring/ordinalLayout.ts`.
 *   - The chart is `role="img"` with a full-sentence label; the table is the
 *     text alternative for anyone who wants to read the numbers.
 *
 * Loading is a skeleton of the same height. Error and offline belong to the
 * screen that fetched the figures (`QueryState`, C-11).
 */

const BAR_HEIGHT = 32
const LABEL_ROW_HEIGHT = 36
const LEADER_LENGTH = 10

const bandFill: Record<GradeBand, string> = {
  top: "fill-grade-top-bg stroke-grade-top",
  mid: "fill-grade-mid-bg stroke-grade-mid",
  borderline: "fill-grade-borderline-bg stroke-grade-borderline",
  fail: "fill-grade-fail-bg stroke-grade-fail",
}
const bandInk: Record<GradeBand, string> = {
  top: "fill-grade-top",
  mid: "fill-grade-mid",
  borderline: "fill-grade-borderline",
  fail: "fill-grade-fail",
}
const bandText: Record<GradeBand, string> = {
  top: "text-grade-top",
  mid: "text-grade-mid",
  borderline: "text-grade-borderline",
  fail: "text-grade-fail",
}

export interface OrdinalDistributionProps {
  /** The ordered ladder, best grade first, from `Outcomes.ladder`. */
  ladder: readonly string[]
  distribution: OutcomeDistribution
  /** Names the figure for assistive technology and the table caption. */
  subjectName?: string
  loading?: boolean
  className?: string
}

export function OrdinalDistribution({
  ladder,
  distribution,
  subjectName,
  loading = false,
  className,
}: OrdinalDistributionProps) {
  const [showTable, setShowTable] = useState(false)
  const tableId = useId()

  if (loading) {
    return (
      <div className={cn("flex flex-col gap-3", className)} role="status" aria-label="Loading grades">
        <SkeletonLine announce={false} width="40%" />
        <SkeletonBlock announce={false} className="h-8" />
        <SkeletonLine announce={false} width="70%" />
      </div>
    )
  }

  // Hidden on the server's say-so or on a count under k, whichever comes first.
  // This branch reads `k` and nothing else: no count, no bucket, no rung.
  if (distributionHidden(distribution)) {
    return (
      <StateView
        compact
        kind="empty"
        tone="neutral"
        icon={<EyeSlash size={16} className="text-ink-faint" aria-hidden />}
        heading={INSUFFICIENT_RESULTS_HEADING}
        body={insufficientResultsBody(distribution.k)}
        className={className}
      />
    )
  }

  const layout = layoutOrdinal(ladder, distribution.buckets)
  const ariaLabel = distributionAriaLabel(subjectName, layout)
  const hasOutside = layout.segments.some((s) => s.labelPlacement === "outside")
  const height = BAR_HEIGHT + (hasOutside ? LABEL_ROW_HEIGHT : 0)
  const caption = distributionCaption(distribution.nGraded ?? layout.n, distribution.nWithoutGrade)
  const tableCaption = subjectName ? `${subjectName}: students at each grade` : "Students at each grade"

  return (
    <figure className={cn("m-0 flex flex-col gap-3", className)}>
      {layout.n === 0 ? (
        <p className="m-0 text-body-md text-ink-muted">No grades to show yet.</p>
      ) : (
        <svg
          role="img"
          aria-label={ariaLabel}
          width="100%"
          height={height}
          className="block overflow-visible"
        >
          {layout.segments.map((segment) => {
            const band = gradeBand(segment.grade)
            const text = `${segment.grade} ${segment.count}`
            return (
              <g key={segment.grade}>
                <rect
                  x={`${segment.startPct}%`}
                  y={0}
                  width={`${segment.widthPct}%`}
                  height={BAR_HEIGHT}
                  strokeWidth={1}
                  className={bandFill[band]}
                />
                {segment.labelPlacement === "inside" ? (
                  <text
                    x={`${segment.labelPct}%`}
                    y={BAR_HEIGHT / 2}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className={cn("text-data-sm", bandInk[band])}
                  >
                    {text}
                  </text>
                ) : (
                  <>
                    <line
                      x1={`${segment.centrePct}%`}
                      y1={BAR_HEIGHT}
                      x2={`${segment.labelPct}%`}
                      y2={BAR_HEIGHT + LEADER_LENGTH}
                      strokeWidth={1}
                      className="stroke-rule-strong"
                    />
                    <text
                      x={`${segment.labelPct}%`}
                      y={BAR_HEIGHT + LEADER_LENGTH + 4}
                      textAnchor="middle"
                      dominantBaseline="hanging"
                      className={cn("text-data-sm", bandInk[band])}
                    >
                      {text}
                    </text>
                  </>
                )}
              </g>
            )
          })}
        </svg>
      )}

      {/* Every rung, in ladder order, the empty ones as 0: the visible form of
          "nobody reached this grade", which the bar cannot draw. */}
      <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
        {layout.rungs.map((rung) => (
          <li key={rung.grade} className="flex items-baseline gap-1.5 text-data-sm">
            <span className={bandText[gradeBand(rung.grade)]}>{rung.grade}</span>
            <span className={rung.count === 0 ? "text-ink-muted" : "text-ink"}>{rung.count}</span>
          </li>
        ))}
      </ul>

      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <span className="text-body-sm text-ink-muted">{caption}</span>
        <Button
          variant="ghost"
          size="sm"
          aria-pressed={showTable}
          aria-controls={tableId}
          onClick={() => setShowTable((value) => !value)}
        >
          Show as table
        </Button>
      </figcaption>

      <div id={tableId} hidden={!showTable}>
        <Table density="operate">
          <caption className="px-4 py-2 text-start text-body-sm text-ink-muted">{tableCaption}</caption>
          <THead sticky={false}>
            <tr>
              <TH>Grade</TH>
              <TH numeric>Students</TH>
            </tr>
          </THead>
          <TBody>
            {distributionTableRows(layout).map(([grade, count]) => (
              <TR key={grade}>
                <TH scope="row">{grade}</TH>
                <TD numeric>{count}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </figure>
  )
}
