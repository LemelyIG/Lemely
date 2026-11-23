/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import { Link } from "react-router-dom"
import { Cards } from "@phosphor-icons/react"
import { SectionHeading } from "./PathSection"
import type { WinView } from "./subjectModel"
import "./subject.css"

/** Topics ranked by marks still to win. Nothing to rank means no section, never an empty heading. */
export function WinList({ win, allTo }: { win: WinView; allTo: string }) {
  if (win.rows.length === 0) return null
  return (
    <section className="sj-win" aria-labelledby="sj-win-h">
      <SectionHeading id="sj-win-h" title={win.heading} to={allTo} />
      <ul role="list">
        {win.rows.map((row) => (
          <li key={row.topic} className="sj-wrow">
            <Link to={row.practiceTo} className="sj-wmain lm-press">
              <span className="sj-at">
                <b>{row.name}</b>
                <span>Practise</span>
              </span>
              <span className="sj-wn">
                +{row.marks}
                <small> marks</small>
              </span>
            </Link>
            {row.flashcardsTo ? (
              <Link to={row.flashcardsTo} className="sj-fc lm-press lm-press-scale" aria-label={`${row.name} flashcards`}>
                <Cards size={18} aria-hidden="true" />
              </Link>
            ) : (
              <span className="sj-fcx" aria-hidden="true" />
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
