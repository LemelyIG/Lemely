/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { SmallChevron } from "./icons"
import "./redesign.css"

export interface H2RowProps {
  title: string
  link?: { label: string; to?: string; onClick?: () => void }
  /** The whole title links somewhere, with a small chevron (mock .hlink.h). */
  titleTo?: string
  /** A trailing slot, e.g. the Paper 4 / Paper 2 toggle (mock sjf.js `tog`). Wins over `link`. */
  right?: ReactNode
}

/** A section heading with an optional trailing link or slot (mock .h2row). No eyebrow, ever. */
export function H2Row({ title, link, titleTo, right }: H2RowProps) {
  return (
    <div className="rd-h2row">
      <h2 className="rd-h2">
        {titleTo ? (
          <Link to={titleTo} className="rd-h2link">
            {title}
            <SmallChevron />
          </Link>
        ) : (
          title
        )}
      </h2>
      {right !== undefined ? (
        <div className="rd-h2row-right">{right}</div>
      ) : link ? (
        link.to ? (
          <Link to={link.to} className="rd-lnk">
            {link.label}
          </Link>
        ) : (
          <button type="button" className="rd-lnk" onClick={link.onClick}>
            {link.label}
          </button>
        )
      ) : null}
    </div>
  )
}
