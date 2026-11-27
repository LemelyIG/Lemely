import type { KeyboardEvent } from "react"
import { radioStep } from "./builderModel"

/**
 * Arrow-key roving for a radiogroup of chips. The group owns the key handler;
 * `select` receives the radio index the key landed on, and focus follows it.
 * Direction is read from the rendered group, so an RTL page swaps the arrows.
 */
export function radioKeyDown(event: KeyboardEvent<HTMLElement>, select: (index: number) => void): void {
  const group = event.currentTarget
  const radios = Array.from(group.querySelectorAll<HTMLElement>('[role="radio"]'))
  const current = radios.indexOf(event.target as HTMLElement)
  if (current < 0) return
  const next = radioStep(event.key, current, radios.length, getComputedStyle(group).direction === "rtl")
  if (next === null) return
  event.preventDefault()
  select(next)
  radios[next]?.focus()
}
