/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import type { CSSProperties } from "react"
import { CaretRight } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { PaperRowView } from "./subjectModel"
import "./subject.css"

export function PapersList({ rows, visible, onShowAll }: { rows: PaperRowView[]; visible: number; onShowAll: () => void }) {
  if (rows.length === 0) return null
  return (
    <section className="sj-sec" aria-labelledby="sj-papers-h">
      <SectionHeading id="sj-papers-h" title="Papers" />
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
        <button type="button" className="sj-more lm-press" onClick={onShowAll}>
          All {rows.length} papers
          <CaretRight size={12} weight="bold" aria-hidden="true" />
        </button>
      ) : null}
    </section>
  )
}
