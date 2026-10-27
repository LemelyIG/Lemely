/* Hallmark · pre-emit critique: P5 H4 E4 S4 R4 V3 — neutral ink ramp on purpose (a lower grade is not a mark against the tutor); each segment now has a swatch, icon, word and count beside it. */
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
  gradeChangeHidden,
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
 * Neutral on purpose. The three parts use ink tones (two solid, one hollow), not the
 * grade-band colours and not green or red: a lower grade is a fact about a
 * student, not a mark against the tutor, and colouring it red would say
 * otherwise. Direction is carried by an arrow, an equals sign, and the words,
 * so the figure survives greyscale and a screen reader. A swatch in each list
 * item repeats its segment's fill, so the bar is read through the item and not
 * through lightness alone.
 *
 * Empty parts stay listed with 0. Below the figure threshold (the server's
 * `insufficient`, or fewer than `k` students paired whatever the state says) it
 * draws nothing and says why (C-11 empty family), with no count. The same
 * numbers are available as a table.
 * Loading is a skeleton; error and offline belong to the fetching screen.
 */

const BAR_HEIGHT = 28

const partIcon: Record<GradeChangeKey, Icon> = {
  lower: ArrowDown,
  same: Equals,
  higher: ArrowUp,
}

/* Lower and higher are solid ink tones, "same" is hollow. The ramp used to run rule-strong,
   ink-faint, ink-muted, and rule-strong is a hairline colour: about 1.4:1 against the page in light
   and 1.6:1 in dark, where the lower segment all but vanished (T33). Every tone here clears the 3:1
   a graphical object needs in both themes, and "same" differs by shape, not by lightness, so the
   three still tell apart in greyscale (and by the arrow, the word and the count beside them). */
const partFill: Record<GradeChangeKey, string> = {
  lower: "fill-ink-faint stroke-paper-raised",
  same: "fill-paper-sunk stroke-ink-muted",
  higher: "fill-ink stroke-paper-raised",
}

/* The same three tokens as backgrounds: the swatch beside each part's icon, word
   and count in the list, which is what ties a segment of the bar to its name.
   Lightness alone never has to tell the segments apart. */
const partSwatch: Record<GradeChangeKey, string> = {
  lower: "border-ink-faint bg-ink-faint",
  same: "border-ink-muted bg-paper-sunk",
  higher: "border-ink bg-ink",
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

  // Hidden on the server's say-so or on a paired count under k. This branch
  // reads `k` and nothing else: no count of any part.
  if (gradeChangeHidden(change)) {
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
              className={partFill[part.key]}
            />
          ))}
        </svg>
      )}

      <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-2 p-0">
        {layout.parts.map((part) => {
          const PartIcon = partIcon[part.key]
          return (
            <li key={part.key} className="flex items-center gap-2 whitespace-nowrap text-body-md text-ink">
              <span
                aria-hidden
                className={cn("h-3 w-3 shrink-0 rounded-sm border", partSwatch[part.key])}
              />
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
