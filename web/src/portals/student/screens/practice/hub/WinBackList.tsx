/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { H2Row, HairRow, HairRows } from "@/components/redesign"
import { buttonVariants } from "@/components/ui/button"
import { subjectDotColor } from "../practiceCopy"
import { SubjectDot } from "../practiceIcons"
import type { WinBackRow } from "./hubModel"

/**
 * Win marks back: the top topics by marks lost. Each row opens the builder sheet
 * focused on that topic, so rows are buttons pushing the builder route with
 * `fromHub` (see HubTiles). `H2Row` has no id prop, so the section is named by
 * `aria-label` rather than `aria-labelledby`.
 */
export function WinBackList({
  rows,
  more,
  subjectOrder,
}: {
  rows: readonly WinBackRow[]
  more: readonly WinBackRow[]
  subjectOrder: readonly string[]
}) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  if (rows.length === 0) return null
  const shown = expanded ? [...rows, ...more] : rows
  return (
    // min-h-11 on the heading row: H2Row is only 44px tall when it has a link, and Recent beside it on desktop always lines up.
    <section aria-label="Win marks back" className="grid gap-1 [&_.rd-h2row]:min-h-11">
      <H2Row title="Win marks back" right={more.length > 0 ? (
        <button type="button" className="rd-lnk" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show less" : "All topics"}
        </button>
      ) : undefined} />
      <HairRows aria-label="Topics to win back">
        {shown.map((r) => (
          <HairRow
            key={`${r.subjectCode}:${r.topic}`}
            title={r.label}
            sub={
              <>
                <SubjectDot color={subjectDotColor(r.subjectCode, subjectOrder)} />
                {r.subjectName}
              </>
            }
            trailing={
              <span className="grid justify-items-end font-mono text-[17px] font-extrabold leading-none text-primary">
                +{r.marks}
                <small className="mt-0.5 font-sans text-[12px] font-semibold text-on-surface-variant">{r.marks === 1 ? "mark" : "marks"}</small>
              </span>
            }
            onClick={() => navigate(r.to, { state: { fromHub: true } })}
          />
        ))}
      </HairRows>
    </section>
  )
}

/** `.tipr` (CS): the sparse nudge to scan more papers. Scan opens a page, so it is a link styled as a button. */
export function ScanTip() {
  return (
    <div className="flex items-center justify-between gap-3 py-3 shadow-[0_-1px_0_var(--color-outline-variant)]">
      <span className="grid gap-0.5">
        <b className="text-[15px] font-bold text-on-surface">More papers, sharper picks</b>
        <span className="text-[13px] text-on-surface-variant">Each paper you scan adds topics here.</span>
      </span>
      <Link to="/student/correct" className={buttonVariants({ variant: "primary", size: "sm", className: "min-h-11 flex-none" })}>
        Scan
      </Link>
    </div>
  )
}
