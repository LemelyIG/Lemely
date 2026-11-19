/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties, ReactNode } from "react"
import { cn } from "@/lib/utils"
import { TrendGlyph } from "./icons"
import { clamp01 } from "./rings"
import { RowAction } from "./RowAction"
import "./redesign.css"

export type Trend = "better" | "worse" | "same"

export const TREND_LABEL: Record<Trend, string> = { better: "Better", worse: "Worse", same: "Same" }

export interface RankRowProps {
  rank: number
  title: string
  /** What the child is doing; a node so a SubjectDot can lead it. */
  sub?: ReactNode
  marksLost: number
  trend: Trend
  assigned?: boolean
  /** 0..1 of the list's largest loss: a thin marks-lost bar under the number. */
  bar?: number
  selected?: boolean
  onClick?: () => void
}

/** The parent ranked row (mock pa.js rank / rankBar / .rkr.on). A list item: put it in HairRows. */
export function RankRow({ rank, title, sub, marksLost, trend, assigned, bar, selected, onClick }: RankRowProps) {
  const barPct = bar === undefined ? undefined : Math.round(clamp01(bar) * 100)
  return (
    <li className="rd-hairrow-item">
      <RowAction onClick={onClick} selected={selected} className={cn("rd-rank", barPct !== undefined && "rd-rank-bar", selected && "rd-selected")}>
        <span className="rd-rank-n">{rank}</span>
        <span className="rd-at">
          <b>
            {title}
            {assigned ? <em className="rd-tag">Assigned</em> : null}
          </b>
          {sub !== undefined && sub !== null && sub !== "" ? <span>{sub}</span> : null}
        </span>
        <span className="rd-rank-m" style={barPct !== undefined ? ({ "--w": `${barPct}%` } as CSSProperties) : undefined}>
          <b>{`−${marksLost}`}</b>
          <small>marks</small>
        </span>
        <span className={`rd-trend rd-trend-${trend}`}>
          <TrendGlyph trend={trend} />
          {TREND_LABEL[trend]}
        </span>
      </RowAction>
    </li>
  )
}
