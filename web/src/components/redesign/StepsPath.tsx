/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties } from "react"
import { EMPTY_GHOST_HEIGHTS, type Grade, gradeColorVar, paperCaption, paperSpoken, stepHeight, stepsSummary } from "./grades"
import "./redesign.css"

export interface StepsPaper {
  id: string
  label: string
  grade: Grade
  pct: number
  /** Shown above the label in Mono, e.g. "61/80". */
  caption?: string
  /** Marks; the Mono line is "got/max" when there is no caption, and the bar is named "48 out of 80". */
  marks?: { got: number; max: number }
}

export interface StepsPathProps {
  papers: StepsPaper[]
  goal?: Grade
  onSelect?: (id: string) => void
  /** The goal line as a percentage of the paper; bars scale from 40% up to it. Default 100. */
  goalPct?: number
  /** The whole line under the goal block, e.g. "68/80 · A* line · 7 to go". Default "A* line". */
  goalCaption?: string
  /** Inside the goal block, e.g. "7 to go". */
  goalNote?: string
  /** Outline bars after the papers (sparse) or instead of them (first run). */
  ghosts?: number
  "aria-label"?: string
}

/** "68/80 · A* line" renders as the mock does: the marks in bold Mono, the line name under them. */
function GoalCaption({ text }: { text: string }) {
  const at = text.indexOf(" · ")
  if (at < 0) return <span data-goal="">{text}</span>
  return (
    <span data-goal="">
      <b>{text.slice(0, at)}</b>
      {text.slice(at + 3)}
    </span>
  )
}

const css = (vars: Record<string, string | number>) => vars as CSSProperties

/** The Steps grade path: one solid bar per paper, a solid goal block, letters on one baseline. */
export function StepsPath({ papers, goal, onSelect, goalPct = 100, goalCaption, goalNote, ghosts = 0, "aria-label": ariaLabel }: StepsPathProps) {
  const ghostCount = Math.max(0, ghosts)
  const columns = Math.max(1, papers.length + ghostCount + (goal ? 1 : 0))
  const last = papers.length - 1
  return (
    <div className="rd-steps" data-empty={papers.length === 0 ? "" : undefined} role="group" aria-label={ariaLabel ?? stepsSummary(papers, goal, goalNote)}>
      <div className="rd-steps-track" style={css({ "--n": columns })}>
        {papers.map((p, i) => {
          const style = css({ "--h": `${stepHeight(p.pct, goalPct)}%`, "--c": gradeColorVar(p.grade), "--i": i })
          const current = i === last ? "" : undefined
          return onSelect ? (
            <button key={p.id} type="button" className="rd-step" data-current={current} style={style} aria-label={`${p.grade}, ${paperSpoken(p)}, ${p.label}`} onClick={() => onSelect(p.id)}>
              <b>{p.grade}</b>
            </button>
          ) : (
            <span key={p.id} className="rd-step" data-current={current} style={style} aria-hidden="true">
              <b>{p.grade}</b>
            </span>
          )
        })}
        {Array.from({ length: ghostCount }, (_, i) => (
          <span
            key={`ghost-${i}`}
            className="rd-step"
            data-ghost=""
            aria-hidden="true"
            style={papers.length === 0 ? css({ "--h": `${EMPTY_GHOST_HEIGHTS[i % EMPTY_GHOST_HEIGHTS.length]}%` }) : undefined}
          />
        ))}
        {goal ? (
          <span className="rd-step" data-goal="" aria-hidden="true" style={css({ "--h": "100%", "--i": papers.length })}>
            <b>{goal}</b>
            {goalNote ? <span>{goalNote}</span> : null}
          </span>
        ) : null}
      </div>
      <div className="rd-steps-labels" style={css({ "--n": columns })} aria-hidden="true">
        {papers.map((p, i) => {
          const caption = paperCaption(p)
          return (
            <span key={p.id} data-current={i === last ? "" : undefined}>
              {caption ? <b>{caption}</b> : null}
              {p.label}
            </span>
          )
        })}
        {Array.from({ length: ghostCount }, (_, i) => (
          <span key={`ghost-${i}`} data-ghost="">
            {papers.length ? "next" : ""}
          </span>
        ))}
        {goal ? <GoalCaption text={goalCaption ?? `${goal} line`} /> : null}
      </div>
    </div>
  )
}
