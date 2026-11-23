/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useRef, type CSSProperties } from "react"
import { CaretRight } from "@phosphor-icons/react"
import { HairRow, HairRows } from "@/components/redesign"
import { SectionHeading } from "./PathSection"
import type { PaperRowView } from "./subjectModel"
import "./subject.css"

/**
 * The All N papers button unmounts the moment it is pressed, which would drop keyboard focus to the page.
 * Focus goes to the first row the press revealed (the row index equals the count that was showing), clamped
 * to the last row; null when there are no rows to land on.
 */
export function focusRowAfterExpand(previouslyVisible: number, total: number): number | null {
  if (total <= 0) return null
  return Math.min(previouslyVisible, total - 1)
}

export function PapersList({ rows, visible, onShowAll }: { rows: PaperRowView[]; visible: number; onShowAll: () => void }) {
  const sectionRef = useRef<HTMLElement>(null)
  /** How many rows were showing when the button was pressed; null when focus has nothing to hand over. */
  const expandedFrom = useRef<number | null>(null)

  useEffect(() => {
    const from = expandedFrom.current
    if (from === null || visible <= from) return
    expandedFrom.current = null
    const index = focusRowAfterExpand(from, rows.length)
    if (index === null) return
    sectionRef.current?.querySelectorAll<HTMLElement>(".rd-hairrow")[index]?.focus()
  }, [visible, rows.length])

  if (rows.length === 0) return null
  return (
    <section className="sj-sec" aria-labelledby="sj-papers-h" ref={sectionRef}>
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
        <button
          type="button"
          className="sj-more lm-press"
          onClick={() => {
            expandedFrom.current = visible
            onShowAll()
          }}
        >
          All {rows.length} papers
          <CaretRight size={12} weight="bold" aria-hidden="true" />
        </button>
      ) : null}
    </section>
  )
}
