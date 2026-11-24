/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties } from "react"
import { Link } from "react-router-dom"
import type { CompareSide, CompareView } from "./papersModel"
import "../subject/subject.css"
import "./papers.css"

function Side({ side, when }: { side: CompareSide; when: string }) {
  return (
    <div className="ap-cmp-side">
      <span className="ap-cmp-when">{when}</span>
      <b className="sj-grade" style={{ "--c": side.colorVar } as CSSProperties}>
        {side.grade}
      </b>
      <b>{side.title}</b>
      <span>
        <span className="ap-num">{side.marks}</span> · <span className="ap-num">{side.pct}</span>
      </span>
      <span>{side.date}</span>
    </div>
  )
}

/** The two picks side by side, earlier first, what changed in words, and a way into each result. */
export function ComparePanel({ view, picked }: { view: CompareView | null; picked: number }) {
  return (
    <section className="ap-cmp" aria-labelledby="ap-cmp-h" aria-live="polite">
      <h2 id="ap-cmp-h">Compare</h2>
      {view ? (
        <>
          <div className="ap-cmp-sides">
            <Side side={view.earlier} when="Earlier" />
            <Side side={view.later} when="Later" />
          </div>
          <p className="ap-cmp-change">
            {view.change} <small>· {view.grades}</small>
          </p>
          <div className="ap-cmp-links">
            <Link to={view.earlier.to}>Open earlier result</Link>
            <Link to={view.later.to}>Open later result</Link>
          </div>
        </>
      ) : (
        <p className="sj-hint">
          {picked === 0 ? "Pick two papers from the list." : "Pick one more."} <span className="ap-num">{picked}</span> of{" "}
          <span className="ap-num">2</span> picked.
        </p>
      )}
    </section>
  )
}
