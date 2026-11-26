/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { Chevron } from "./icons"
import { RowAction } from "./RowAction"
import "./redesign.css"

export function HairRows({ children, "aria-label": ariaLabel }: { children?: ReactNode; "aria-label"?: string }) {
  return (
    <ul className="rd-hairrows" role="list" aria-label={ariaLabel}>
      {children}
    </ul>
  )
}

export interface HairRowProps {
  leading?: ReactNode
  title: ReactNode
  sub?: ReactNode
  trailing?: ReactNode
  to?: string
  onClick?: () => void
  selected?: boolean
  /** A toggling row (a pick, not a link): aria-pressed, the selected look, and no chevron, which would say it goes somewhere. */
  pressed?: boolean
}

/** One hairline row (mock .wrow / .rp / .arow): leading, title and sub, trailing, chevron when it goes somewhere. */
export function HairRow({ leading, title, sub, trailing, to, onClick, selected, pressed }: HairRowProps) {
  const on = selected || pressed
  return (
    <li className="rd-hairrow-item">
      <RowAction to={to} onClick={onClick} selected={selected} pressed={pressed} className={cn("rd-hairrow", on && "rd-selected")}>
        {leading !== undefined && leading !== null && leading !== "" ? <span className="rd-hr-lead">{leading}</span> : null}
        <span className="rd-at">
          <b>{title}</b>
          {sub !== undefined && sub !== null && sub !== "" ? <span>{sub}</span> : null}
        </span>
        {trailing !== undefined && trailing !== null && trailing !== "" ? <span className="rd-hr-trail">{trailing}</span> : null}
        {(to || onClick) && pressed === undefined ? <Chevron /> : null}
      </RowAction>
    </li>
  )
}
