/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ElementType } from "react"
import "./redesign.css"

export interface WalkthroughStep {
  /** Optional: the mocks number every tip; an icon replaces the number when given. */
  icon?: ElementType
  title: string
  body?: string
}

/** The first-run walkthrough list (mock .walk2 / .wn2). */
export function Walkthrough({ steps }: { steps: WalkthroughStep[] }) {
  return (
    <ol className="rd-walk">
      {steps.map((step, i) => {
        const Icon = step.icon
        return (
          <li key={step.title}>
            <span className="rd-walk-n" aria-hidden="true">
              {Icon ? <Icon size={18} /> : i + 1}
            </span>
            <span className="rd-at">
              <b>{step.title}</b>
              {step.body ? <span>{step.body}</span> : null}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
