import type { CSSProperties } from "react"
import { Link } from "react-router-dom"
import { GHOST_PATH_HEIGHTS, type StepsView } from "./subjectModel"
import "./subject.css"

type Vars = CSSProperties & Record<`--${string}`, string | number>

/**
 * The approved Steps path: one solid bar per attempt on a single baseline, the
 * latest solid in its grade colour, then a soft green goal block (never a
 * dashed outline). Bars run from 40% of the marks up to the goal line.
 *
 * A paper can have no goal line (no boundary resolved): then there is no goal
 * block, label or disclosure, and the bars scale against the paper's full marks.
 */
export function SubjectSteps({
  steps,
  goalExpanded = false,
  onGoal,
}: {
  steps: StepsView
  goalExpanded?: boolean
  onGoal?: () => void
}) {
  const n: Vars = { "--n": steps.bars.length + steps.ghosts + (steps.goal ? 1 : 0) }
  return (
    <div className="sj-steps" role="group" aria-label={steps.groupLabel}>
      <div className="sj-track" style={n}>
        {steps.bars.map((bar) => (
          <Link
            key={bar.id}
            to={bar.resultTo}
            className="sj-stp"
            data-current={bar.current}
            style={{ "--h": `${bar.heightPct}%`, "--c": bar.colorVar } as Vars}
            aria-label={bar.ariaLabel}
          >
            <b aria-hidden="true">{bar.grade}</b>
          </Link>
        ))}
        {Array.from({ length: steps.ghosts }, (_, i) => (
          <span key={`ghost-${i}`} className="sj-stp sj-stp--ghost" aria-hidden="true" />
        ))}
        {steps.goal ? (
          <button
            type="button"
            className="sj-stp sj-stp--goal"
            style={{ "--h": "100%" } as Vars}
            aria-label={steps.goal.ariaLabel}
            aria-expanded={goalExpanded}
            aria-controls="sj-goal-note"
            onClick={onGoal}
          >
            <b aria-hidden="true">{steps.goal.grade}</b>
            <span aria-hidden="true">{steps.goal.gapLabel}</span>
          </button>
        ) : null}
      </div>
      <div className="sj-labels" style={n} aria-hidden="true">
        {steps.bars.map((bar) => (
          <span key={bar.id} data-current={bar.current}>
            <b>
              {bar.marks}
              <small>/{bar.outOf}</small>
            </b>
            {bar.month}
          </span>
        ))}
        {Array.from({ length: steps.ghosts }, (_, i) => (
          <span key={`next-${i}`} className="sj-next">
            next
          </span>
        ))}
        {steps.goal ? (
          <span className="sj-goal-label">
            <b>
              {steps.goal.marks}
              <small>/{steps.goal.outOf}</small>
            </b>
            {steps.goal.grade} line
          </span>
        ) : null}
      </div>
    </div>
  )
}

/** The first-run outline of the path to come. Decorative only. */
export function GhostSteps({ goalGrade = "A*" }: { goalGrade?: string }) {
  const n: Vars = { "--n": GHOST_PATH_HEIGHTS.length + 1 }
  return (
    <div className="sj-steps sj-steps--ghost" aria-hidden="true">
      <div className="sj-track" style={n}>
        {GHOST_PATH_HEIGHTS.map((h) => (
          <span key={h} className="sj-stp sj-stp--ghost" style={{ "--h": `${h}%` } as Vars} />
        ))}
        <span className="sj-stp sj-stp--goal" style={{ "--h": "100%" } as Vars}>
          <b>{goalGrade}</b>
        </span>
      </div>
      <div className="sj-labels" style={n}>
        {GHOST_PATH_HEIGHTS.map((h) => (
          <span key={h} />
        ))}
        <span className="sj-goal-label">{goalGrade} line</span>
      </div>
    </div>
  )
}
