/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import type { CSSProperties } from "react"
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { PaperRowView } from "./subjectModel"
import "./subject.css"

/**
 * The newest few papers. The heading's chevron and the All N papers link under the list both open the All papers
 * screen (S-09), where every attempt can be filtered, sorted and compared. The heading links even when every paper
 * is already showing: the screen is where the filters are.
 */
export function PapersList({ rows, visible, allTo }: { rows: PaperRowView[]; visible: number; allTo: string }) {
  if (rows.length === 0) return null
  return (
    <section className="sj-sec sj-sec--papers" aria-labelledby="sj-papers-h">
      <SectionHeading id="sj-papers-h" title="Papers" to={allTo} />
      <HairRows aria-label="Papers, newest first">
        {rows.slice(0, visible).map((row) => (
          <HairRow
            key={row.id}
            to={row.to}
            leading={
              <b className="sj-grade" style={{ "--c": row.colorVar } as CSSProperties}>
                {row.grade}
              </b>
            }
            title={row.title}
            sub={row.sub}
          />
        ))}
      </HairRows>
      {visible < rows.length ? (
        <Link to={allTo} className="sj-more lm-press">
          All {rows.length} papers
          <CaretRight size={12} weight="bold" aria-hidden="true" />
        </Link>
      ) : null}
    </section>
  )
}
