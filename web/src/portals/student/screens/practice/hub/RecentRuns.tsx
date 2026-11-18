/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { H2Row, HairRow, HairRows } from "@/components/redesign"
import { subjectDotColor } from "../practiceCopy"
import { ClockIcon, ResumeIcon, SubjectDot, TickIcon } from "../practiceIcons"
import type { RecentRow } from "./hubModel"
import { MonoNumbers } from "./MonoNumbers"

const LEADING = {
  resume: { className: "bg-primary text-on-primary", icon: <ResumeIcon /> },
  done: { className: "bg-success-container text-success-text", icon: <TickIcon /> },
  marking: { className: "bg-primary-container text-primary", icon: <ClockIcon /> },
} as const

/**
 * Recent runs: unfinished first (Resume), then marked and marking. Every row
 * opens a page, so rows are links. "See all" expands in place; it is a
 * disclosure, so it carries `aria-expanded` (H2Row's own link button cannot).
 */
export function RecentRuns({
  rows,
  more,
  subjectOrder,
}: {
  rows: readonly RecentRow[]
  more: readonly RecentRow[]
  subjectOrder: readonly string[]
}) {
  const [expanded, setExpanded] = useState(false)
  if (rows.length === 0) return null
  const shown = expanded ? [...rows, ...more] : rows
  return (
    <section aria-label="Recent" className="grid gap-1 [&_.rd-h2row]:min-h-11">
      <H2Row
        title="Recent"
        right={
          more.length > 0 ? (
            <button type="button" className="rd-lnk" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
              {expanded ? "Show less" : "See all"}
            </button>
          ) : undefined
        }
      />
      <HairRows aria-label="Recent practice">
        {shown.map((r) => (
          <HairRow
            key={r.assignmentId}
            leading={
              <span className={`grid size-10 place-items-center rounded-[13px] ${LEADING[r.kind].className}`}>
                {LEADING[r.kind].icon}
              </span>
            }
            title={r.title}
            sub={
              <>
                <SubjectDot color={subjectDotColor(r.subjectCode, subjectOrder)} />
                <MonoNumbers text={r.sub} />
              </>
            }
            trailing={
              r.kind === "resume" ? (
                <span className="inline-flex min-h-11 items-center text-[14px] font-bold text-primary">Resume</span>
              ) : undefined
            }
            to={r.to}
          />
        ))}
      </HairRows>
    </section>
  )
}
