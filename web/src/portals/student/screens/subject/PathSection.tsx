import { useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { SubjectSteps } from "./SubjectSteps"
import type { GoalStep, PaperTab, PathView, TrendView } from "./subjectModel"
import "./subject.css"

/** An h2 that is a link (with the mock's chevron) only when it has somewhere to go. */
export function SectionHeading({ id, title, to, children }: { id?: string; title: string; to?: string; children?: ReactNode }) {
  return (
    <div className="sj-h2row">
      <h2 id={id} className="sj-h2">
        {to ? (
          <Link to={to} className="lm-press lm-press-scale">
            {title}
            {/* A forward chevron: it must flip under dir="rtl" when Arabic ships. */}
            <CaretRight size={14} weight="bold" aria-hidden="true" />
          </Link>
        ) : (
          title
        )}
      </h2>
      {children}
    </div>
  )
}

/**
 * Which tab an arrow key moves to, or null for any other key. ArrowRight is
 * "forward" in left-to-right layouts and ArrowLeft is under `dir="rtl"`, so the
 * key that points the way the tabs read always advances. Wraps at both ends.
 */
export function nextPaperIndex(index: number, key: string, count: number, rtl: boolean): number | null {
  if (key !== "ArrowRight" && key !== "ArrowLeft") return null
  const forward = key === (rtl ? "ArrowLeft" : "ArrowRight")
  return (index + (forward ? 1 : -1) + count) % count
}

function PaperSwitch({ tabs, selected, onSelect }: { tabs: PaperTab[]; selected: number; onSelect: (n: number) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const rtl = event.currentTarget.closest('[dir="rtl"]') !== null
    const next = nextPaperIndex(index, event.key, tabs.length, rtl)
    if (next === null) return
    event.preventDefault()
    onSelect(tabs[next].paperNumber)
    refs.current[next]?.focus()
  }
  return (
    <div className="sj-ptog" role="tablist" aria-label="Choose a paper">
      {tabs.map((tab, i) => {
        const on = tab.paperNumber === selected
        return (
          <button
            key={tab.paperNumber}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            id={`sj-tab-${tab.paperNumber}`}
            aria-selected={on}
            aria-controls="sj-path-panel"
            tabIndex={on ? 0 : -1}
            onClick={() => onSelect(tab.paperNumber)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {tab.name}
          </button>
        )
      })}
    </div>
  )
}

function TrendLine({ trend }: { trend: TrendView }) {
  if (trend.kind === "single") return <p className="sj-trend">{trend.text}</p>
  return (
    <p className="sj-trend">
      Heading for {trend.article} <b style={{ "--c": trend.colorVar } as CSSProperties}>{trend.forecast}</b> · {trend.change}
    </p>
  )
}

/** "A* line from the May/Jun 2024 boundary." Source labels are sentence-cased in the model; mid-sentence they are not. */
function goalNote(goal: GoalStep): string {
  const source = goal.sourceLabel.replace(/^Average/, "average").replace(/^Estimated/, "estimated")
  return `${goal.grade} line from the ${source}.`
}

export function PathSection({ path, onSelect }: { path: PathView; onSelect: (paperNumber: number) => void }) {
  const [goalOpen, setGoalOpen] = useState(false)
  const switchable = path.tabs.length > 1
  // The goal grade is data, not a constant: a paper with no resolved boundary gets a plain heading.
  const title = path.goalGrade ? `Your path to ${path.goalGrade}` : "Your path"
  return (
    <section className="sj-sec" aria-labelledby="sj-path-h">
      <SectionHeading id="sj-path-h" title={title}>
        {switchable ? <PaperSwitch tabs={path.tabs} selected={path.selected} onSelect={onSelect} /> : null}
      </SectionHeading>
      <div
        className="sj-pbody"
        id="sj-path-panel"
        {...(switchable ? { role: "tabpanel", "aria-labelledby": `sj-tab-${path.selected}` } : {})}
      >
        {/* Keyed by paper so a switch remounts the bars and replays sj-grow. */}
        <SubjectSteps key={path.selected} steps={path.steps} goalExpanded={goalOpen} onGoal={() => setGoalOpen((v) => !v)} />
        <TrendLine trend={path.trend} />
        {path.steps.goal ? (
          <p id="sj-goal-note" className="sj-trend" hidden={!goalOpen}>
            {goalNote(path.steps.goal)}
          </p>
        ) : null}
      </div>
    </section>
  )
}
