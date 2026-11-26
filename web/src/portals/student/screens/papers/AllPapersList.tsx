/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties } from "react"
import { HairRow, HairRows } from "@/components/redesign"
import type { PaperRowView } from "./papersModel"
import "../subject/subject.css"
import "./papers.css"

/**
 * One hairline row per attempt, the Subject screen's own row: grade, paper identity, then mark, percent and date in
 * Mono, then how sure the marker was and any teacher correction. In compare mode a row picks instead of opening, and
 * the row is a pressed toggle and shows its pick order (1 earlier pick, 2 later) so the student can see which two are held.
 */
export function AllPapersList({
  rows,
  picks,
  onPick,
  label,
}: {
  rows: PaperRowView[]
  /** Null when rows open their result; the held picks, in the order they were made, when comparing. */
  picks: string[] | null
  onPick: (id: string) => void
  label: string
}) {
  return (
    <HairRows aria-label={label}>
      {rows.map((row) => {
        const order = picks ? picks.indexOf(row.id) : -1
        return (
          <HairRow
            key={row.id}
            to={picks ? undefined : row.to}
            onClick={picks ? () => onPick(row.id) : undefined}
            pressed={picks ? order >= 0 : undefined}
            leading={
              <b className="sj-grade" style={{ "--c": row.colorVar } as CSSProperties}>
                {row.grade}
              </b>
            }
            title={row.title}
            sub={
              <>
                <span className="ap-line">
                  <span className="ap-num">{row.marks}</span> · <span className="ap-num">{row.pct}</span> · {row.date}
                </span>
                {row.confidence || row.corrected ? (
                  <span className="ap-line ap-meta">
                    {row.confidence ? <span>{row.confidence}</span> : null}
                    {row.corrected ? <span className="ap-tag">{row.corrected}</span> : null}
                  </span>
                ) : null}
              </>
            }
            trailing={
              order >= 0 ? (
                <span className="ap-pick">
                  <span className="sr-only">Pick </span>
                  {order + 1}
                </span>
              ) : undefined
            }
          />
        )
      })}
    </HairRows>
  )
}
