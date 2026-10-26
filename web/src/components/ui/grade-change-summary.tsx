/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useId, useState } from "react"
import { ArrowDown, ArrowUp, Equals, EyeSlash, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import { StateView } from "@/components/ui/state-views"
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table"
import {
  GRADE_CHANGE_TITLE,
  gradeChangeAriaLabel,
  gradeChangeCaption,
  gradeChangeTableRows,
  layoutGradeChange,
  type GradeChangeKey,
} from "@/lib/tutoring/gradeChange"
import { INSUFFICIENT_RESULTS_HEADING, insufficientResultsBody } from "@/lib/tutoring/ordinalLayout"
import type { OutcomeChange } from "@/lib/tutoringTypes"

/*
 * C-18 Grade change summary (SPEC §d, decision-log rows 8, 8b and 15e). Three
 * counts under one fixed title: students whose grade was lower, the same, or
 * higher while they had this tutor.
 *
 * The title is fixed and not a prop. "Change in grade while with this tutor" is
 * the wording the user locked: it describes a change that happened while a
 * student had this tutor, and does not say the tutor caused it (students choose
 * their tutors, so the figure cannot show that).
 *
 * Neutral on purpose. The three parts use a light-to-dark ink ramp, not the
 * grade-band colours and not green or red: a lower grade is a fact about a
 * student, not a mark against the tutor, and colouring it red would say
 * otherwise. Direction is carried by an arrow, an equals sign, and the words,
 * so the figure survives greyscale and a screen reader.
 *
 * Empty parts stay listed with 0. Below the figure threshold it draws nothing
 * and says why (C-11 empty family). The same numbers are available as a table.
 * Loading is a skeleton; error and offline belong to the fetching screen.
 */

const BAR_HEIGHT = 28

const partIcon: Record<GradeChangeKey, Icon> = {
  lower: ArrowDown,
  same: Equals,
  higher: ArrowUp,
}

/* A lightness ramp of the ink tokens: lower is the lightest, higher the darkest. */
const partFill: Record<GradeChangeKey, string> = {
  lower: "fill-rule-strong",
  same: "fill-ink-faint",
  higher: "fill-ink-muted",
}

export interface GradeChangeSummaryProps {
  change: OutcomeChange
  /** The heading element for the fixed title, to fit the page's outline. */
  headingAs?: "h2" | "h3" | "h4"
  loading?: boolean
  className?: string
}

export function GradeChangeSummary({
  change,
  headingAs: Heading = "h3",
  loading = false,
  className,
}: GradeChangeSummaryProps) {
  const [showTable, setShowTable] = useState(false)
  const titleId = useId()
  const tableId = useId()

  const title = (
    <Heading id={titleId} className="m-0 text-label text-ink">
      {GRADE_CHANGE_TITLE}
    </Heading>
  )

  if (loading) {
    return (
      <div className={cn("flex flex-col gap-3", className)} role="status" aria-label="Loading grade change">
        <SkeletonLine announce={false} width="55%" />
        <SkeletonBlock announce={false} className="h-7" />
        <SkeletonLine announce={false} width="70%" />
      </div>
    )
  }

  if (change.state === "insufficient") {
    return (
      <div className={cn("flex flex-col gap-3", className)}>
        {title}
        <StateView
          compact
          kind="empty"
          tone="neutral"
          icon={<EyeSlash size={16} className="text-ink-faint" aria-hidden />}
          heading={INSUFFICIENT_RESULTS_HEADING}
          body={insufficientResultsBody(change.k)}
        />
      </div>
    )
  }

  const layout = layoutGradeChange(change)
  const n = change.nPaired ?? layout.n

  return (
    <figure className={cn("m-0 flex flex-col gap-3", className)} aria-labelledby={titleId}>
      {title}

      {layout.n === 0 ? (
        <p className="m-0 text-body-md text-ink-muted">No grades to compare yet.</p>
      ) : (
        <svg
          role="img"
          aria-label={gradeChangeAriaLabel(layout)}
          width="100%"
          height={BAR_HEIGHT}
          className="block"
        >
          {layout.parts.map((part) => (
            <rect
              key={part.key}
              x={`${part.startPct}%`}
              y={0}
              width={`${part.widthPct}%`}
              height={BAR_HEIGHT}
              strokeWidth={2}
              className={cn(partFill[part.key], "stroke-paper-raised")}
            />
          ))}
        </svg>
      )}

      <ul className="m-0 grid list-none grid-cols-1 gap-2 p-0 sm:grid-cols-3">
        {layout.parts.map((part) => {
          const PartIcon = partIcon[part.key]
          return (
            <li key={part.key} className="flex items-center gap-2 text-body-md text-ink">
              <PartIcon size={16} weight="bold" className="shrink-0 text-ink-muted" aria-hidden />
              <span>{part.label}</span>
              <span className="text-data-md">{part.count}</span>
            </li>
          )
        })}
      </ul>

      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <span className="text-body-sm text-ink-muted">{gradeChangeCaption(n)}</span>
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
          <caption className="px-4 py-2 text-start text-body-sm text-ink-muted">
            {GRADE_CHANGE_TITLE}
          </caption>
          <THead sticky={false}>
            <tr>
              <TH>Change</TH>
              <TH numeric>Students</TH>
            </tr>
          </THead>
          <TBody>
            {gradeChangeTableRows(layout).map(([label, count]) => (
              <TR key={label}>
                <TH scope="row">{label}</TH>
                <TD numeric>{count}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </figure>
  )
}
